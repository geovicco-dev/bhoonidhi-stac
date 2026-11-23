"""scripts/refresh_manifest.py keeps what the portal stops listing."""

from __future__ import annotations

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "refresh_manifest.py"
keep_unlisted = runpy.run_path(str(SCRIPT))["keep_unlisted"]


def window(token, start="1988-04-04", end: str | None = "1991-05-28"):
    return {
        "token": token,
        "operational_start": start,
        "operational_end": end,
        "resolution_m": 73.0,
    }


def entry(cid, windows, access="OnOrder"):
    return {
        "collection_id": cid,
        "satellite": "IRS-1A",
        "sensor": "LISS1",
        "product_windows": windows,
        "access_level": access,
    }


def test_unchanged_list_leaves_entries_unchanged():
    previous = [entry("a", [window("")]), entry("b", [window("L1"), window("L2")])]
    merged, kept = keep_unlisted(previous, [dict(e) for e in previous])
    assert merged == previous
    assert kept == []


def test_product_dropped_from_the_list_stays_after_the_listed_ones():
    previous = [entry("irs-1a-liss1", [window("")])]
    listed = [entry("irs-1a-liss1", [window("L2")], access="DirectDownload")]
    merged, kept = keep_unlisted(previous, listed)
    assert [w["token"] for w in merged[0]["product_windows"]] == ["L2", ""]
    assert merged[0]["access_level"] == "DirectDownload"
    assert kept == ["irs-1a-liss1: (default)"]


def test_listed_product_takes_the_portal_window():
    previous = [entry("a", [window("L1", end=None)])]
    listed = [entry("a", [window("L1", end="2026-11-02")])]
    merged, kept = keep_unlisted(previous, listed)
    assert merged[0]["product_windows"] == [window("L1", end="2026-11-02")]
    assert kept == []


def test_collection_dropped_from_the_list_stays_at_the_end():
    previous = [entry("gone", [window("")]), entry("a", [window("")])]
    listed = [entry("a", [window("")]), entry("new", [window("")])]
    merged, kept = keep_unlisted(previous, listed)
    assert [e["collection_id"] for e in merged] == ["a", "new", "gone"]
    assert merged[2] == previous[0]
    assert kept == ["gone: whole collection"]
