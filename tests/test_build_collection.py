"""Tests for build_stac_collection: description, extent and summaries.

The collections are built from the real 79-entry manifest, so these also
check the manifest carries what the collections need.
"""

from __future__ import annotations

import pytest

from bhoonidhi_stac.collections import load_manifest, stac_collections
from bhoonidhi_stac.ops.register_collections import build_stac_collection

AOI = {"min_lon": 68.0, "min_lat": 6.0, "max_lon": 98.0, "max_lat": 38.0}


def _entry(**overrides):
    entry = {
        "collection_id": "resourcesat-2a-liss3",
        "satellite": "ResourceSat-2A",
        "sensor": "LISS3",
        "access_level": "DirectDownload",
        "product_windows": [
            {
                "token": "BOA-Archives",
                "operational_start": "2016-12-18",
                "operational_end": None,
                "resolution_m": 23.5,
            },
            {
                "token": "L2",
                "operational_start": "2017-01-01",
                "operational_end": None,
                "resolution_m": 23.5,
            },
        ],
    }
    entry.update(overrides)
    return entry


@pytest.fixture(scope="module")
def collections():
    return stac_collections()


def test_every_collection_has_a_description(collections):
    # STAC requires a non-empty description; stac-api-validator fails the
    # collections class on an empty one.
    assert len(collections) == 79
    assert all(c["description"].strip() for c in collections)


def test_description_wording_for_an_open_acquiring_collection():
    c = build_stac_collection(_entry(), AOI)
    assert c["description"] == (
        "LISS3 scenes from ResourceSat-2A in the Bhoonidhi archive of NRSC/ISRO, "
        "acquired since 2016-12-18. ResourceSat-2A is operated by ISRO. "
        "Open data, downloaded directly from Bhoonidhi with a free account."
    )


def test_description_wording_for_a_retired_collection():
    windows = [
        {
            "token": "",
            "operational_start": "1996-11-14",
            "operational_end": "2007-09-20",
            "resolution_m": 5.8,
        }
    ]
    c = build_stac_collection(
        _entry(
            collection_id="irs-1c-pan",
            satellite="IRS-1C",
            sensor="PAN",
            access_level="OnOrder",
            product_windows=windows,
        ),
        AOI,
    )
    assert c["description"] == (
        "PAN scenes from IRS-1C in the Bhoonidhi archive of NRSC/ISRO, "
        "acquired from 1996-11-14 to 2007-09-20. IRS-1C is operated by ISRO. "
        "Open data, ordered free of charge on Bhoonidhi before download."
    )


def test_temporal_extent_follows_the_product_windows():
    acquiring = build_stac_collection(_entry(), AOI)
    assert acquiring["extent"]["temporal"]["interval"] == [
        ["2016-12-18T00:00:00Z", None]
    ]
    retired = _entry(
        product_windows=[
            {
                "token": "a",
                "operational_start": "2001-01-01",
                "operational_end": "2005-06-30",
                "resolution_m": 5.8,
            },
            {
                "token": "b",
                "operational_start": "1999-03-01",
                "operational_end": "2007-09-20",
                "resolution_m": 5.8,
            },
        ]
    )
    assert build_stac_collection(retired, AOI)["extent"]["temporal"]["interval"] == [
        ["1999-03-01T00:00:00Z", "2007-09-20T00:00:00Z"]
    ]


def test_summaries_list_each_resolution_and_product_once():
    windows = [
        {
            "token": "L2",
            "operational_start": "2011-05-08",
            "operational_end": None,
            "resolution_m": 56.0,
        },
        {
            "token": "10x10deg-tiles_5day_100m",
            "operational_start": "2012-01-01",
            "operational_end": None,
            "resolution_m": 100.0,
        },
        {
            "token": "",
            "operational_start": "2011-05-08",
            "operational_end": None,
            "resolution_m": 56.0,
        },
    ]
    s = build_stac_collection(_entry(product_windows=windows), AOI)["summaries"]
    assert s["gsd"] == [56.0, 100.0]
    # The default product (empty token) is not a product name.
    assert s["bhoonidhi:products"] == ["L2", "10x10deg-tiles_5day_100m"]


def test_empty_summaries_are_left_out():
    # A sensor with only its default product has no product names; STAC does
    # not allow an empty summary list, so the key is left out.
    windows = [
        {
            "token": "",
            "operational_start": "1996-11-14",
            "operational_end": "2007-09-20",
            "resolution_m": 5.8,
        }
    ]
    s = build_stac_collection(_entry(product_windows=windows), AOI)["summaries"]
    assert "bhoonidhi:products" not in s
    assert s["gsd"] == [5.8]


def test_manifest_gives_every_product_a_resolution():
    for entry in load_manifest():
        for window in entry["product_windows"]:
            assert isinstance(window["resolution_m"], float), (
                entry["collection_id"],
                window["token"],
            )
            assert window["resolution_m"] > 0


def test_no_collection_has_an_empty_summary_or_an_open_start(collections):
    for c in collections:
        assert all(c["summaries"].values()), c["id"]
        assert c["summaries"]["gsd"], c["id"]
        start, _ = c["extent"]["temporal"]["interval"][0]
        assert start, c["id"]


def test_collections_declare_no_extension(collections):
    # Collections carry no sat, view or eo fields of their own, so they
    # declare no extension.
    assert all(not c.get("stac_extensions") for c in collections)
