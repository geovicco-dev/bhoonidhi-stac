"""Regenerate the collections manifest from the portal's product list.

Run from the repository root when the portal adds or ends a product:

    uv run python scripts/refresh_manifest.py --refresh

It reads the product list with bhoonidhi-downloader (no login), builds one
entry per satellite and sensor with the library's own functions, and
rewrites src/bhoonidhi_stac/data/collections-manifest.json in the portal's
order, so an unchanged product list leaves the file unchanged. Then run
scripts/collections_md.py so docs/collections.md matches.

Without --refresh it reads the downloader's saved copy of the product list
in ~/.bhoonidhi/, which may be older than the portal's.

A product or collection the manifest already has stays in it when the
portal stops listing it, and the script prints what it kept.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bhoonidhi_stac.ops.register_collections import (
    fetch_archive,
    generate_collection_config,
)

MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "bhoonidhi_stac"
    / "data"
    / "collections-manifest.json"
)

# The fields each manifest entry keeps; everything else about a collection
# is derived from these when it is built.
FIELDS = ("collection_id", "satellite", "sensor", "product_windows", "access_level")


def entries_from(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Manifest entries for parsed product-list records, in the portal's order."""
    return [
        {k: config[k] for k in FIELDS}
        for record in records
        for config in generate_collection_config(record)
    ]


def keep_unlisted(
    previous: list[dict[str, Any]], entries: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Add back what the portal no longer lists but the manifest already has.

    The portal can drop a product from its list while its scenes stay
    searchable (IRS-1A's original LISS1 and LISS2 products did this when a
    Level-2 product replaced them in the list). The ingest names partitions
    after products and collections, so dropping one would make its ingested
    weeks look never run. An unlisted product keeps its window and goes
    after the listed ones; an unlisted collection keeps its whole entry and
    goes at the end. Returns the entries and one line per thing kept.
    """
    old_by_id = {e["collection_id"]: e for e in previous}
    listed_ids = {e["collection_id"] for e in entries}
    kept: list[str] = []
    merged = []
    for entry in entries:
        old = old_by_id.get(entry["collection_id"])
        if old is not None:
            tokens = {w["token"] for w in entry["product_windows"]}
            unlisted = [w for w in old["product_windows"] if w["token"] not in tokens]
            if unlisted:
                entry = {
                    **entry,
                    "product_windows": entry["product_windows"] + unlisted,
                }
                for w in unlisted:
                    kept.append(
                        f"{entry['collection_id']}: {w['token'] or '(default)'}"
                    )
        merged.append(entry)
    for old in previous:
        if old["collection_id"] not in listed_ids:
            merged.append(old)
            kept.append(f"{old['collection_id']}: whole collection")
    return merged, kept


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the collections manifest from the portal's product list."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="read the product list from the portal instead of the saved copy",
    )
    args = parser.parse_args()
    previous = json.loads(MANIFEST.read_text())
    entries, kept = keep_unlisted(
        previous, entries_from(fetch_archive(refresh=args.refresh))
    )
    before = {e["collection_id"] for e in previous}
    MANIFEST.write_text(json.dumps(entries))
    after = {e["collection_id"] for e in entries}
    print(f"{len(entries)} collections written to {MANIFEST}")
    print(f"added: {sorted(after - before) or 'none'}")
    print(f"no longer listed by the portal, kept: {kept or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
