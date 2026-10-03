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
- Items and collections declare no STAC extension. The eo, sat and view
  fields the items carried did not fit those extensions: the portal's
  path number, pass type and roll angle stay as its own fields.
- NovaSAR-1 is credited to SSTL, which operates it; the Sentinel credit
  links to the EU's Copernicus pages.
