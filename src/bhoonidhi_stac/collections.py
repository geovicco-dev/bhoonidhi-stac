"""The collections the STAC API serves, and what each one is.

``data/collections-manifest.json`` lists one entry per collection (satellite,
sensor, products with their operational windows, and the portal's access
level). An ingest registers these collections, then fills them with
scenes.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from bhoonidhi_stac.ops.register_collections import build_stac_collection

# Every scene search and every collection extent covers this box (India).
INDIA_AOI = {"min_lon": 68.0, "min_lat": 6.0, "max_lon": 98.0, "max_lat": 38.0}


def load_manifest() -> list[dict[str, Any]]:
    """The collections manifest, one dict per collection."""
    text = (
        resources.files("bhoonidhi_stac")
        .joinpath("data/collections-manifest.json")
        .read_text()
    )
    return json.loads(text)


def stac_collections() -> list[dict[str, Any]]:
    """Every collection in the manifest as a STAC collection, with licence and credit."""
    return [build_stac_collection(entry, INDIA_AOI) for entry in load_manifest()]
