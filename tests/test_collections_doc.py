"""docs/collections.md must match the collections manifest."""

from __future__ import annotations

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "collections_md.py"


def test_collections_doc_is_current():
    script = runpy.run_path(str(SCRIPT))
    assert script["DOC"].read_text() == script["render"](), (
        "docs/collections.md is out of date; run: uv run python scripts/collections_md.py"
    )
