"""Tests for stac_licensing / attribution.

Pure function, no I/O — asserts the per-collection licence, the rel=license
link, and per-source provider credit are correct across the source families in
the real 79-collection manifest.
"""

from __future__ import annotations

import pytest

from bhoonidhi_stac.ops.register_collections import (
    BHOONIDHI_EULA_URL,
    stac_licensing,
)


def _provider_names(result):
    return [p["name"] for p in result["providers"]]


def test_priced_is_proprietary_not_open():
    r = stac_licensing("CartoSat-3", "Priced")
    assert r["license"] == "proprietary"


def test_open_is_other_never_blanket_open():
    r = stac_licensing("ResourceSat-2A", "Open")
    # The bug this fixes: a bare "open" is not a valid SPDX id and mislabels
    # priced data. "other" is the accurate non-blanket value.
    assert r["license"] == "other"


def test_onorder_is_other():
    assert stac_licensing("RISAT-1", "OnOrder")["license"] == "other"


def test_every_collection_credits_bhoonidhi_as_licensor():
    # NRSC/ISRO Bhoonidhi is host+licensor on EVERY collection, regardless of
    # the original producer.
    for sat in ("CartoSat-3", "Sentinel-2A", "LandSat-9", "Terra"):
        r = stac_licensing(sat, "Open")
        bhoonidhi = [p for p in r["providers"] if "Bhoonidhi" in p["name"]]
        assert len(bhoonidhi) == 1
        assert set(bhoonidhi[0]["roles"]) == {"host", "licensor"}


def test_license_link_points_at_eula():
    r = stac_licensing("EOS-06", "Open")
    assert r["license_link"]["rel"] == "license"
    assert r["license_link"]["href"] == BHOONIDHI_EULA_URL


@pytest.mark.parametrize(
    "satellite,expected_producer",
    [
        # ISRO / IRS family
        ("CartoSat-3", "ISRO"),
        ("ResourceSat-2A", "ISRO"),
        ("OceanSat-2", "ISRO"),
        ("RISAT-1", "ISRO"),
        ("EOS-04", "ISRO"),
        ("IRS-1C", "ISRO"),
        # non-IRS — each under its own operator
        ("Sentinel-1A", "Copernicus/ESA"),
        ("Sentinel-2C", "Copernicus/ESA"),
        ("LandSat-8", "USGS"),
        ("LandSat-9", "USGS"),
        ("Terra", "NASA"),
        ("Aqua", "NASA"),
        ("MetOp-B", "EUMETSAT"),
        ("KompSat-3A", "KARI"),
        ("Novasar-1", "SSTL/UKSA"),
        ("NOAA-19", "NOAA"),
    ],
)
def test_producer_credit_per_source(satellite, expected_producer):
    r = stac_licensing(satellite, "Open")
    producers = [p for p in r["providers"] if "producer" in p["roles"]]
    assert len(producers) == 1
    assert producers[0]["name"] == expected_producer


def test_unknown_satellite_falls_back_to_isro_producer():
    # Never leave a collection uncredited — unknown source defaults to ISRO
    # (the portal's own default source).
    r = stac_licensing("SomeFutureSat-1", "Open")
    producers = [p for p in r["providers"] if "producer" in p["roles"]]
    assert producers[0]["name"] == "ISRO"


def test_isro_producer_carries_the_irs_caption():
    for sat in ("ResourceSat-2A", "EOS-04", "SomeFutureSat-1"):
        producer = next(
            p
            for p in stac_licensing(sat, "Open")["providers"]
            if "producer" in p["roles"]
        )
        assert producer["description"] == "Credit: ISRO-IRS"
    sentinel = next(
        p
        for p in stac_licensing("Sentinel-2A", "Open")["providers"]
        if "producer" in p["roles"]
    )
    assert "description" not in sentinel


def test_manifest_access_reaches_the_collection_licence():
    # The ingest registers collections from its manifest. Every entry must
    # carry the portal's access level, or build_stac_collection cannot tell a
    # priced collection from an open one and labels them all "other".
    import json
    from pathlib import Path

    from bhoonidhi_stac.ops.register_collections import build_stac_collection

    manifest_path = (
        Path(__file__).parents[1] / "src/bhoonidhi_stac/data/collections-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    aoi = {"min_lon": 68.0, "min_lat": 6.0, "max_lon": 98.0, "max_lat": 38.0}
    licences = {}
    for entry in manifest:
        assert entry.get("access_level") in {"DirectDownload", "OnOrder", "Priced"}, (
            entry["collection_id"]
        )
        licences[entry["collection_id"]] = build_stac_collection(entry, aoi)["license"]
    priced = {cid for cid, lic in licences.items() if lic == "proprietary"}
    assert {"cartosat-3-pan-spot", "cartosat-3-mx-spot"} <= priced
    assert "resourcesat-2a-liss4-mx70" not in priced
