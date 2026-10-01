"""Fetch, parse, and transform the Bhoonidhi archive into collection configs.

Data flow
---------
Portal (SatSenServlet)
  → SDK ``client.archive.list()``   raw portal dicts
  → ``fetch_archive()``             parsed, per-satellite dicts
  → ``generate_collection_config()`` per-collection config
  → ``build_stac_collection()``      the STAC collection registered in pgSTAC
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# ---------------------------------------------------------------------------
# 0. STAC licensing + attribution
# ---------------------------------------------------------------------------
#
# Every collection served through the STAC API is redistribution of ISRO
# portal content, permitted under the Bhoonidhi open-data grant ONLY with
# accurate licensing and per-source credit. This block encodes that once, at
# registration, so every downstream consumer (web footer, QGIS providers
# panel, notebook header, MCP output) inherits it.
#
# Bhoonidhi/NRSC distributes every collection under its EULA, so it is the
# `licensor` + `host` on all of them. The original satellite operator is the
# `producer`; non-IRS sources carry their own provider per the EULA's Non-IRS
# clause. IRS data is captioned "ISRO-IRS" (the EULA's exact wording).

# The governing distribution licence for everything on the portal: the
# terms page the portal itself links as its End User License Agreement.
BHOONIDHI_EULA_URL = "https://bhoonidhi.nrsc.gov.in/bhoonidhi/htmls/TnC.html"

# The credit the EULA asks for on IRS data, in its own wording.
IRS_CAPTION = "ISRO-IRS"

# NRSC / ISRO — distributor + licensor on EVERY collection.
_BHOONIDHI_PROVIDER: dict[str, Any] = {
    "name": "NRSC/ISRO Bhoonidhi",
    "roles": ["host", "licensor"],
    "url": "https://bhoonidhi.nrsc.gov.in/",
}

# Original producer keyed by satellite-name prefix (longest match first). Each
# value is (provider name, url). ISRO entries carry the "ISRO-IRS" caption;
# other missions are credited to their own operators, whose terms apply
# alongside the EULA (Sentinel→Copernicus/ESA, Landsat→USGS, MODIS→NASA),
# with the remaining operators by public record.
# TODO: check each non-IRS provider's credit wording against its own terms.
_PRODUCER_BY_PREFIX: list[tuple[str, tuple[str, str]]] = [
    # --- ISRO / IRS family (caption: ISRO-IRS) ---
    ("CartoSat", ("ISRO", "https://www.isro.gov.in/")),
    ("ResourceSat", ("ISRO", "https://www.isro.gov.in/")),
    ("OceanSat", ("ISRO", "https://www.isro.gov.in/")),
    ("RISAT", ("ISRO", "https://www.isro.gov.in/")),
    ("EOS", ("ISRO", "https://www.isro.gov.in/")),
    ("IRS", ("ISRO", "https://www.isro.gov.in/")),
    ("NISAR", ("NASA/ISRO", "https://www.isro.gov.in/")),
    # --- non-IRS (each under its own provider's terms) ---
    (
        "Sentinel",
        ("Copernicus/ESA", "https://eu-space.europa.eu/earth-observation/copernicus"),
    ),
    ("LandSat", ("USGS", "https://www.usgs.gov/landsat-missions")),
    ("Terra", ("NASA", "https://www.nasa.gov/")),
    ("Aqua", ("NASA", "https://www.nasa.gov/")),
    ("Suomi-NPP", ("NASA/NOAA", "https://www.nasa.gov/")),
    ("JPSS", ("NOAA", "https://www.noaa.gov/")),
    ("NOAA", ("NOAA", "https://www.noaa.gov/")),
    ("MetOp", ("EUMETSAT", "https://www.eumetsat.int/")),
    ("KompSat", ("KARI", "https://www.kari.re.kr/eng/")),
    ("Novasar", ("SSTL", "https://www.sstl.co.uk/")),
]


def _producer_provider(satellite: str) -> dict[str, Any]:
    """The original-operator STAC provider for a satellite, credited as producer.

    Matches the longest satellite-name prefix in ``_PRODUCER_BY_PREFIX``.
    Falls back to a bare ISRO producer (the portal's default source) when a
    satellite is unrecognised, so a collection is never left without credit.
    """
    sat = satellite or ""
    for prefix, (name, url) in _PRODUCER_BY_PREFIX:
        if sat.lower().startswith(prefix.lower()):
            provider = {"name": name, "roles": ["producer"], "url": url}
            if name == "ISRO":
                provider["description"] = f"Credit: {IRS_CAPTION}"
            return provider
    return {
        "name": "ISRO",
        "roles": ["producer"],
        "url": "https://www.isro.gov.in/",
        "description": f"Credit: {IRS_CAPTION}",
    }


def stac_licensing(satellite: str, canonical_access: str | None) -> dict[str, Any]:
    """Licensing + attribution fragment for a STAC collection.

    Returns the ``license`` string, a ``rel="license"`` link to the Bhoonidhi
    EULA, and a ``providers`` array crediting the original operator (producer)
    and NRSC/ISRO Bhoonidhi (host + licensor). Priced collections are
    ``proprietary`` (they carry NSIL's pricing terms); everything else is
    ``other`` — the accurate non-blanket value, never a bare ``"open"``.

    Parameters
    ----------
    satellite
        The collection's satellite name (used to pick the producer).
    canonical_access
        The normalised access label (``Open`` / ``OnOrder`` / ``Priced``).

    Returns
    -------
    dict
        ``{"license": str, "license_link": dict, "providers": list[dict]}`` —
        the caller merges these into the STAC collection.
    """
    return {
        "license": "proprietary" if canonical_access == "Priced" else "other",
        "license_link": {
            "rel": "license",
            "href": BHOONIDHI_EULA_URL,
            "title": "Bhoonidhi End User License Agreement",
        },
        "providers": [_producer_provider(satellite), _BHOONIDHI_PROVIDER],
    }


# Normalise portal access labels to the canonical gate labels.
_ACCESS_MAP = {"DirectDownload": "Open", "OnOrder": "OnOrder", "Priced": "Priced"}

# How each access level reads in a collection's description.
_ACCESS_SENTENCE = {
    "Open": "Open data, downloaded directly from Bhoonidhi with a free account.",
    "OnOrder": "Open data, ordered free of charge on Bhoonidhi before download.",
    "Priced": "Priced data, sold through Bhoonidhi.",
}


def _span(product_windows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """First and last acquisition dates across a collection's products.

    The end is ``None`` while any product is still being acquired, and both
    are ``None`` when the portal gives no start date at all.
    """
    starts = [
        w["operational_start"] for w in product_windows if w.get("operational_start")
    ]
    if not starts:
        return None, None
    ends = [w.get("operational_end") for w in product_windows]
    if any(end is None for end in ends):
        return min(starts), None
    return min(starts), max(end for end in ends if end)


def _describe(
    satellite: str,
    sensor: str,
    product_windows: list[dict[str, Any]],
    producer: str,
    canonical_access: str | None,
) -> str:
    """The collection's description, built from its manifest entry.

    Says what the collection holds, when the portal's product list says it
    was acquired, who operates the satellite, and how its data is obtained,
    so the text follows the manifest whenever the collections are registered
    again.
    """
    start, end = _span(product_windows)
    first = f"{sensor} scenes from {satellite} in the Bhoonidhi archive of NRSC/ISRO"
    if start and end is None:
        first += f", acquired since {start}"
    elif start:
        first += f", acquired from {start} to {end}"
    sentences = [f"{first}.", f"{satellite} is operated by {producer}."]
    if canonical_access in _ACCESS_SENTENCE:
        sentences.append(_ACCESS_SENTENCE[canonical_access])
    return " ".join(sentences)


def build_stac_collection(
    collection_config: dict[str, Any],
    aoi: dict[str, float],
) -> dict[str, Any]:
    """Build the STAC Collection dict for pgSTAC registration.

    Pure transform: every caller that registers collections gets the same
    licence and credit. Reuses ``stac_licensing`` for the licence string, the
    ``rel="license"`` link, and the per-source providers.

    Parameters
    ----------
    collection_config
        One entry from the collections manifest (``collection_id``,
        ``satellite``, ``sensor``, ``access_level``, and ``product_windows``:
        each product's ``token``, ``operational_start``, ``operational_end``
        and ``resolution_m``).
    aoi
        Bounding box dict with ``min_lon``/``min_lat``/``max_lon``/``max_lat``.

    Returns
    -------
    dict
        A STAC Collection ready for ``DatabaseManager.register_collection``.
        The temporal extent spans the products' operational windows, open
        while any product is still acquired. ``summaries`` lists each value
        the portal gives; a summary with no value is left out, since STAC
        does not allow an empty one.
    """
    collection_id = collection_config["collection_id"]
    sensor = collection_config.get("sensor", "")
    satellite = collection_config.get("satellite", "")
    access_level = collection_config.get("access_level", "")
    product_windows = collection_config.get("product_windows") or []
    canonical_access = _ACCESS_MAP.get(access_level, access_level)
    op_start, op_end = _span(product_windows)

    licensing = stac_licensing(satellite, canonical_access)

    summaries: dict[str, list[Any]] = {
        "platform": [satellite.lower().replace(" ", "-")],
        "instruments": [sensor],
        "gsd": sorted(
            {w["resolution_m"] for w in product_windows if w.get("resolution_m")}
        ),
        "bhoonidhi:access": [canonical_access],
        "bhoonidhi:products": [w["token"] for w in product_windows if w.get("token")],
    }

    return {
        "type": "Collection",
        "id": collection_id,
        "stac_version": "1.0.0",
        "description": _describe(
            satellite,
            sensor,
            product_windows,
            next(p["name"] for p in licensing["providers"] if "producer" in p["roles"]),
            canonical_access,
        ),
        "license": licensing["license"],
        "providers": licensing["providers"],
        "extent": {
            "spatial": {
                "bbox": [
                    [
                        aoi["min_lon"],
                        aoi["min_lat"],
                        aoi["max_lon"],
                        aoi["max_lat"],
                    ]
                ]
            },
            "temporal": {
                "interval": [
                    [
                        f"{op_start}T00:00:00Z" if op_start else None,
                        f"{op_end}T00:00:00Z" if op_end else None,
                    ]
                ]
            },
        },
        "links": [licensing["license_link"]],
        "summaries": {key: values for key, values in summaries.items() if values},
    }


# ---------------------------------------------------------------------------
# 1. fetch_archive — the only function that touches the network
# ---------------------------------------------------------------------------


def fetch_archive(
    satellite_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch the Bhoonidhi archive via the SDK and return parsed records.

    Each record represents one satellite with its sensors, availability
    window, access level, and per-sensor collection metadata.

    Parameters
    ----------
    satellite_filter
        If given, return only the record whose ``satName`` matches.

    Returns
    -------
    list[dict]
        Parsed satellite records ready for ``generate_collection_config``.
    """
    from bhoonidhi_downloader.sdk import BhoonidhiClient

    client = BhoonidhiClient()
    raw_records = client.archive.list()
    return _parse_archive(raw_records, satellite_filter=satellite_filter)


# ---------------------------------------------------------------------------
# 2. generate_collection_config — pure transformation, no I/O
# ---------------------------------------------------------------------------


def generate_collection_config(
    sat_record: dict[str, Any],
) -> list[dict[str, Any]]:
    """Turn one parsed satellite record into a list of collection configs.

    Collections are keyed at the **satellite + sensor** level (not per
    product). Every product that Bhoonidhi exposes under a sensor is
    collapsed into that sensor's ``products`` list, so a sensor with two
    products (e.g. Sentinel-1A SAR ``Level-1_GRD`` + ``Level-1_SLC``)
    yields ONE collection carrying both, rather than one collection per
    product. Product then lives at the STAC Item level; the collection's
    ``products`` feeds ``summaries.bhoonidhi:products``.

    Operational window per sensor: the collection spans the widest window
    of its products. A sensor counts as **active** (``operational_end =
    None``) if *any* of its products is still active — a sensor is only
    retired once all of its products have an end date.

    Parameters
    ----------
    sat_record
        A single dict from ``fetch_archive()``.

    Returns
    -------
    list[dict]
        One config per (satellite, sensor), each carrying
        ``collection_id``, ``satellite``, ``sensor``, ``resolution_m``,
        ``access_level``, ``operational_start``, ``operational_end``, and
        ``products`` (the list of product tokens under that sensor).
    """
    from bhoonidhi_downloader.schemas.selection import product_token

    satellite = sat_record.get("satellite")

    # Aggregate every dispName under its (sensor) key. dispNames in the
    # parsed record already share a sensor via ``meta["sensor"]``; group
    # on the raw sensor name so distinct capture modes (e.g. SAR(IW) vs
    # SAR(CRS)) stay separate collections.
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for collection_group in sat_record.get("collections", []):
        for display_name, meta in collection_group.items():
            sensor = meta.get("sensor") or ""
            op_start = _parse_mdy(meta.get("start_date"))
            op_end = _parse_mdy(meta.get("end_date"))

            # Canonical product token — the dispName suffix after
            # ``satellite_sensor_``. Empty string means the sensor's
            # default product (no distinct suffix); skip empties so the
            # products list only carries real product names.
            token = product_token(display_name, satellite or "", sensor)

            if sensor not in groups:
                order.append(sensor)
                groups[sensor] = {
                    "sensor": sensor,
                    "resolution_m": meta.get("resolution"),
                    "products": [],
                    "product_windows": {},  # token -> {start, end, resolution}
                    "_starts": [],
                    "_ends": [],
                    "_any_active": False,
                }
            g = groups[sensor]
            if token and token not in g["products"]:
                g["products"].append(token)
            # Per-product operational window: each product keeps
            # its own start/end so ingest can run only products still active.
            # A sensor's default (empty token) is keyed as "" so it is never
            # lost. Widen if the same token appears more than once.
            pw = g["product_windows"].setdefault(
                token,
                {
                    "start": op_start,
                    "end": op_end,
                    "any_active": op_end is None,
                    "resolution": _metres(meta.get("resolution")),
                },
            )
            if op_start is not None and (pw["start"] is None or op_start < pw["start"]):
                pw["start"] = op_start
            if op_end is None:
                pw["any_active"] = True
            elif pw["end"] is None or op_end > pw["end"]:
                pw["end"] = op_end
            if op_start is not None:
                g["_starts"].append(op_start)
            # A product with no end date is still active → the whole
            # sensor stays active regardless of retired siblings.
            if op_end is None:
                g["_any_active"] = True
            else:
                g["_ends"].append(op_end)

    results: list[dict[str, Any]] = []
    for sensor in order:
        g = groups[sensor]

        # Widest operational window across the sensor's products.
        op_start = min(g["_starts"]) if g["_starts"] else None
        # Active if any product is active; else the latest retirement.
        op_end = None if g["_any_active"] else (max(g["_ends"]) if g["_ends"] else None)

        # Structured per-product windows for the ingest. An active
        # product has operational_end = None. resolution_m is the portal's
        # resolution for that product, in metres.
        product_windows = [
            {
                "token": token,
                "operational_start": pw["start"].isoformat() if pw["start"] else None,
                "operational_end": None
                if pw["any_active"]
                else (pw["end"].isoformat() if pw["end"] else None),
                "resolution_m": pw["resolution"],
            }
            for token, pw in g["product_windows"].items()
        ]

        results.append(
            {
                "collection_id": _slugify(f"{satellite}-{sensor}"),
                "satellite": satellite,
                "sensor": sensor,
                "resolution_m": g["resolution_m"],
                "access_level": sat_record.get("access_level"),
                "operational_start": op_start.isoformat() if op_start else None,
                "operational_end": op_end.isoformat() if op_end else None,
                # Flat token list — unchanged, feeds summaries.bhoonidhi:products.
                "products": g["products"],
                # Structured windows — per-product active/retired state.
                "product_windows": product_windows,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_mdy(s: str | None) -> date | None:
    """Parse an M/D/YYYY date string into a ``date``, or ``None``."""
    if not s:
        return None
    try:
        month, day, year = (int(p) for p in s.split("/"))
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


def _metres(value: Any) -> float | None:
    """The portal's resolution string as metres, or ``None`` if it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumeric runs with hyphens, strip edges."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _normalize_products(products: Any) -> str | None:
    """Collapse a product field to a single display string."""
    if products is None:
        return None
    if isinstance(products, list):
        cleaned = [str(p).strip() for p in products if str(p).strip()]
        return cleaned[0] if cleaned else None
    return str(products)


def _parse_archive(
    raw_records: list[dict[str, Any]],
    satellite_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Transform raw SDK archive records into the shape the collection configs use.

    The output shape matches what ``generate_collection_config`` consumes:

    .. code-block:: python

        {
            "index": 1,
            "satellite": "Aqua",
            "availability": "31 December 2003 - 31 December 2019",
            "availability_start": "12/31/2003",
            "availability_end": "12/31/2019",  # or None
            "access_level": "OnOrder",
            "collections": [
                {"Aqua_MODIS": {"sensor": "MODIS", "resolution": "500",
                                "start_date": "12/31/2003",
                                "end_date": "12/31/2019",
                                "product": "Others"}}
            ],
            "resolution": "500",
            "min_resolution": "500",
            "max_resolution": "500",
        }

    Parameters
    ----------
    raw_records
        Direct output of ``client.archive.list()`` — raw portal dicts
        with keys like ``satName``, ``priced``, ``sensors``, etc.
    satellite_filter
        If given, keep only records whose ``satName`` matches exactly.
    """
    from datetime import datetime as _dt

    results: list[dict[str, Any]] = []

    for idx, record in enumerate(raw_records, start=1):
        sat_name = record.get("satName")

        if satellite_filter and sat_name != satellite_filter:
            continue

        min_res = record.get("thisMinRes")
        max_res = record.get("thisMaxRes")
        resolution = f"{min_res} - {max_res}" if min_res != max_res else min_res

        start_raw = record.get("totalStartDate")
        start_display = (
            _dt.strptime(start_raw, "%m/%d/%Y").strftime("%d %B %Y")  # noqa: DTZ007
            if start_raw
            else "N/A"
        )
        end_raw = record.get("totalEndDate", "")
        end_display = (
            _dt.strptime(end_raw, "%m/%d/%Y").strftime("%d %B %Y")  # noqa: DTZ007
            if end_raw
            else "till date"
        )

        collections: list[dict[str, dict[str, Any]]] = [
            {
                str(sensor.get("dispName", "")): {
                    "sensor": sensor.get("senName"),
                    "resolution": sensor.get("res"),
                    "start_date": sensor.get("stDate"),
                    "end_date": sensor.get("endDate"),
                    "product": _normalize_products(sensor.get("products")),
                }
            }
            for sensor in record.get("sensors", [])
            if sensor.get("dispName")
        ]

        access_level = (record.get("priced") or "N/A").split("_")[-1]

        results.append(
            {
                "index": idx,
                "satellite": sat_name,
                "availability": f"{start_display} - {end_display}",
                "availability_start": start_raw,
                "availability_end": end_raw if end_raw else None,
                "access_level": access_level,
                "collections": collections,
                "resolution": resolution,
                "min_resolution": min_res,
                "max_resolution": max_res,
            }
        )

    return results
