"""Building the STAC collections and searching the portal by area.

``register_collections`` turns the portal's product list into STAC
collections with licence and credit; ``spatial`` splits a search area into
tiles small enough for the portal's result limit.

Every function is a pure transformation except ``fetch_archive``, which
calls the bhoonidhi-downloader SDK to read the portal's product list.
"""
