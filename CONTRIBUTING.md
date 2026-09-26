# Contributing

Reports of wrong or missing metadata, questions, documentation fixes and
code are all welcome.

- **Wrong or missing metadata:** open an issue with the scene id, the
  collection, and what the portal shows for that scene.
- **A bug in the library:** open an issue with the steps to reproduce it.
- **A change:** fork, branch from `main`, and open a pull request.

## Setup

You need [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync
```

## Checks

Every pull request runs these; run them before you push:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Add or update a test for any change in behaviour. For a bug fix, a test that
fails before the fix and passes after is the one to write.

## What belongs in a change

- The library turns portal metadata into STAC. It never downloads imagery
  and never logs in to the portal.
- Every collection credits its producer and names NRSC/ISRO Bhoonidhi as
  host and licensor, with the Bhoonidhi licence link. Keep
  `tests/test_stac_licensing.py` passing.
- A change to the collection list comes from
  `scripts/refresh_manifest.py`, followed by `scripts/collections_md.py`,
  never from editing `collections-manifest.json` by hand.

## Commits

Conventional commit titles (`feat: …`, `fix: …`, `docs: …`), one change per
commit, with a body that says why.
