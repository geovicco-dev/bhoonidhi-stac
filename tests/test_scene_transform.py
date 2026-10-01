"""Tests for the portal-scene to STAC-item transform (core/database.py).

Covers the tiled-product case where PATHNO carries a tile token (for example
N36E068) rather than a numeric orbit path. The transform must still produce a
valid item instead of raising and dropping the scene.
"""

from __future__ import annotations

from bhoonidhi_stac.core.database import DatabaseManager
from bhoonidhi_stac.schemas import DatabaseSchema


def _manager():
    return DatabaseManager(DatabaseSchema())


def _tiled_scene():
    # Shape taken from a real ResourceSat-2 AWIFS gridded-tile scene: PATHNO is
    # a tile token, and the orbit fields are empty. Carries the fields the SDK
    # URL builders and classifiers read, so the transform runs end to end.
    return {
        "ID": "R2_W_zzz_01APR2023_15APR2023_15_N36E068_JTGN00GTD",
        "FILENAME": "R2_W_zzz_01APR2023_15APR2023_15_N36E068_JTGN00GTD",
        "DIRPATH": "/imgarchive/PRODUCTJPGS//RS2/AWIF/2023/APR/01/",
        "SATELLITE": "RS2",
        "SENSOR": "AWIF",
        "PATHNO": "N36E068",
        "DOP": "01-Apr-2023",
        "TABLETYPE": "PMETA",
        "PRICED": "OpenData_x",
        "PRODTYPE": "10x10deg-tiles",
        "PRODCODE": "JTGN00GTD",
        "ROLL": "0.000000",
        "PASS_TYPE": "",
        "ImgCrnNWLat": "46.00079",
        "ImgCrnNWLon": "67.9996",
        "ImgCrnNELat": "46.00079",
        "ImgCrnNELon": "78.0001",
        "ImgCrnSELat": "36.000352",
        "ImgCrnSELon": "78.0001",
        "ImgCrnSWLat": "36.000352",
        "ImgCrnSWLon": "67.9996",
    }


def test_tiled_scene_transforms_without_dropping():
    # Before the fix, int(PATHNO) raised on the tile token and the scene was
    # skipped, so a whole gridded product landed zero items.
    item = _manager()._ensure_stac_item(_tiled_scene(), "resourcesat-2-awifs")
    assert item is not None
    assert item["type"] == "Feature"
    assert item["id"] == "R2_W_zzz_01APR2023_15APR2023_15_N36E068_JTGN00GTD"
    assert item["collection"] == "resourcesat-2-awifs"
    assert item["properties"]["PATHNO"] == "N36E068"


def test_portal_orbit_fields_stay_raw_fields_only():
    # PATHNO numbers ground tracks by position, not orbits in flying order;
    # PASS_TYPE holds reception codes (SSR, D, X, ...) and ROLL a signed roll
    # angle. None matches the meaning of a sat or view field, so all stay as
    # the portal's own fields and the item declares no extension.
    scene = _tiled_scene()
    scene["PATHNO"] = "94"
    scene["ROW"] = "52"
    scene["PASS_TYPE"] = "SSR"
    scene["ROLL"] = "-12.5"
    item = _manager()._ensure_stac_item(scene, "resourcesat-2a-liss3")
    assert item is not None
    props = item["properties"]
    assert props["PATHNO"] == "94"
    assert props["ROW"] == "52"
    assert props["PASS_TYPE"] == "SSR"
    assert props["ROLL"] == "-12.5"
    assert not [k for k in props if k.startswith(("sat:", "view:", "eo:"))]
    assert item["stac_extensions"] == []
