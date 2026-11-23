# Changelog

## [0.1.0] - unreleased

The first public release.

### Added

- The collection list: one collection per satellite and sensor (79), with
  each product's acquisition dates and the portal's access level.
- STAC collections with licence and credit: ISRO-IRS for ISRO data, each
  foreign mission's operator, `proprietary` for priced data, and a link to
  the Bhoonidhi End User License Agreement.
- Portal scene to STAC item, and pgSTAC setup, collection registration and
  upserts (pypgstac 0.9.12).
- Search-area splitting (a quadtree) so no search loses scenes to the
  portal's 500-result limit.
- `scripts/refresh_manifest.py` rebuilds the collection list from the
  portal; `scripts/collections_md.py` writes docs/collections.md from it.

### Fixed

- Every collection has a description, built from its manifest entry
  (sensor and satellite, acquisition dates, operator, access), and its
  summaries list each product's resolution and name.
- A collection's extent follows its scenes from the moment it is
  registered: first to newest scene date, and a box around every scene
  footprint. Before, a collection kept the registered India box and
  product dates until new scenes arrived, so collections whose products
  had ended never showed their scenes' coverage. A collection with no
  scenes yet shows its product windows and the India box.
- A search box given with heights (six numbers) searches its map box
  instead of failing with a server error. Scene footprints carry no
  height, so the heights are ignored.
- Items and collections declare no STAC extension. The eo, sat and view
  fields the items carried did not fit those extensions: the portal's
  path number, pass type and roll angle stay as its own fields.
- NovaSAR-1 is credited to SSTL, which operates it; the Sentinel credit
  links to the EU's Copernicus pages.
- A search that filters on product or availability across every
  collection answers at once instead of reading every scene: both get an
  index. The API's `/queryables` lists resolution, product and
  availability with what each means.
- `scripts/refresh_manifest.py --refresh` reads the product list from the
  portal. Without the flag it reads the downloader's saved copy, as
  before, which can be older than the portal's.
- Suomi-NPP VIIRS ends on 2 November 2026, the date the portal now gives
  for its three products. The weekly ingest no longer searches weeks
  after it, which the portal refuses.
- IRS-1A LISS1 and LISS2 add the portal's Level-2 orthorectified product
  (`L2`, direct download). Their original product, which the portal no
  longer lists but still serves, stays with its scenes.
  `scripts/refresh_manifest.py` keeps any product or collection the
  portal stops listing, and prints what it kept.
- bhoonidhi-downloader moves from 0.5.6 to 0.6.0. It can search a
  product whose portal name has no suffix on its own (product `Others`,
  listed here as `(default)`), and it still searches a product the portal
  no longer lists.

### Security

- The certificate bundle, certifi, moves from 2026.7.22 to 2026.10.23.
  That release removes three emSign root certificates (emSign ECC Root
  CA - G3, emSign Root CA - C1 and emSign ECC Root CA - C3), its fix for
  the advisory about compromised emSign intermediate CA keys. The
  Bhoonidhi portal client (bhoonidhi-downloader, through requests) checks
  the portal's certificate against this bundle.
