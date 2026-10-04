"""Tests for the queryables and search indexes the setup step writes
(core/database.py).

The unit tests check the definitions against what pgSTAC's search does with
these properties. The integration test runs ensure_pgstac_schema against a
real pgSTAC when BHX_TEST_PGSTAC_DSN names one (a throwaway database: the
test writes to it), and is skipped otherwise.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import psycopg
import pytest
from bhoonidhi_downloader.core.search.availability import Availability

from bhoonidhi_stac.core.database import DatabaseManager
from bhoonidhi_stac.schemas import DatabaseSchema

BY_NAME = {q["name"]: q for q in DatabaseManager.QUERYABLES}
INDEXED = dict(DatabaseManager.SEARCH_INDEXES)


def test_the_three_filtered_properties_are_listed():
    assert set(BY_NAME) == {"gsd", "SELECTION", "bhoonidhi:availability"}


def test_no_queryable_asks_pgstac_for_an_index():
    # pgSTAC builds an index on the property alone for an entry with an index
    # type, and its maintenance drops other indexes on that property. The
    # search indexes are built by the setup step instead.
    assert all(q["property_index_type"] is None for q in DatabaseManager.QUERYABLES)


def test_only_product_and_availability_get_search_indexes():
    # All scenes of a sensor share one or two resolutions; leaving out the
    # collections that cannot match is what makes a resolution filter fast.
    assert set(INDEXED) == {"SELECTION", "bhoonidhi:availability"}


def test_wrappers_match_how_pgstac_filters_these_values():
    # pgSTAC's filters read gsd with to_float and the others with to_text;
    # an index on any other expression is never used by a search.
    assert BY_NAME["gsd"]["property_wrapper"] == "to_float"
    assert BY_NAME["gsd"]["definition"]["type"] == "number"
    for name in ("SELECTION", "bhoonidhi:availability"):
        assert BY_NAME[name]["property_wrapper"] == "to_text"
        assert BY_NAME[name]["definition"]["type"] == "string"


def test_availability_values_are_the_sdks():
    # The values the transform writes come from the SDK's classifier.
    assert BY_NAME["bhoonidhi:availability"]["definition"]["enum"] == [
        a.value for a in Availability
    ]
    described = BY_NAME["bhoonidhi:availability"]["definition"]["description"]
    assert all(a.value in described for a in Availability)


def test_every_definition_has_a_title_and_a_description():
    for q in DatabaseManager.QUERYABLES:
        assert q["definition"]["title"].strip()
        assert q["definition"]["description"].strip()


DSN = os.environ.get("BHX_TEST_PGSTAC_DSN", "")


@pytest.mark.skipif(not DSN, reason="BHX_TEST_PGSTAC_DSN names no test pgSTAC")
def test_setup_writes_queryables_and_search_indexes_once():
    url = urlparse(DSN)
    manager = DatabaseManager(
        DatabaseSchema(
            host=url.hostname or "localhost",
            port=url.port or 5432,
            user=url.username or "postgres",
            password=url.password or "",
            database=url.path.lstrip("/"),
        )
    )
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM pgstac.queryables WHERE name = ANY(%s)", (list(BY_NAME),)
        )
        # Drops every property index pgSTAC does not ask for, ours included.
        conn.execute("SELECT pgstac.maintain_partitions('items', true)")

    def state():
        with psycopg.connect(DSN) as conn:
            rows = conn.execute(
                "SELECT name, definition, property_wrapper, property_index_type "
                "FROM pgstac.queryables WHERE name = ANY(%s)",
                (list(BY_NAME),),
            ).fetchall()
            indexes = conn.execute(
                "SELECT i.indexname, i.indexdef, c.oid::int FROM pg_indexes i "
                "JOIN pg_class c ON c.relname = i.indexname "
                "WHERE i.schemaname = 'pgstac' AND i.tablename ~ '^_items_' "
                "AND i.indexdef ~ 'content'"
            ).fetchall()
            row = conn.execute("SELECT count(*) FROM pgstac.partitions_view").fetchone()
        tables: int = row[0] if row else 0
        return (
            {r[0]: r[1:] for r in rows},
            {name: (d, oid) for name, d, oid in indexes},
            tables,
        )

    manager.ensure_pgstac_schema()
    rows, indexes, tables = state()
    assert tables > 0, "the test pgSTAC holds no scene table"
    for q in DatabaseManager.QUERYABLES:
        assert rows[q["name"]] == (
            q["definition"],
            q["property_wrapper"],
            q["property_index_type"],
        )
    # Two indexes per scene table, property then newest date, nothing else.
    assert len(indexes) == 2 * tables
    for prop, tag in DatabaseManager.SEARCH_INDEXES:
        mine = {
            n: d for n, (d, _) in indexes.items() if n.endswith(f"_{tag}_datetime_idx")
        }
        assert len(mine) == tables
        assert all(f"'{prop}'" in d and "datetime DESC" in d for d in mine.values())
    assert not any("'gsd'" in d for d, _ in indexes.values())

    # A second run changes nothing: the same indexes, not rebuilt.
    manager.ensure_pgstac_schema()
    assert state() == (rows, indexes, tables)

    # pgSTAC's own maintenance, as its triggers run it after a queryables
    # change or a scene write, leaves them in place.
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("SELECT pgstac.maintain_partitions()")
    assert state() == (rows, indexes, tables)

    # A changed description is written back without touching any index.
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE pgstac.queryables SET definition = %s WHERE name = 'gsd'",
            (json.dumps({"title": "old", "type": "number"}),),
        )
    manager.ensure_pgstac_schema()
    assert state() == (rows, indexes, tables)
