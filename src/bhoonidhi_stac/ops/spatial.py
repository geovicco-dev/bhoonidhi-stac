"""Adaptive quadtree spatial partitioning for Bhoonidhi scene search.

The portal caps every search POST at 500 scenes; the downloader's
recursive paging gets past that for most sensors, but a few (EOS-04, NISAR)
truncate at 500. Partitioning the search AOI so no single query matches more
than the cap recovers their complete scene set, and is a harmless safety net
for everything else (upsert de-duplicates any overlap).

This module is pure orchestration: it decides how to slice a bounding box and
calls a caller-supplied ``search`` function for each cell. It holds no HTTP,
no SDK, and no database code, so live ingest and backfill share one path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# A search function takes a bbox (min_lon, min_lat, max_lon, max_lat) and
# returns the list of scene dicts matching it for the caller's fixed window.
SearchFn = Callable[[float, float, float, float], list[dict[str, Any]]]


@dataclass
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def split(self) -> list[BBox]:
        """Four equal quadrants at the midpoints."""
        mx = (self.min_lon + self.max_lon) / 2
        my = (self.min_lat + self.max_lat) / 2
        return [
            BBox(self.min_lon, self.min_lat, mx, my),  # SW
            BBox(mx, self.min_lat, self.max_lon, my),  # SE
            BBox(self.min_lon, my, mx, self.max_lat),  # NW
            BBox(mx, my, self.max_lon, self.max_lat),  # NE
        ]

    def is_smaller_than(self, min_deg: float) -> bool:
        return (self.max_lon - self.min_lon) <= min_deg or (
            self.max_lat - self.min_lat
        ) <= min_deg


@dataclass
class QuadtreeResult:
    """The complete, auditable outcome of one partitioned search."""

    scenes: dict[str, dict] = field(default_factory=dict)  # scene_id -> scene
    calls: int = 0
    kept_cells: int = 0
    max_depth: int = 0
    # Regions skipped because their first children came back empty.
    skipped_low_yield: list[dict] = field(default_factory=list)
    # Cells a stop-guard halted while still at the cap (possible residual loss).
    residual_capped: list[dict] = field(default_factory=list)

    @property
    def scene_count(self) -> int:
        return len(self.scenes)


def _scene_id(scene: dict) -> str | None:
    return scene.get("ID") or scene.get("sceneId") or scene.get("id")


def partition_search(
    aoi: BBox,
    search: SearchFn,
    *,
    cap_threshold: int = 490,
    max_depth: int = 5,
    min_cell_deg: float = 0.5,
    empty_skip_fraction: float = 0.20,
) -> QuadtreeResult:
    """Search ``aoi`` with an adaptive quadtree and return the unioned scenes.

    A cell is searched once. If it comes back under ``cap_threshold`` it is
    complete and kept. If it is at/near the cap it is subdivided and its
    children recursed — unless a stop-guard (``max_depth`` or ``min_cell_deg``)
    forbids it, in which case the cell is kept but recorded as possibly still
    truncated. When a subdivided cell's first children are empty (the first
    ``empty_skip_fraction`` of them), the region is flagged low-yield and its
    remaining children are skipped and recorded.

    Scenes are unioned by scene id, so overlapping cells are safe.
    """
    result = QuadtreeResult()

    def keep(scenes: list[dict]) -> None:
        result.kept_cells += 1
        for s in scenes:
            sid = _scene_id(s)
            if sid:
                result.scenes[sid] = s

    def recurse(box: BBox, depth: int, scenes: list[dict]) -> None:
        result.max_depth = max(result.max_depth, depth)
        n = len(scenes)

        # Complete set for this area.
        if n < cap_threshold:
            keep(scenes)
            return

        # At/near cap but a guard forbids splitting: keep, but flag as
        # potentially still truncated so nothing is lost silently.
        if depth >= max_depth or box.is_smaller_than(min_cell_deg):
            keep(scenes)
            result.residual_capped.append(
                {
                    "bbox": (box.min_lon, box.min_lat, box.max_lon, box.max_lat),
                    "count": n,
                    "depth": depth,
                    "guard": "max_depth" if depth >= max_depth else "min_cell_size",
                }
            )
            return

        # Capped and allowed to split: search children, with empty-skip.
        children = box.split()
        empty_budget = max(1, round(len(children) * empty_skip_fraction))
        empties = 0
        for i, child in enumerate(children):
            child_scenes = search(
                child.min_lon, child.min_lat, child.max_lon, child.max_lat
            )
            result.calls += 1
            if not child_scenes:
                empties += 1
                # Only bail on a leading run of empties (the region is barren).
                if empties == i + 1 and empties >= empty_budget:
                    result.skipped_low_yield.append(
                        {
                            "parent_bbox": (
                                box.min_lon,
                                box.min_lat,
                                box.max_lon,
                                box.max_lat,
                            ),
                            "reason": "LOW_YIELD",
                            "empty_children_seen": empties,
                            "depth": depth,
                        }
                    )
                    break
                continue
            recurse(child, depth + 1, child_scenes)

    root_scenes = search(aoi.min_lon, aoi.min_lat, aoi.max_lon, aoi.max_lat)
    result.calls += 1
    recurse(aoi, 0, root_scenes)
    return result
