"""Tests for the scene counts behind /aggregate (api/aggregation.py).

The unit tests check the grouping sets, the response shape and the request
checks. The integration test loads a few scenes into a real pgSTAC when
BHX_TEST_PGSTAC_DSN names one (a throwaway database: the test writes to it),
and checks the counts against what pgstac.search returns for the same search;
it is skipped otherwise.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime

import asyncpg
import pytest
from fastapi import HTTPException

from bhoonidhi_stac.api.aggregation import (
    NAMES,
    AggregatePost,
    count_scenes,
    grouped_query,
    groupings,
    level,
    plan,
    to_aggregations,
)


def day(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def row(
    collection=None, platform=None, period=None, scenes=0, oldest=None, newest=None
):
    grouped = [
        c
        for c, v in (
            ("collection", collection),
            ("platform", platform),
            ("period", period),
        )
        if v
    ]
    return {
        "level": level(grouped),
        "collection": collection,
        "platform": platform,
        "period": period,
        "scenes": scenes,
        "oldest": oldest,
        "newest": newest,
    }


def by_name(aggregations):
    return {a["name"]: a for a in aggregations}


def test_grouping_levels_match_postgres_grouping_bits():
    # grouping(collection, platform, period): 4, 2 and 1 for each column left out.
    assert level(()) == 7
    assert level(["period"]) == 6
    assert level(["platform"]) == 5
    assert level(["platform", "period"]) == 4
    assert level(["collection"]) == 3


def test_a_total_needs_one_grouping_and_no_platform():
    sets = groupings(["total_count", "datetime_min", "datetime_max"])
    assert sets == [()]
    sql = grouped_query("TRUE", sets)
    assert "NULL::text AS platform" in sql
    assert "GROUPING SETS (())" in sql
    # Columns no grouping uses are neither selected nor passed to grouping().
    assert "NULL AS collection, NULL AS platform, NULL AS period" in sql
    assert "grouping(" not in sql


def test_platform_per_period_also_counts_each_platform():
    sets = groupings(["platform_datetime_frequency"])
    assert sets == [(), ("platform",), ("platform", "period")]
    assert "content->'properties'->>'platform' AS platform" in grouped_query(
        "TRUE", sets
    )


def test_every_aggregation_has_a_grouping():
    assert len(groupings(NAMES)) == 5


def test_response_shape_and_order():
    rows = [
        row(
            scenes=6,
            oldest=day("2025-01-01T05:00:00"),
            newest=day("2025-02-10T06:30:00"),
        ),
        row(period=day("2025-02-01"), scenes=1),
        row(period=day("2025-01-01"), scenes=5),
        row(collection="b", scenes=2),
        row(collection="a", scenes=4),
        row(collection="c", scenes=2),
        row(platform="p2", scenes=1),
        row(platform="p1", scenes=5),
        row(platform="p1", period=day("2025-02-01"), scenes=1),
        row(platform="p1", period=day("2025-01-01"), scenes=4),
        row(platform="p2", period=day("2025-01-01"), scenes=1),
    ]
    out = to_aggregations(rows, NAMES)
    assert [a["name"] for a in out] == NAMES
    got = by_name(out)
    assert got["total_count"] == {
        "name": "total_count",
        "data_type": "integer",
        "value": 6,
    }
    assert got["datetime_min"]["value"] == "2025-01-01T05:00:00Z"
    assert got["datetime_max"]["value"] == "2025-02-10T06:30:00Z"
    # Periods run oldest first; collections and platforms most scenes first.
    assert [
        (b["key"], b["frequency"]) for b in got["datetime_frequency"]["buckets"]
    ] == [
        ("2025-01-01T00:00:00Z", 5),
        ("2025-02-01T00:00:00Z", 1),
    ]
    assert [b["key"] for b in got["collection_frequency"]["buckets"]] == ["a", "b", "c"]
    assert [b["key"] for b in got["platform_frequency"]["buckets"]] == ["p1", "p2"]
    nested = got["platform_datetime_frequency"]["buckets"]
    assert [(b["key"], b["frequency"]) for b in nested] == [("p1", 5), ("p2", 1)]
    assert [(b["key"], b["frequency"]) for b in nested[0]["buckets"]] == [
        ("2025-01-01T00:00:00Z", 4),
        ("2025-02-01T00:00:00Z", 1),
    ]
    assert all(b["data_type"] == "frequency_distribution" for b in nested[0]["buckets"])


def test_an_empty_result_counts_zero_and_has_no_dates():
    out = by_name(to_aggregations([row()], NAMES))
    assert out["total_count"]["value"] == 0
    assert out["datetime_min"]["value"] is None
    assert out["datetime_max"]["value"] is None
    assert out["datetime_frequency"]["buckets"] == []
    assert out["platform_datetime_frequency"]["buckets"] == []


def test_plan_keeps_only_the_fields_that_select_scenes():
    request = AggregatePost.model_validate(
        {
            "collections": ["a"],
            "bbox": [78.0, 26.0, 78.5, 26.5],
            "datetime": "2025-01-01T00:00:00Z/2025-12-31T23:59:59Z",
            "filter-lang": "cql2-json",
            "filter": {"op": "<=", "args": [{"property": "gsd"}, 6]},
            "limit": 5,
            "aggregations": ["total_count", "total_count", "datetime_frequency"],
            "datetime_frequency_interval": "day",
        }
    )
    wanted, interval, search = plan(request)
    assert wanted == ["total_count", "datetime_frequency"]
    assert interval == "day"
    assert search == {
        "collections": ["a"],
        "bbox": [78.0, 26.0, 78.5, 26.5],
        "datetime": "2025-01-01T00:00:00Z/2025-12-31T23:59:59Z",
        "filter": {"op": "<=", "args": [{"property": "gsd"}, 6]},
        "filter-lang": "cql2-json",
    }


def test_the_interval_defaults_to_month():
    assert plan(AggregatePost(aggregations=["datetime_frequency"]))[1] == "month"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"aggregations": []},
        {"aggregations": ["cloud_cover_frequency"]},
        {"aggregations": ["datetime_frequency"], "datetime_frequency_interval": "hour"},
    ],
)
def test_requests_that_name_no_known_count_are_refused(body):
    with pytest.raises(HTTPException) as refused:
        plan(AggregatePost.model_validate(body))
    assert refused.value.status_code == 400


DSN = os.environ.get("BHX_TEST_PGSTAC_DSN", "")

# Two collections of one satellite share the scene "twice", as some
# ResourceSat-1 and NovaSAR-1 scenes do; "far" lies outside the search box.
NEAR = [10.0, 10.0, 10.1, 10.1]
SCENES = [
    ("test-counts-a", "one", "p1", "2025-01-01T04:00:00Z", NEAR),
    ("test-counts-a", "two", "p1", "2025-01-01T09:00:00Z", NEAR),
    ("test-counts-a", "three", "p1", "2025-01-02T04:00:00Z", NEAR),
    ("test-counts-a", "twice", "p1", "2025-01-03T04:00:00Z", NEAR),
    ("test-counts-b", "twice", "p1", "2025-01-03T04:00:00Z", NEAR),
    ("test-counts-b", "four", "p1", "2025-02-10T04:00:00Z", NEAR),
    ("test-counts-c", "five", "p2", "2025-01-02T23:30:00Z", NEAR),
    ("test-counts-c", "far", "p2", "2025-01-02T04:00:00Z", [50.0, 50.0, 50.1, 50.1]),
]
COLLECTIONS = sorted({s[0] for s in SCENES})


def _item(collection, scene_id, platform, when, box):
    w, s, e, n = box
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": scene_id,
        "collection": collection,
        "bbox": box,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
        "properties": {"datetime": when, "platform": platform},
        "assets": {},
        "links": [],
    }


def _collection(collection_id):
    return {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": collection_id,
        "description": "Scenes for the scene count tests.",
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[None, None]]},
        },
        "links": [],
    }


async def _run_counts():
    conn = await asyncpg.connect(DSN, server_settings={"search_path": "pgstac,public"})
    try:
        for collection_id in COLLECTIONS:
            await conn.execute(
                "SELECT pgstac.upsert_collection($1::text::jsonb)",
                json.dumps(_collection(collection_id)),
            )
        await conn.execute(
            "SELECT pgstac.upsert_items($1::text::jsonb)",
            json.dumps([_item(*s) for s in SCENES]),
        )

        search = {"collections": COLLECTIONS, "bbox": [9.0, 9.0, 11.0, 11.0]}
        day_counts = by_name(await count_scenes(conn, search, NAMES, "day"))
        month_counts = by_name(
            await count_scenes(conn, search, ["datetime_frequency"], "month")
        )
        narrowed = {
            **search,
            "filter-lang": "cql2-json",
            "filter": {
                "op": "t_intersects",
                "args": [
                    {"property": "datetime"},
                    {"interval": ["2025-01-02T00:00:00Z", "2025-01-31T23:59:59Z"]},
                ],
            },
        }
        narrowed_counts = by_name(
            await count_scenes(conn, narrowed, ["total_count"], "day")
        )
        found = []
        for body in (search, narrowed):
            page = await conn.fetchval(
                "SELECT pgstac.search($1::text::jsonb)::text",
                json.dumps({**body, "limit": 100, "fields": {"include": ["id"]}}),
            )
            found.append({f["id"] for f in json.loads(page)["features"]})
        return day_counts, month_counts, narrowed_counts, found
    finally:
        for collection_id in COLLECTIONS:
            await conn.execute("SELECT pgstac.delete_collection($1)", collection_id)
        await conn.close()


def _pairs(aggregation):
    return [(b["key"], b["frequency"]) for b in aggregation["buckets"]]


@pytest.mark.skipif(not DSN, reason="BHX_TEST_PGSTAC_DSN names no test pgSTAC")
def test_counts_match_the_search_and_count_a_shared_scene_once():
    day_counts, month_counts, narrowed_counts, found = asyncio.run(_run_counts())

    # The same scenes pgSTAC's search returns, the shared one counted once.
    assert found[0] == {"one", "two", "three", "twice", "four", "five"}
    assert day_counts["total_count"]["value"] == len(found[0]) == 6
    assert narrowed_counts["total_count"]["value"] == len(found[1]) == 3

    assert day_counts["datetime_min"]["value"] == "2025-01-01T04:00:00Z"
    assert day_counts["datetime_max"]["value"] == "2025-02-10T04:00:00Z"
    # Periods are UTC days: the 23:30 scene stays on 2 January.
    assert _pairs(day_counts["datetime_frequency"]) == [
        ("2025-01-01T00:00:00Z", 2),
        ("2025-01-02T00:00:00Z", 2),
        ("2025-01-03T00:00:00Z", 1),
        ("2025-02-10T00:00:00Z", 1),
    ]
    assert _pairs(month_counts["datetime_frequency"]) == [
        ("2025-01-01T00:00:00Z", 5),
        ("2025-02-01T00:00:00Z", 1),
    ]
    # Each collection counts the scenes filed under it, the shared one in both.
    assert _pairs(day_counts["collection_frequency"]) == [
        ("test-counts-a", 4),
        ("test-counts-b", 2),
        ("test-counts-c", 1),
    ]
    assert _pairs(day_counts["platform_frequency"]) == [("p1", 5), ("p2", 1)]
    p1, p2 = day_counts["platform_datetime_frequency"]["buckets"]
    assert (p1["key"], p1["frequency"], p2["key"], p2["frequency"]) == (
        "p1",
        5,
        "p2",
        1,
    )
    assert _pairs(p1) == [
        ("2025-01-01T00:00:00Z", 2),
        ("2025-01-02T00:00:00Z", 1),
        ("2025-01-03T00:00:00Z", 1),
        ("2025-02-10T00:00:00Z", 1),
    ]
    assert _pairs(p2) == [("2025-01-02T00:00:00Z", 1)]
