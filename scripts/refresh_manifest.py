"""Regenerate the collections manifest from the portal's product list.

Run from the repository root when the portal adds or ends a product:

    uv run python scripts/refresh_manifest.py

It reads the product list with bhoonidhi-downloader (no login), builds one
entry per satellite and sensor with the library's own functions, and
rewrites src/bhoonidhi_stac/data/collections-manifest.json in the portal's
order, so an unchanged product list leaves the file unchanged. Then run
scripts/collections_md.py so docs/collections.md matches.
"""

from __future__ import annotations

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


def main() -> int:
    entries = entries_from(fetch_archive())
    before = {e["collection_id"] for e in json.loads(MANIFEST.read_text())}
    MANIFEST.write_text(json.dumps(entries))
    after = {e["collection_id"] for e in entries}
    print(f"{len(entries)} collections written to {MANIFEST}")
    print(f"added: {sorted(after - before) or 'none'}")
    print(f"removed: {sorted(before - after) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
