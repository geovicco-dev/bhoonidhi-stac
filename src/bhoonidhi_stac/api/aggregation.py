"""Scene counts for the STAC API: the Aggregation extension's /aggregate.

A search answers with scenes, at most 10,000 a page, so counting a large result
by paging through it takes minutes. /aggregate takes the same search and
answers with counts the database works out in one query: the total, the oldest
and newest dates, and the number of scenes per period, per collection, per
satellite, and per satellite and period.

The counts use pgSTAC's own filter: pgstac.stac_search_to_where turns the
search into the WHERE clause pgstac.search runs, so a count always describes
the scenes the same search returns. Some scenes are filed under two
collections (ResourceSat-1 LISS-4 MX23 and MONO, NovaSAR-1). Such a scene
counts once in every count, except that each of its collections counts it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import attr
from asyncpg import Connection
from asyncpg.exceptions import InvalidDatetimeFormatError, QueryCanceledError
from fastapi import HTTPException, Request
from pydantic import ValidationError
from stac_fastapi.extensions.aggregation.client import AsyncBaseAggregationClient
from stac_fastapi.extensions.aggregation.request import (
    AggregationExtensionGetRequest,
    AggregationExtensionPostRequest,
)
from stac_fastapi.extensions.aggregation.types import (
    Aggregation,
    AggregationCollection,
)
from stac_fastapi.extensions.filter.request import (
    FilterExtensionGetRequest,
    FilterExtensionPostRequest,
)
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.types.search import PgstacSearch
from stac_fastapi.types.requests import get_base_url

FREQUENCY = "frequency_distribution"

# What /aggregations lists, in the shape stac-fastapi-elasticsearch-opensearch
# uses, so a client written for either server reads both.
AVAILABLE: list[dict[str, str]] = [
    {"name": "total_count", "data_type": "integer"},
    {"name": "datetime_min", "data_type": "datetime"},
    {"name": "datetime_max", "data_type": "datetime"},
    {
        "name": "datetime_frequency",
        "data_type": FREQUENCY,
        "frequency_distribution_data_type": "datetime",
    },
    {
        "name": "collection_frequency",
        "data_type": FREQUENCY,
        "frequency_distribution_data_type": "string",
    },
    {
        "name": "platform_frequency",
        "data_type": FREQUENCY,
        "frequency_distribution_data_type": "string",
    },
    # Per satellite, each bucket holding that satellite's scenes per period: a
    # client can count any stretch of dates for any satellites without asking
    # again.
    {
        "name": "platform_datetime_frequency",
        "data_type": FREQUENCY,
        "frequency_distribution_data_type": "string",
    },
]
NAMES = [a["name"] for a in AVAILABLE]

INTERVALS = ("year", "month", "week", "day")
DEFAULT_INTERVAL = "month"

# The columns the counts are grouped by, and the grouping each aggregation
# reads. A platform's per-period bucket needs the platform's own total as well.
COLUMNS = ("collection", "platform", "period")
GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "total_count": ((),),
    "datetime_min": ((),),
    "datetime_max": ((),),
    "datetime_frequency": (("period",),),
    "collection_frequency": (("collection",),),
    "platform_frequency": (("platform",),),
    "platform_datetime_frequency": (("platform",), ("platform", "period")),
}

# The search fields that select scenes; paging, sorting and the aggregation
# fields themselves do not change which scenes match.
SEARCH_FIELDS = {
    "collections",
    "ids",
    "bbox",
    "intersects",
    "datetime",
    "filter_expr",
    "filter_lang",
    "filter_crs",
}

TOO_BROAD = (
    "Counting the scenes of this search took longer than the server allows. "
    "Narrow the area, the dates or the collections and try again."
)


class AggregatePost(
    PgstacSearch, AggregationExtensionPostRequest, FilterExtensionPostRequest
):
    """The body of POST /aggregate: a search, the aggregations and the period."""

    datetime_frequency_interval: str | None = None


@attr.s
class AggregateGet(AggregationExtensionGetRequest, FilterExtensionGetRequest):
    """The query parameters of GET /aggregate."""

    datetime_frequency_interval: str | None = attr.ib(default=None)


def level(columns: Iterable[str]) -> int:
    """A number naming the grouping of these columns, as each result row carries it.

    It is what grouping(collection, platform, period) gives: a bit for every
    column the row is not grouped by, 4 for collection, 2 for platform, 1 for
    period.
    """
    grouped = set(columns)
    return sum(_bit(c) for c in COLUMNS if c not in grouped)


def _bit(column: str) -> int:
    return 1 << (len(COLUMNS) - 1 - COLUMNS.index(column))


def groupings(wanted: Iterable[str]) -> list[tuple[str, ...]]:
    """The grouping sets the wanted aggregations read, each once, the total first."""
    sets = {g for name in wanted for g in GROUPS[name]}
    sets.add(())
    return sorted(sets, key=lambda g: (len(g), [COLUMNS.index(c) for c in g]))


def grouped_query(where: str, sets: Sequence[tuple[str, ...]]) -> str:
    """One query counting the matching scenes for every grouping set.

    The period is the scene's date cut to the interval in UTC; $1 is the
    interval. A scene's platform is read from its stored record, which is the
    slow part on a large result, so it is read only when a grouping needs it.
    """
    needs_platform = any("platform" in g for g in sets)
    platform = "content->'properties'->>'platform'" if needs_platform else "NULL::text"
    grouping_sets = ", ".join("(" + ", ".join(g) + ")" for g in sets)
    # Postgres's grouping() takes only columns some grouping set uses, and a
    # column no set uses cannot be selected; such a column is rolled up in
    # every row, so it reads as NULL and its bit is a constant.
    used = {c for g in sets for c in g}
    row_level = " + ".join(
        f"grouping({c}) * {_bit(c)}" if c in used else str(_bit(c)) for c in COLUMNS
    )
    keys = ", ".join(c if c in used else f"NULL AS {c}" for c in COLUMNS)
    return f"""
        SELECT {row_level} AS level,
               {keys},
               count(DISTINCT id) AS scenes,
               min(datetime) AS oldest,
               max(datetime) AS newest
        FROM (
            SELECT id, collection, datetime,
                   {platform} AS platform,
                   date_trunc($1, datetime, 'UTC') AS period
            FROM pgstac.items
            WHERE {where}
        ) AS matched
        GROUP BY GROUPING SETS ({grouping_sets})
    """


def rfc3339(value: datetime) -> str:
    """A timestamp as RFC 3339 in UTC, e.g. 2025-01-31T05:12:33Z."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bucket(key: str, frequency: int) -> dict[str, Any]:
    return {"key": key, "data_type": FREQUENCY, "frequency": frequency}


def _by_frequency(rows: Iterable[Any], column: str) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: (-r["scenes"], r[column] or ""))
    return [_bucket(r[column], r["scenes"]) for r in ordered]


def _by_period(rows: Iterable[Any]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: r["period"])
    return [_bucket(rfc3339(r["period"]), r["scenes"]) for r in ordered]


def to_aggregations(rows: Sequence[Any], wanted: Sequence[str]) -> list[Aggregation]:
    """The wanted aggregations, in the order asked, from the grouped query's rows."""
    at: dict[int, list[Any]] = {}
    for row in rows:
        at.setdefault(row["level"], []).append(row)
    total = at[level(())][0]

    out: list[Aggregation] = []
    for name in wanted:
        if name == "total_count":
            out.append(
                Aggregation(name=name, data_type="integer", value=total["scenes"])
            )
        elif name in ("datetime_min", "datetime_max"):
            # An empty result has no dates.
            when = total["oldest" if name == "datetime_min" else "newest"]
            value = rfc3339(when) if when else None
            out.append(Aggregation(name=name, data_type="datetime", value=value))
        elif name == "datetime_frequency":
            buckets = _by_period(at.get(level(["period"]), []))
            out.append(Aggregation(name=name, data_type=FREQUENCY, buckets=buckets))
        elif name == "collection_frequency":
            buckets = _by_frequency(at.get(level(["collection"]), []), "collection")
            out.append(Aggregation(name=name, data_type=FREQUENCY, buckets=buckets))
        elif name == "platform_frequency":
            buckets = _by_frequency(at.get(level(["platform"]), []), "platform")
            out.append(Aggregation(name=name, data_type=FREQUENCY, buckets=buckets))
        elif name == "platform_datetime_frequency":
            periods: dict[str, list[Any]] = {}
            for row in at.get(level(["platform", "period"]), []):
                periods.setdefault(row["platform"], []).append(row)
            buckets = _by_frequency(at.get(level(["platform"]), []), "platform")
            for bucket in buckets:
                bucket["buckets"] = _by_period(periods.get(bucket["key"], []))
            out.append(Aggregation(name=name, data_type=FREQUENCY, buckets=buckets))
    return out


def plan(aggregate: AggregatePost) -> tuple[list[str], str, dict[str, Any]]:
    """Check a request and return its aggregations, its interval and its search.

    Raises:
        HTTPException: 400 when no aggregation is named, a name is unknown or
            the interval is not one of INTERVALS.
    """
    wanted = list(dict.fromkeys(aggregate.aggregations or []))
    if not wanted:
        raise HTTPException(
            status_code=400,
            detail="Name the counts in 'aggregations'; /aggregations lists them.",
        )
    unknown = [name for name in wanted if name not in NAMES]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown aggregations {unknown}; available: {NAMES}.",
        )
    interval = aggregate.datetime_frequency_interval or DEFAULT_INTERVAL
    if interval not in INTERVALS:
        raise HTTPException(
            status_code=400,
            detail=f"datetime_frequency_interval must be one of {list(INTERVALS)}.",
        )
    search = aggregate.model_dump(
        mode="json", by_alias=True, exclude_none=True, include=SEARCH_FIELDS
    )
    return wanted, interval, search


async def count_scenes(
    conn: Connection, search: dict[str, Any], wanted: Sequence[str], interval: str
) -> list[Aggregation]:
    """Run the counts for a pgSTAC search body on one connection."""
    where = await conn.fetchval(
        "SELECT pgstac.stac_search_to_where($1::text::jsonb)", json.dumps(search)
    )
    rows = await conn.fetch(grouped_query(where, groupings(wanted)), interval)
    return to_aggregations(rows, wanted)


def _links(request: Request, collection_id: str | None, endpoint: str) -> list[dict]:
    base_url = get_base_url(request)
    links = [{"rel": "root", "type": "application/json", "href": base_url}]
    if collection_id:
        collection = urljoin(base_url, f"collections/{collection_id}")
        links.append(
            {"rel": "collection", "type": "application/json", "href": collection}
        )
        self_href = f"{collection}/{endpoint}"
    else:
        self_href = urljoin(base_url, endpoint)
    links.append({"rel": "self", "type": "application/json", "href": self_href})
    return links


@attr.s
class SceneCountClient(AsyncBaseAggregationClient):
    """The Aggregation extension's client, counting in the pgSTAC database."""

    # Reads GET parameters the way stac-fastapi-pgstac's GET /search does.
    core: CoreCrudClient = attr.ib(factory=CoreCrudClient)

    async def get_aggregations(
        self, collection_id: str | None = None, **kwargs: Any
    ) -> AggregationCollection:
        """List the counts /aggregate can return; every collection has them all."""
        return AggregationCollection(
            type="AggregationCollection",
            aggregations=[Aggregation(**a) for a in AVAILABLE],
            links=_links(kwargs["request"], collection_id, "aggregations"),
        )

    async def aggregate(  # type: ignore[override]
        self,
        aggregate_request: AggregatePost | None = None,
        *,
        request: Request,
        collections: list[str] | None = None,
        ids: list[str] | None = None,
        bbox: Any = None,
        intersects: str | None = None,
        datetime: str | None = None,
        filter_expr: str | None = None,
        filter_lang: str | None = None,
        aggregations: list[str] | None = None,
        datetime_frequency_interval: str | None = None,
        **kwargs: Any,
    ) -> AggregationCollection:
        """Count the scenes a search matches.

        POST passes the parsed body as aggregate_request; GET passes the query
        parameters one by one.
        """
        if aggregate_request is None:
            clean = self.core._clean_search_args(
                base_args={"collections": collections, "ids": ids, "bbox": bbox},
                intersects=intersects,
                datetime=datetime,
                filter_query=filter_expr,
                filter_lang=filter_lang,
            )
            try:
                aggregate_request = AggregatePost(
                    **clean,
                    aggregations=aggregations,
                    datetime_frequency_interval=datetime_frequency_interval,
                )
            except ValidationError as e:
                raise HTTPException(
                    status_code=400, detail=f"Invalid parameters provided {e}"
                ) from e

        collection_id = request.path_params.get("collection_id")
        if collection_id:
            aggregate_request.collections = [collection_id]
        wanted, interval, search = plan(aggregate_request)

        async with request.app.state.get_connection(request, "r") as conn:
            try:
                counts = await count_scenes(conn, search, wanted, interval)
            except QueryCanceledError as e:
                # The database login's time limit (60 s on the public API).
                raise HTTPException(status_code=400, detail=TOO_BROAD) from e
            except InvalidDatetimeFormatError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Datetime parameter {aggregate_request.datetime} is invalid.",
                ) from e

        return AggregationCollection(
            type="AggregationCollection",
            aggregations=counts,
            links=_links(request, collection_id, "aggregate"),
        )
