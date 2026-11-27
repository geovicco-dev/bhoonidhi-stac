"""The availability write against a real pgSTAC 0.9.12 database.

Skipped unless BHX_TEST_PGSTAC_DSN points at a pgSTAC database the test may
write to, for example:

    BHX_TEST_PGSTAC_DSN=postgresql://username:password@127.0.0.1:8861/postgis

Each test creates its own collection, so it never touches existing data, and
drops it afterwards. The central property: after a write, every stored
column of every item, ``content`` (assets and links included) compared as
text, is byte-for-byte what it was, apart from the refreshed availability
fields and ``updated`` of the items that changed.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime

import pytest

from bhoonidhi_stac.core.availability import (
    ACCESS,
    AVAILABILITY,
    DOWNLOADABLE,
    REFRESHED_FIELDS,
    UPDATED,
    AvailabilityChange,
    AvailabilityStore,
    AvailabilityWriteError,
    StoredAvailability,
)
from bhoonidhi_stac.schemas import DatabaseSchema

DSN = os.environ.get("BHX_TEST_PGSTAC_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="BHX_TEST_PGSTAC_DSN is not set")

READY = {ACCESS: "Open", AVAILABILITY: "direct_available", DOWNLOADABLE: True}
ARCHIVED = {ACCESS: "Open", AVAILABILITY: "direct_unavailable", DOWNLOADABLE: True}


def _store() -> AvailabilityStore:
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(DSN)
    return AvailabilityStore(
        DatabaseSchema(
            host=str(info.get("host", "localhost")),
            port=int(info.get("port") or 5432),
            user=str(info.get("user", "postgres")),
            password=str(info.get("password", "")),
            database=str(info.get("dbname", "postgres")),
        )
    )


def _item(collection: str, n: int, values: dict) -> dict:
    return {
        "type": "Feature",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": f"scene-{n:03d}",
        "collection": collection,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[77, 12], [78, 12], [78, 13], [77, 13], [77, 12]]],
        },
        "bbox": [77, 12, 78, 13],
        "properties": {
            "datetime": f"2026-09-{(n % 28) + 1:02d}T00:00:00Z",
            "created": "2026-09-30T00:00:00Z",
            "updated": "2026-09-30T00:00:00Z",
            "bhoonidhi:product": "L2",
            "CURR_SCENE_NO": "Y",
            **values,
        },
        "assets": {
            # An href pointing at our own copy, as the scene-assets design
            # will store it. A whole-item rewrite from the portal would lose it.
            "thumbnail": {
                "href": f"s3://bhoonidhi-assets/{collection}/scene-{n:03d}.jpg",
                "type": "image/jpeg",
                "roles": ["thumbnail"],
            },
            "metadata": {
                "href": f"https://bhoonidhi.nrsc.gov.in/meta/scene-{n:03d}.txt",
                "type": "text/plain",
                "roles": ["metadata"],
            },
        },
        "links": [
            {"rel": "via", "href": f"https://example.org/scene-{n:03d}"},
        ],
    }


@pytest.fixture
def db():
    import psycopg

    collection = f"avail-test-{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pgstac.create_collection(%s::jsonb)",
            (
                json.dumps(
                    {
                        "type": "Collection",
                        "stac_version": "1.1.0",
                        "id": collection,
                        "description": "availability write test",
                        "license": "other",
                        "links": [],
                        "extent": {
                            "spatial": {"bbox": [[-180, -90, 180, 90]]},
                            "temporal": {"interval": [[None, None]]},
                        },
                    }
                ),
            ),
        )
        items = [_item(collection, n, READY if n % 2 else ARCHIVED) for n in range(40)]
        cur.execute("SELECT pgstac.create_items(%s::jsonb)", (json.dumps(items),))
    yield collection
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT pgstac.delete_collection(%s)", (collection,))


def _rows(collection: str) -> dict[str, tuple]:
    import psycopg

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, content::text, encode(ST_AsEWKB(geometry), 'hex'),
                   datetime, end_datetime, private::text
            FROM pgstac.items WHERE collection = %s
            """,
            (collection,),
        )
        return {r[0]: r[1:] for r in cur.fetchall()}


def _api_item(collection: str, item_id: str) -> dict:
    import psycopg

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT pgstac.get_item(%s, %s)", (item_id, collection))
        row = cur.fetchone()
        assert row is not None
        return row[0]


def _without_refreshed(item: dict) -> dict:
    out = json.loads(json.dumps(item))
    for f in REFRESHED_FIELDS:
        out["properties"].pop(f, None)
    return out


def _change(item_id: str, old: dict, new: dict) -> AvailabilityChange:
    return AvailabilityChange(id=item_id, old=dict(old), new=dict(new))


def test_write_changes_only_the_refreshed_fields(db):
    store = _store()
    before_rows = _rows(db)
    before_api = {i: _api_item(db, i) for i in ("scene-001", "scene-002", "scene-003")}
    when = datetime(2026, 10, 5, 7, 30, 0, tzinfo=UTC)

    result = store.write(
        db,
        [
            _change("scene-001", READY, ARCHIVED),  # Ready -> Archived
            _change("scene-002", ARCHIVED, READY),  # Archived -> Ready
        ],
        when,
    )
    assert result.written == ["scene-001", "scene-002"]
    assert result.skipped == []

    after_rows = _rows(db)
    assert set(after_rows) == set(before_rows)
    changed = {i for i in before_rows if before_rows[i] != after_rows[i]}
    assert changed == {"scene-001", "scene-002"}

    for i in changed:
        b = json.loads(before_rows[i][0])
        a = json.loads(after_rows[i][0])
        # Every column other than content is byte-for-byte the same.
        assert before_rows[i][1:] == after_rows[i][1:]
        # Inside content, only the refreshed fields differ.
        assert _without_refreshed(a) == _without_refreshed(b)
        assert a["assets"] == b["assets"]
        assert a["links"] == b["links"]
        assert a["properties"][UPDATED] == "2026-10-05T07:30:00Z"
    a1 = json.loads(after_rows["scene-001"][0])["properties"]
    a2 = json.loads(after_rows["scene-002"][0])["properties"]
    assert a1[AVAILABILITY] == "direct_unavailable"
    assert a2[AVAILABILITY] == "direct_available"
    # access did not change, so it was not rewritten.
    assert a1[ACCESS] == "Open"

    # The item as the STAC API serves it: same apart from the refreshed fields.
    for i in ("scene-001", "scene-002"):
        assert _without_refreshed(_api_item(db, i)) == _without_refreshed(before_api[i])
    assert _api_item(db, "scene-003") == before_api["scene-003"]


def test_write_skips_an_item_another_writer_changed(db):
    store = _store()
    # The refresh read scene-005 as Archived, but it is stored as Ready.
    result = store.write(db, [_change("scene-005", ARCHIVED, READY)], datetime.now(UTC))
    assert result.written == []
    assert result.skipped == ["scene-005"]


def test_write_is_rolled_back_when_anything_else_changes(db):
    import psycopg
    from psycopg import sql

    store = _store()
    before = _rows(db)
    # A trigger that also rewrites an asset href stands in for a write path
    # that changes more than it should. It fires only for this test's
    # collection. The check must catch it and roll the whole write back.
    func = sql.Identifier("public", f"avail_tamper_{db[-8:]}")
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "CREATE FUNCTION {}() RETURNS trigger AS $$ BEGIN "
                "NEW.content := jsonb_set(NEW.content, '{{assets,thumbnail,href}}', "
                "'\"https://portal.example/x.jpg\"'); RETURN NEW; END $$ "
                "LANGUAGE plpgsql"
            ).format(func)
        )
        cur.execute(
            sql.SQL(
                "CREATE TRIGGER avail_tamper BEFORE UPDATE ON pgstac.items "
                "FOR EACH ROW WHEN (NEW.collection = {}) EXECUTE FUNCTION {}()"
            ).format(sql.Literal(db), func)
        )
    try:
        with pytest.raises(AvailabilityWriteError) as exc:
            store.write(db, [_change("scene-001", READY, ARCHIVED)], datetime.now(UTC))
        assert exc.value.item_ids == ["scene-001"]
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("DROP TRIGGER avail_tamper ON pgstac.items")
            cur.execute(sql.SQL("DROP FUNCTION {}()").format(func))
    assert _rows(db) == before


def test_stored_reads_only_refreshable_items_in_the_window(db):
    store = _store()
    rows = store.stored(
        db,
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 9, 8, tzinfo=UTC),
    )
    assert all(isinstance(r, StoredAvailability) for r in rows)
    days = {r.datetime.date().day for r in rows}
    assert days and days <= set(range(1, 8))
    assert {r.product for r in rows} == {"L2"}


def test_weeks_groups_a_products_items_by_the_ingest_week(db):
    import psycopg

    from bhoonidhi_stac.ops.availability import week_start

    def extra(n: int, when: str, product: str | None, values: dict) -> dict:
        item = _item(db, n, values)
        item["properties"]["datetime"] = when
        if product is None:
            del item["properties"]["bhoonidhi:product"]
        else:
            item["properties"]["bhoonidhi:product"] = product
        return item

    on_order = {ACCESS: "OnOrder", AVAILABILITY: "on_order", DOWNLOADABLE: False}
    extras = [
        # The last second of Saturday and the first of Sunday, in UTC.
        extra(100, "2026-09-19T23:59:59Z", "X", READY),
        extra(101, "2026-09-20T00:00:00Z", "X", ARCHIVED),
        extra(102, "2026-09-20T00:00:00Z", "X", on_order),
        extra(103, "2026-09-09T10:00:00Z", None, READY),
    ]
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        # A session time zone far from UTC must not move an item's week.
        cur.execute("SET TIME ZONE 'Australia/Sydney'")
        cur.execute("SELECT pgstac.create_items(%s::jsonb)", (json.dumps(extras),))

    store = _store()
    assert store.weeks(db, "X") == [
        (datetime(2026, 9, 20).date(), 1),
        (datetime(2026, 9, 13).date(), 1),
    ]
    # The default product is the one whose items carry no product.
    assert store.weeks(db, None) == [(datetime(2026, 9, 6).date(), 1)]

    # The fixture's 40 L2 items, all Ready or Archived, by their Sunday.
    expected: dict = {}
    for n in range(40):
        w = week_start(datetime(2026, 9, (n % 28) + 1).date())
        expected[w] = expected.get(w, 0) + 1
    assert store.weeks(db, "L2") == sorted(expected.items(), reverse=True)


def test_counts_gives_each_collections_ready_and_archived_items(db):
    import psycopg

    on_order = {ACCESS: "OnOrder", AVAILABILITY: "on_order", DOWNLOADABLE: False}
    extras = [_item(db, 100, on_order), _item(db, 101, READY)]
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT pgstac.create_items(%s::jsonb)", (json.dumps(extras),))

    counts = _store().counts()
    # The fixture's 40 items alternate Ready and Archived; On order is not counted.
    assert counts[db] == {"direct_available": 21, "direct_unavailable": 20}
    assert _store().counts(["on_order"])[db] == {"on_order": 1}
