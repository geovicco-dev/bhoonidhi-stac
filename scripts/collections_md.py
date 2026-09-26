"""Write docs/collections.md from the collections manifest.

Run from the repository root after the manifest changes:

    uv run python scripts/collections_md.py

tests/test_collections_doc.py fails when the committed file is out of date.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bhoonidhi_stac.collections import load_manifest, stac_collections

DOC = Path(__file__).resolve().parent.parent / "docs" / "collections.md"

ACCESS = {
    "DirectDownload": "open, direct download",
    "OnOrder": "open, on order",
    "Priced": "priced",
}


def _period(entry: dict) -> str:
    windows = entry["product_windows"]
    start = min(w["operational_start"] for w in windows if w.get("operational_start"))
    ends = [w.get("operational_end") for w in windows]
    end = "acquiring" if any(e is None for e in ends) else max(ends)
    return f"{start} to {end}"


def _products(entry: dict) -> str:
    tokens = [w["token"] or "(default)" for w in entry["product_windows"]]
    return ", ".join(tokens)


def render() -> str:
    collections = {c["id"]: c for c in stac_collections()}
    rows = []
    for entry in sorted(load_manifest(), key=lambda e: e["collection_id"]):
        collection = collections[entry["collection_id"]]
        producer = next(
            p["name"] for p in collection["providers"] if "producer" in p["roles"]
        )
        rows.append(
            f"| `{entry['collection_id']}` | {entry['satellite']} | {entry['sensor']} "
            f"| {_products(entry)} | {producer} | {ACCESS[entry['access_level']]} "
            f"| {_period(entry)} |"
        )
    lines = [
        "# Collections",
        "",
        "Every collection the portal lists, one per satellite and sensor, built from",
        "`src/bhoonidhi_stac/data/collections-manifest.json`. `scripts/collections_md.py`",
        "writes this page; do not edit it by hand.",
        "",
        "- **Producer**: the satellite's operator, credited in the collection's",
        "  `providers`. NRSC/ISRO Bhoonidhi is the host and licensor of every",
        "  collection.",
        "- **Access**: the portal's access level. Open data is downloaded directly",
        "  or ordered free of charge; priced data is sold.",
        '- **Period**: when the products were acquired. "acquiring" means at least',
        "  one product is still being added.",
        "",
        f"{len(rows)} collections.",
        "",
        "| Collection | Satellite | Sensor | Products | Producer | Access | Period |",
        "|---|---|---|---|---|---|---|",
        *rows,
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if DOC.read_text() != text:
            print(f"{DOC} is out of date; run: uv run python scripts/collections_md.py")
            return 1
        return 0
    DOC.parent.mkdir(exist_ok=True)
    DOC.write_text(text)
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
