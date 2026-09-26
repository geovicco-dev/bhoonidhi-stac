# bhoonidhi-stac

Scene metadata from ISRO's [Bhoonidhi](https://bhoonidhi.nrsc.gov.in)
archive as a [STAC](https://stacspec.org) catalogue, and the Python library
that builds it.

**Catalogue:** https://bhoonidhi-stac.ecotrakr.in

Search the metadata without an account or API approval. Downloading still
needs your own free Bhoonidhi account.

> Unofficial. Not affiliated with or endorsed by ISRO or NRSC. The catalogue
> holds metadata and links only; no imagery is stored or served. It comes
> with no uptime guarantee.

## What the catalogue holds

- 79 collections, one per satellite and sensor, from 41 satellites: ISRO's
  own and the foreign missions Bhoonidhi distributes (Sentinel-1 and -2,
  Landsat 8 and 9, Terra and Aqua, MetOp, NOAA, Suomi NPP, JPSS-1, NISAR,
  NovaSAR-1, KOMPSAT-3 and -3A). [docs/collections.md](docs/collections.md)
  lists them all.
- For each scene: its footprint, date, satellite and sensor, product,
  whether it can be downloaded directly or must be ordered, a link to its
  quicklook, and the portal's own fields.
- Scenes from 1988 onwards. A weekly update adds the latest week of every
  product still being acquired, so the catalogue runs up to a week behind
  the portal.

## Search it

Any STAC client works. With
[pystac-client](https://github.com/stac-utils/pystac-client):

```python
from pystac_client import Client

catalogue = Client.open("https://bhoonidhi-stac.ecotrakr.in")
search = catalogue.search(
    collections=["resourcesat-2a-liss3"],
    bbox=[77.0, 28.4, 77.4, 28.8],  # around Delhi
    datetime="2026-09-01/2026-09-15",
)
for item in search.items():
    print(item.id, item.datetime.date(), item.properties["bhoonidhi:availability"])
```

To download a scene you find, use
[`bhd`](https://github.com/geovicco-dev/bhoonidhi-downloader) with your own
Bhoonidhi account, or ask an AI assistant through
[bhoonidhi-mcp](https://github.com/geovicco-dev/bhoonidhi-mcp).
[bhoonidhi-explorer](https://github.com/geovicco-dev/bhoonidhi-explorer)
searches this catalogue in plain words on a map.

## How it is built

[docs/methods.md](docs/methods.md) covers the details:

1. The portal's product list becomes one collection per satellite and sensor.
2. Each week, the portal is searched over India, product by product. A
   search area that hits the portal's 500-scene limit is split into
   quarters until every part fits.
3. Each portal scene becomes a STAC item and is stored in pgSTAC with an
   upsert, so searching a week again never adds copies.

The library in this repository does steps 1 and 3 and the splitting in
step 2. Scheduling the weekly run is not part of it.

## Licence and credit

The scene metadata belongs to NRSC/ISRO and is used under the
[Bhoonidhi End User License Agreement](https://bhoonidhi.nrsc.gov.in/bhoonidhi/htmls/TnC.html).
Credit ISRO data as "ISRO-IRS". Data from other missions also carries its
operator's terms; each collection names its operator in `providers`.
Collections of priced data are marked `license: proprietary`.

The code in this repository is MIT licensed ([LICENSE](LICENSE)).

## Use the library

```bash
uv add git+https://github.com/geovicco-dev/bhoonidhi-stac
```

```python
from bhoonidhi_stac.collections import stac_collections

collections = stac_collections()  # 79 STAC collections with licence and credit
```

| Module | What it does |
|---|---|
| `collections` | The collection list and each collection as STAC |
| `ops/register_collections.py` | The portal's product list to collections, with licence and credit |
| `ops/spatial.py` | Splits a search area until each part fits the portal's result limit |
| `core/database.py` | Portal scene to STAC item; pgSTAC setup, collection registration and upserts |

Python 3.12 or later. The pgSTAC database must run pgSTAC 0.9.12, the
version pypgstac is pinned to.

## Report a problem

Open an [issue](https://github.com/geovicco-dev/bhoonidhi-stac/issues) for
wrong or missing metadata, with the scene id and the collection. Security
problems: see [SECURITY.md](SECURITY.md).

## Develop

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

When the portal adds or ends a product, `uv run python
scripts/refresh_manifest.py` rebuilds the collection list, and `uv run
python scripts/collections_md.py` updates docs/collections.md.
