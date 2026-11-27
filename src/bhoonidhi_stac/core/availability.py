"""Keep stored scenes' availability current without rewriting the items.

The portal moves scenes between staged (Ready) and archived over time, so the
availability recorded when a scene was first stored goes stale. This module
derives availability from a fresh portal scene with the classifiers the
transform uses, compares it with what pgSTAC holds, and writes only the fields
that changed.

pgSTAC 0.9.12 has no partial update. Its ``update_item`` deletes the item and
creates it again, and ``upsert_item`` goes through ``items_staging_upsert``,
which deletes and re-inserts as well, so both replace every field of the item.
``AvailabilityStore.write`` instead runs one UPDATE that sets the changed
availability fields and the STAC ``updated`` time inside the stored
properties. pgSTAC dehydrates an item only against its collection's base item
(type, stac_version, the collection's item_assets and the collection id), so
properties are stored as given, and the rest of the item, assets and links
included, is left exactly as it was. pgSTAC's AFTER UPDATE trigger on
``items`` then refreshes the partition statistics and removes the rows from
its cache of formatted items.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from bhoonidhi_stac.schemas import DatabaseSchema

ACCESS = "bhoonidhi:access"
AVAILABILITY = "bhoonidhi:availability"
DOWNLOADABLE = "bhoonidhi:downloadable"
PRODUCT = "bhoonidhi:product"
UPDATED = "updated"

#: The fields a portal scene decides and a refresh may change.
AVAILABILITY_FIELDS: tuple[str, ...] = (ACCESS, AVAILABILITY, DOWNLOADABLE)

#: Every property a refresh may write: the availability fields and the STAC
#: ``updated`` time. A refresh never writes anything else.
REFRESHED_FIELDS: tuple[str, ...] = (*AVAILABILITY_FIELDS, UPDATED)

#: Stored availability values that a refresh checks: Ready and Archived.
REFRESHABLE = ("direct_available", "direct_unavailable")


def scene_item_id(scene: Mapping[str, Any]) -> str | None:
    """The id the transform gives the item it builds from a portal scene."""
    return scene.get("ID") or scene.get("FILENAME")


def scene_availability(scene: dict[str, Any]) -> dict[str, Any]:
    """A portal scene's availability fields, derived as the transform does.

    Calls bhoonidhi-downloader's ``access_of``, ``availability_of`` and
    ``is_downloadable``, the classifiers the transform calls, so a refreshed
    item carries the values a fresh ingest of the scene would give it.
    """
    from bhoonidhi_downloader.core.search.availability import (
        access_of,
        availability_of,
        is_downloadable,
    )

    return {
        ACCESS: access_of(scene).value,
        AVAILABILITY: availability_of(scene).value,
        DOWNLOADABLE: is_downloadable(scene),
    }


def availability_label(value: Any) -> str:
    """The word the downloader shows for an availability value (Ready, Archived)."""
    from bhoonidhi_downloader.core.search.availability import Availability

    try:
        return Availability(value).label
    except ValueError:
        return "unset" if value is None else str(value)


@dataclass(frozen=True)
class StoredAvailability:
    """An item's availability fields as stored in pgSTAC."""

    id: str
    datetime: datetime
    product: str | None
    values: dict[str, Any]


@dataclass(frozen=True)
class AvailabilityChange:
    """One item's availability fields as stored and as the portal has them now."""

    id: str
    old: dict[str, Any]
    new: dict[str, Any]

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(f for f in AVAILABILITY_FIELDS if self.old.get(f) != self.new[f])

    @property
    def transition(self) -> tuple[str, str]:
        """The availability labels before and after, e.g. (Ready, Archived)."""
        return (
            availability_label(self.old.get(AVAILABILITY)),
            availability_label(self.new[AVAILABILITY]),
        )


@dataclass
class Reconciliation:
    """Stored items compared with what the portal returned for them."""

    changes: list[AvailabilityChange] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    not_returned: list[str] = field(default_factory=list)


def reconcile(
    stored: Iterable[StoredAvailability], found: Mapping[str, Mapping[str, Any]]
) -> Reconciliation:
    """Compare stored items with fresh availability values from the portal.

    ``stored`` must hold only items whose search succeeded; ``found`` maps an
    item id to the values ``scene_availability`` derived from the portal scene.
    An item the portal did not return is listed as not returned and never
    changed.
    """
    out = Reconciliation()
    for item in stored:
        new = found.get(item.id)
        if new is None:
            out.not_returned.append(item.id)
        elif all(item.values.get(f) == new[f] for f in AVAILABILITY_FIELDS):
            out.unchanged.append(item.id)
        else:
            out.changes.append(
                AvailabilityChange(id=item.id, old=dict(item.values), new=dict(new))
            )
    return out


def stac_timestamp(moment: datetime) -> str:
    """A UTC time in the form STAC's ``updated`` field takes."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_rows(
    changes: Iterable[AvailabilityChange], updated: datetime
) -> list[dict[str, Any]]:
    """One row per change for the UPDATE: the values expected now, and the patch.

    ``expect`` holds all three availability fields as read, with JSON null for
    a missing field, so the write lands only if the item still holds exactly
    what was read. ``patch`` holds only the fields that changed, plus
    ``updated``.
    """
    stamp = stac_timestamp(updated)
    rows = []
    for c in changes:
        patch = {f: c.new[f] for f in c.changed_fields}
        if not patch:
            continue
        patch[UPDATED] = stamp
        rows.append(
            {
                "id": c.id,
                "expect": {f: c.old.get(f) for f in AVAILABILITY_FIELDS},
                "patch": patch,
            }
        )
    return rows


class AvailabilityWriteError(RuntimeError):
    """A write changed something other than the refreshed fields; rolled back."""

    def __init__(self, collection_id: str, item_ids: list[str]):
        self.collection_id = collection_id
        self.item_ids = item_ids
        super().__init__(
            f"{len(item_ids)} item(s) in {collection_id} changed outside the "
            f"availability fields; the write was rolled back: {item_ids[:5]}"
        )


@dataclass(frozen=True)
class WriteResult:
    """What one write did: the ids written, the ids skipped, and the
    fingerprint of each written item taken just before the write."""

    written: list[str]
    skipped: list[str]
    fingerprints: dict[str, str] = field(default_factory=dict)
    #: The refreshed fields each written item should now hold.
    expected: dict[str, dict[str, Any]] = field(default_factory=dict)


# Everything stored for an item except the refreshed properties, as one hash.
# pgSTAC keeps id, collection, geometry and the datetimes in columns and the
# rest of the item in ``content``, so the hash covers both.
_FINGERPRINT = """
    md5(
        (i.content
            #- '{properties,bhoonidhi:access}'
            #- '{properties,bhoonidhi:availability}'
            #- '{properties,bhoonidhi:downloadable}'
            #- '{properties,updated}')::text
        || '|' || encode(ST_AsEWKB(i.geometry), 'hex')
        || '|' || extract(epoch FROM i.datetime)::text
        || '|' || extract(epoch FROM i.end_datetime)::text
        || '|' || COALESCE(i.private::text, '')
    )
"""

# Locks the rows in id order before anything is read from them, so no other
# writer can change them between this read and the check after the UPDATE.
# pgSTAC's upsert locks in (collection, id) order too, so the two cannot
# deadlock.
_LOCK_AND_FINGERPRINT_SQL = f"""
    SELECT i.id, {_FINGERPRINT}
    FROM pgstac.items AS i
    WHERE i.collection = %s AND i.id = ANY(%s)
    ORDER BY i.id
    FOR UPDATE
"""

_FINGERPRINT_SQL = f"""
    SELECT i.id, {_FINGERPRINT}
    FROM pgstac.items AS i
    WHERE i.collection = %s AND i.id = ANY(%s)
"""

_REFRESHED_SQL = """
    SELECT id,
        content->'properties'->'bhoonidhi:access',
        content->'properties'->'bhoonidhi:availability',
        content->'properties'->'bhoonidhi:downloadable',
        content->'properties'->'updated'
    FROM pgstac.items
    WHERE collection = %s AND id = ANY(%s)
"""

_STORED_SQL = """
    SELECT
        id,
        datetime,
        content->'properties'->>'bhoonidhi:product',
        content->'properties'->'bhoonidhi:access',
        content->'properties'->'bhoonidhi:availability',
        content->'properties'->'bhoonidhi:downloadable'
    FROM pgstac.items
    WHERE collection = %s
      AND datetime >= %s AND datetime < %s
      AND content->'properties'->>'bhoonidhi:availability' = ANY(%s)
"""

# Weeks start on Sunday (UTC), as the ingest's week partitions do: moving a
# time one day forward puts a Sunday into the ISO week (Monday to Sunday) that
# date_trunc finds, and the day taken off again gives that week's Sunday.
# ``IS NOT DISTINCT FROM`` matches a NULL product to items without one.
_WEEKS_SQL = """
    SELECT
        (date_trunc('week', (datetime AT TIME ZONE 'UTC') + interval '1 day')
            - interval '1 day')::date AS week,
        count(*)
    FROM pgstac.items
    WHERE collection = %s
      AND content->'properties'->>'bhoonidhi:product' IS NOT DISTINCT FROM %s
      AND content->'properties'->>'bhoonidhi:availability' = ANY(%s)
    GROUP BY 1
    ORDER BY 1 DESC
"""

# The filter is the expression the availability search index is built on
# (DatabaseManager.SEARCH_INDEXES), so each scene table can answer from it.
_COUNTS_SQL = """
    SELECT collection,
           pgstac.to_text(content->'properties'->'bhoonidhi:availability'),
           count(*)
    FROM pgstac.items
    WHERE pgstac.to_text(content->'properties'->'bhoonidhi:availability') = ANY(%s)
    GROUP BY 1, 2
"""

# One statement, so pgSTAC's statement-level trigger runs once per write. The
# WHERE clause compares the three stored fields with what was read: an item
# whose availability another writer changed since then is left alone.
_UPDATE_SQL = """
    WITH u AS (
        SELECT * FROM jsonb_to_recordset(%(rows)s::jsonb)
            AS u(id text, expect jsonb, patch jsonb)
    )
    UPDATE pgstac.items AS i
    SET content = jsonb_set(
        i.content,
        '{properties}',
        COALESCE(i.content->'properties', '{}'::jsonb) || u.patch
    )
    FROM u
    WHERE i.collection = %(collection)s
      AND i.id = u.id
      AND jsonb_build_object(
            'bhoonidhi:access',
            COALESCE(i.content->'properties'->'bhoonidhi:access', 'null'::jsonb),
            'bhoonidhi:availability',
            COALESCE(i.content->'properties'->'bhoonidhi:availability', 'null'::jsonb),
            'bhoonidhi:downloadable',
            COALESCE(i.content->'properties'->'bhoonidhi:downloadable', 'null'::jsonb)
          ) = u.expect
    RETURNING i.id
"""


def _refreshed_row(row: tuple) -> dict[str, Any]:
    return {ACCESS: row[1], AVAILABILITY: row[2], DOWNLOADABLE: row[3], UPDATED: row[4]}


class AvailabilityStore:
    """Reads and writes the availability fields of items in pgSTAC."""

    def __init__(self, params: DatabaseSchema):
        self.dsn = params.dsn

    def stored(
        self,
        collection_id: str,
        since: datetime,
        until: datetime,
        availability: Iterable[str] = REFRESHABLE,
    ) -> list[StoredAvailability]:
        """Items of a collection acquired in [since, until) with the given availability."""
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(_STORED_SQL, (collection_id, since, until, list(availability)))
            return [
                StoredAvailability(
                    id=row[0],
                    datetime=row[1],
                    product=row[2],
                    values={ACCESS: row[3], AVAILABILITY: row[4], DOWNLOADABLE: row[5]},
                )
                for row in cur.fetchall()
            ]

    def item_count(self, collection_id: str) -> int:
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pgstac.items WHERE collection = %s",
                (collection_id,),
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def weeks(
        self,
        collection_id: str,
        product: str | None,
        availability: Iterable[str] = REFRESHABLE,
    ) -> list[tuple[date, int]]:
        """The ingest weeks holding a product's items with the given availability.

        Returns (the week's Sunday, item count), newest week first. A ``None``
        product means the collection's unnamed default product, whose items
        carry no ``bhoonidhi:product``.
        """
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(_WEEKS_SQL, (collection_id, product, list(availability)))
            return [(row[0], row[1]) for row in cur.fetchall()]

    def counts(
        self, availability: Iterable[str] = REFRESHABLE
    ) -> dict[str, dict[str, int]]:
        """Every collection's item count for each of the given availabilities.

        Returns {collection: {availability: count}}. A collection with no
        item of a given availability has no entry for it.
        """
        out: dict[str, dict[str, int]] = {}
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(_COUNTS_SQL, (list(availability),))
            for collection_id, value, count in cur.fetchall():
                out.setdefault(collection_id, {})[value] = count
        return out

    def write(
        self,
        collection_id: str,
        changes: list[AvailabilityChange],
        updated: datetime,
    ) -> WriteResult:
        """Write the changed fields and ``updated`` in one checked transaction.

        The rows are locked and fingerprinted first, then updated, then
        fingerprinted again. If any written item differs in anything other
        than the refreshed fields, or does not hold the values written, the
        transaction is rolled back and ``AvailabilityWriteError`` is raised.
        An item whose stored availability no longer matches ``change.old`` is
        skipped, so a value read before another writer stored a newer one
        never overwrites it.
        """
        rows = update_rows(changes, updated)
        if not rows:
            return WriteResult(written=[], skipped=[])
        expected = {c.id: c.new for c in changes}
        stamp = stac_timestamp(updated)
        ids = [r["id"] for r in rows]
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(_LOCK_AND_FINGERPRINT_SQL, (collection_id, ids))
            before = dict(cur.fetchall())
            cur.execute(
                _UPDATE_SQL, {"rows": json.dumps(rows), "collection": collection_id}
            )
            written = sorted(r[0] for r in cur.fetchall())
            cur.execute(_FINGERPRINT_SQL, (collection_id, written))
            after = dict(cur.fetchall())
            cur.execute(_REFRESHED_SQL, (collection_id, written))
            now = {row[0]: _refreshed_row(row) for row in cur.fetchall()}
            bad = [
                i
                for i in written
                if before.get(i) != after.get(i)
                or now[i] != {**expected[i], UPDATED: stamp}
            ]
            if bad:
                raise AvailabilityWriteError(collection_id, bad)
        skipped = sorted(set(ids) - set(written))
        return WriteResult(
            written=written,
            skipped=skipped,
            fingerprints={i: before[i] for i in written},
            expected={i: {**expected[i], UPDATED: stamp} for i in written},
        )

    def existing_ids(self, collection_id: str, ids: list[str]) -> set[str]:
        """The ids in ``ids`` that the collection holds, whatever their availability."""
        if not ids:
            return set()
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM pgstac.items WHERE collection = %s AND id = ANY(%s)",
                (collection_id, list(ids)),
            )
            return {row[0] for row in cur.fetchall()}

    def fingerprints(self, collection_id: str, ids: list[str]) -> dict[str, str]:
        """A hash of everything stored for each item except the refreshed fields."""
        if not ids:
            return {}
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(_FINGERPRINT_SQL, (collection_id, list(ids)))
            return dict(cur.fetchall())

    def refreshed(
        self, collection_id: str, ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """The refreshed fields of each item as stored now."""
        if not ids:
            return {}
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(_REFRESHED_SQL, (collection_id, list(ids)))
            return {row[0]: _refreshed_row(row) for row in cur.fetchall()}
