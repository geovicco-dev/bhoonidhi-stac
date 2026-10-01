# Methods

How the data behind the STAC API is built from the Bhoonidhi portal and
kept current. The steps below are what the code in this repository does;
the scheduler that runs them is not part of it.

## Source

Every scene comes from ISRO's Bhoonidhi portal
(https://bhoonidhi.nrsc.gov.in), run by NRSC. Scenes are found with the
portal's own search, the same search anyone can run on its website without
an account, through
[bhoonidhi-downloader](https://github.com/geovicco-dev/bhoonidhi-downloader).
The API serves metadata and links only. Nothing here downloads imagery.

## Collections

The portal publishes its product list: satellites, sensors, products,
acquisition dates and access level (`bhd archive` shows it).
`ops/register_collections.py` turns that list into one collection per
satellite and sensor, 79 in all. Each collection records:

- its products, each with the dates it was acquired over (the product
  window) and the resolution the portal gives for it;
- the portal's access level: open for direct download, open on order, or
  priced;
- licence and credit (below);
- a description built from the above: sensor and satellite, acquisition
  dates, operator and access.

The collection's temporal extent spans its product windows and stays open
while any product is still acquired. Its summaries list the resolutions and
products. Collections declare no STAC extension.

The list is kept in `src/bhoonidhi_stac/data/collections-manifest.json`.
`scripts/refresh_manifest.py` rebuilds it from the portal's current product
list; a product the portal adds appears once it is rerun.
[collections.md](collections.md) shows every collection.

## Searching the portal

Each search covers one product and one week over India (68°E to 98°E, 6°N
to 38°N). A week outside the product's window is not searched.

The portal returns at most 500 scenes for one search. The downloader pages
past that for most sensors; for a few (EOS-04 and NISAR) paging stops at
500, and the rest would be lost without a trace. `ops/spatial.py` guards
against this with a quadtree:

1. Search the whole box.
2. If the result holds 490 scenes or more, split the box into four equal
   quarters and search each; repeat inside any quarter that is still full.
3. Stop splitting at depth 5, or when a side is shorter than half a degree.
   A cell that stops while still full is kept and reported, because it may
   still be missing scenes.
4. If the first quarters of a split come back empty, skip that split's
   other quarters and record the skip.

Scenes from all cells are merged by scene id, so overlapping cells never
produce duplicates. Each run reports how many searches it made, how deep it
went, and any cell that stopped while full.

## From portal scene to STAC item

`DatabaseManager._transform_bhoonidhi_scene_to_stac` in `core/database.py`
turns one portal result into a STAC item:

| STAC | From |
|---|---|
| `id` | The portal's scene id |
| `geometry`, `bbox` | The four image corners the portal reports |
| `datetime` | The date of pass (`DOP`), at 00:00 UTC; the portal gives no time. A scene whose date cannot be read gets the date it was stored |
| `platform`, `instruments` | The portal's satellite and sensor codes |
| `gsd` | The sensor's resolution in metres, from the portal's product list |
| `bhoonidhi:access` | `Open`, `OnOrder` or `Priced` |
| `bhoonidhi:availability`, `bhoonidhi:downloadable` | Whether the scene could be downloaded directly when it was last searched |
| `bhoonidhi:product_type`, `bhoonidhi:product_code`, `bhoonidhi:selection`, `bhoonidhi:quality_score` | The portal's product fields |
| `assets.thumbnail` | The scene's quicklook on the portal |
| `assets.metadata` | The portal's metadata file, for open scenes that have one |

The item also keeps every raw field the portal returned (about 55: corner
coordinates, orbit numbers, `DOP`, `SATELLITE`, `SENSOR`, `SELECTION` and
others), so nothing from the source is lost. The ingest adds
`bhoonidhi:product`, the product the scene was found under.

Items declare no STAC extension. The portal's path (`PATHNO`), pass type
(`PASS_TYPE`) and roll angle (`ROLL`) stay as its own fields, because none
means what the matching extension field means: path numbers count ground
tracks by their position on the ground, where the sat extension's relative
orbit counts orbits in the order they are flown; the pass type holds the
portal's own codes (such as SSR and PLD), not ascending or descending; and
a roll angle is not an azimuth.

The portal's metadata carries no reliable cloud cover, so
`bhoonidhi:cloud_cover` is always empty. `bhoonidhi:downloaded` and
`bhoonidhi:status` hold fixed values (`false`, `L0`). pgSTAC does not store
empty values: a field with nothing in it, such as cloud cover, is absent
from the stored item.

## Storing

Items are written to a pgSTAC database with pypgstac. Every write is an
upsert keyed by scene id: searching the same week again replaces the
scenes it finds and never adds a copy. Before the first write,
`ensure_pgstac_schema` creates or migrates the pgSTAC schema.

## Keeping it current

Once a week, the ingest searches the most recent week of every product and
stores what it finds. A product whose acquisition has ended has no new
weeks, so only products still being acquired produce searches. A week that
fails is searched again on a later run. Older weeks are filled on request,
week by week, with the same search; because every write is an upsert,
filling a week twice is harmless.

The API is therefore up to a week behind the portal. Availability can
change after a scene is stored: a scene that could be downloaded directly
may later need ordering. `bhd` searches the live portal when you run it.

## Licence and credit

Every collection names two providers: the satellite's operator as
`producer`, and NRSC/ISRO Bhoonidhi as `host` and `licensor`, with a
`rel="license"` link to the Bhoonidhi End User License Agreement. ISRO
collections carry the credit the agreement asks for, "ISRO-IRS". Other
missions (Copernicus/ESA, USGS, EUMETSAT, NOAA, NASA, KARI, SSTL) name
their operator, whose terms also apply. Collections of priced data carry
`license: proprietary`; the rest carry `other`, because the agreement is not
a standard open licence. `tests/test_stac_licensing.py` checks each case.

## Checks on every run

- **No scene lost on write:** the collection's scene count must not drop
  across a write.
- **No full cell left:** no quadtree cell stopped while still at the limit.
- **An open week is not empty:** a week inside a product's window that
  returns nothing is flagged, since it may be a portal outage.
