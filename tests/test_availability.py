"""Tests for the availability re-check that need no database.

They cover how portal scenes are classified, how stored items are compared
with them, how each week is searched on the ingest's week grid and written
before the next, and how failed or incomplete searches, the stop time and a
rolled-back write keep items from being written.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bhoonidhi_stac.core.availability import (
    ACCESS,
    AVAILABILITY,
    DOWNLOADABLE,
    UPDATED,
    AvailabilityChange,
    AvailabilityWriteError,
    StoredAvailability,
    WriteResult,
    reconcile,
    scene_availability,
    scene_item_id,
    stac_timestamp,
    update_rows,
)
from bhoonidhi_stac.ops.availability import (
    product_week,
    recheck_product,
    week_start,
)
from bhoonidhi_stac.ops.spatial import QuadtreeResult

READY = "direct_available"
ARCHIVED = "direct_unavailable"


def _scene(item_id: str, ready: bool, priced: str = "OpenData_DirectDownload") -> dict:
    # The fields the downloader's classifiers read. CURR_SCENE_NO is "Y" for a
    # scene staged on the portal (Ready) and anything else for an archived one.
    return {
        "ID": item_id,
        "FILENAME": item_id,
        "PRICED": priced,
        "CURR_SCENE_NO": "Y" if ready else "N",
        "TABLETYPE": "PMETA",
    }


def _stored(item_id: str, availability: str, day: date, product: str | None = None):
    # Stored values as the transform writes them for an open-data scene.
    values = scene_availability(_scene(item_id, ready=availability == READY))
    assert values[AVAILABILITY] == availability
    return StoredAvailability(
        id=item_id,
        datetime=datetime.combine(day, datetime.min.time(), UTC),
        product=product,
        values=values,
    )


# --- classification ---------------------------------------------------------


def test_scene_availability_uses_the_downloader_classifiers():
    from bhoonidhi_downloader.core.search.availability import (
        access_of,
        availability_of,
        is_downloadable,
    )

    for ready in (True, False):
        scene = _scene("S1", ready)
        got = scene_availability(scene)
        assert got == {
            ACCESS: access_of(scene).value,
            AVAILABILITY: availability_of(scene).value,
            DOWNLOADABLE: is_downloadable(scene),
        }
    assert scene_availability(_scene("S1", True))[AVAILABILITY] == READY
    assert scene_availability(_scene("S1", False))[AVAILABILITY] == ARCHIVED


def test_scene_availability_matches_the_transform():
    # The item the transform builds from a scene must carry the same three
    # values, so a re-check never disagrees with a fresh ingest.
    from bhoonidhi_stac.core.database import DatabaseManager
    from bhoonidhi_stac.schemas import DatabaseSchema

    base = {
        "ID": "R2_W_zzz_01APR2023_15APR2023_15_N36E068_JTGN00GTD",
        "FILENAME": "R2_W_zzz_01APR2023_15APR2023_15_N36E068_JTGN00GTD",
        "DIRPATH": "/imgarchive/PRODUCTJPGS//RS2/AWIF/2023/APR/01/",
        "SATELLITE": "RS2",
        "SENSOR": "AWIF",
        "PATHNO": "N36E068",
        "DOP": "01-Apr-2023",
        "TABLETYPE": "PMETA",
        "ImgCrnNWLat": "46.0",
        "ImgCrnNWLon": "68.0",
        "ImgCrnNELat": "46.0",
        "ImgCrnNELon": "78.0",
        "ImgCrnSELat": "36.0",
        "ImgCrnSELon": "78.0",
        "ImgCrnSWLat": "36.0",
        "ImgCrnSWLon": "68.0",
    }
    manager = DatabaseManager(DatabaseSchema())
    for priced, staged in [
        ("OpenData_DirectDownload", "Y"),
        ("OpenData_DirectDownload", "N"),
        ("OpenData_OnOrder", "N"),
        ("Priced", "N"),
    ]:
        scene = {**base, "PRICED": priced, "CURR_SCENE_NO": staged}
        item = manager._ensure_stac_item(dict(scene), "resourcesat-2a-awifs")
        assert item is not None
        assert item["id"] == scene_item_id(scene)
        fresh = scene_availability(scene)
        for field in (ACCESS, AVAILABILITY, DOWNLOADABLE):
            assert item["properties"][field] == fresh[field], (priced, staged, field)


def test_scene_item_id_falls_back_to_filename():
    assert scene_item_id({"ID": "a", "FILENAME": "b"}) == "a"
    assert scene_item_id({"ID": "", "FILENAME": "b"}) == "b"
    assert scene_item_id({}) is None


# --- reconcile and the write rows -------------------------------------------


def test_reconcile_sorts_items_into_changed_unchanged_and_not_returned():
    day = date(2026, 9, 1)
    stored = [
        _stored("ready-now-archived", READY, day),
        _stored("still-ready", READY, day),
        _stored("archived-now-ready", ARCHIVED, day),
        _stored("gone", READY, day),
    ]
    found = {
        "ready-now-archived": scene_availability(_scene("x", ready=False)),
        "still-ready": scene_availability(_scene("x", ready=True)),
        "archived-now-ready": scene_availability(_scene("x", ready=True)),
        "only-on-portal": scene_availability(_scene("x", ready=True)),
    }
    rec = reconcile(stored, found)
    assert sorted(c.id for c in rec.changes) == [
        "archived-now-ready",
        "ready-now-archived",
    ]
    assert rec.unchanged == ["still-ready"]
    assert rec.not_returned == ["gone"]
    transitions = {c.id: c.transition for c in rec.changes}
    assert transitions["ready-now-archived"] == ("Ready", "Archived")
    assert transitions["archived-now-ready"] == ("Archived", "Ready")


def test_update_rows_patch_only_changed_fields_and_updated():
    change = AvailabilityChange(
        id="a",
        old={ACCESS: "Open", AVAILABILITY: READY, DOWNLOADABLE: True},
        new={ACCESS: "Open", AVAILABILITY: ARCHIVED, DOWNLOADABLE: False},
    )
    when = datetime(2026, 10, 5, 7, 30, tzinfo=UTC)
    (row,) = update_rows([change], when)
    assert row["id"] == "a"
    assert row["patch"] == {
        AVAILABILITY: ARCHIVED,
        DOWNLOADABLE: False,
        UPDATED: "2026-10-05T07:30:00Z",
    }
    # The guard compares all three fields, with null for a missing one.
    assert row["expect"] == {ACCESS: "Open", AVAILABILITY: READY, DOWNLOADABLE: True}


def test_update_rows_write_access_only_when_it_changes():
    same = AvailabilityChange(
        id="a",
        old={ACCESS: "Open", AVAILABILITY: READY, DOWNLOADABLE: True},
        new={ACCESS: "Open", AVAILABILITY: ARCHIVED, DOWNLOADABLE: True},
    )
    moved = AvailabilityChange(
        id="b",
        old={ACCESS: "Open", AVAILABILITY: READY, DOWNLOADABLE: True},
        new={ACCESS: "OnOrder", AVAILABILITY: "on_order", DOWNLOADABLE: False},
    )
    rows = {r["id"]: r for r in update_rows([same, moved], datetime.now(UTC))}
    assert ACCESS not in rows["a"]["patch"]
    assert rows["b"]["patch"][ACCESS] == "OnOrder"


def test_stac_timestamp_is_utc_with_z():
    assert stac_timestamp(datetime(2026, 10, 5, 7, 30, 9, tzinfo=UTC)) == (
        "2026-10-05T07:30:09Z"
    )


# --- the ingest's week grid ---------------------------------------------------


def test_week_start_is_sunday():
    assert week_start(date(2026, 10, 4)) == date(2026, 10, 4)  # Sunday
    assert week_start(date(2026, 10, 3)) == date(2026, 9, 27)  # Saturday
    assert week_start(date(2026, 10, 5)) == date(2026, 10, 4)  # Monday


def test_product_week_is_clamped_to_the_product_window():
    window = {
        "token": "L2",
        "operational_start": "2026-09-16",
        "operational_end": "2026-10-07",
    }
    # A product that started mid-week is searched from its start.
    first = product_week(window, date(2026, 9, 13))
    assert first is not None
    assert first.start == datetime(2026, 9, 16)
    assert first.end == datetime(2026, 9, 20)
    assert first.label == "L2|2026-09-13"
    # A retired product's last week stops at its end date.
    last = product_week(window, date(2026, 10, 4))
    assert last is not None
    assert last.end == datetime(2026, 10, 7)
    # Weeks wholly outside the window are not searched, as the ingest skips them.
    assert product_week(window, date(2026, 9, 6)) is None
    assert product_week(window, date(2026, 10, 11)) is None
    # The default product has an empty token and searches with no product.
    default = product_week({"token": ""}, date(2026, 9, 6))
    assert default is not None
    assert default.product is None
    assert default.label == "(default)|2026-09-06"


# --- re-checking a product week by week ---------------------------------------


def _qt(scenes: dict, capped: bool = False) -> QuadtreeResult:
    qt = QuadtreeResult()
    qt.scenes = scenes
    qt.calls = 1
    if capped:
        qt.residual_capped.append({"bbox": (0, 0, 1, 1), "returned": 500})
    return qt


class _FakeStore:
    """An in-memory stand-in for AvailabilityStore.

    ``write`` applies the change, so a later read sees the new values, and
    ``fingerprints`` hashes nothing but the id unless ``drift`` names it.
    """

    def __init__(self, items: list[StoredAvailability], fail_write_week=None):
        self.items = {i.id: i for i in items}
        self.writes: list[list[str]] = []
        self.weeks_asked: list[str | None] = []
        self.stamps: dict[str, str] = {}
        self.drift: set[str] = set()
        self.fail_write_week = fail_write_week

    def _product(self, item):
        return item.product or None

    def weeks(self, collection_id, product, availability):
        self.weeks_asked.append(product)
        counts: dict[date, int] = {}
        for i in self.items.values():
            if self._product(i) == product and i.values[AVAILABILITY] in availability:
                w = week_start(i.datetime.date())
                counts[w] = counts.get(w, 0) + 1
        return sorted(counts.items(), reverse=True)

    def stored(self, collection_id, since, until, availability):
        return [
            i
            for i in self.items.values()
            if since <= i.datetime < until and i.values[AVAILABILITY] in availability
        ]

    def existing_ids(self, collection_id, ids):
        return set(ids) & set(self.items)

    def write(self, collection_id, changes, updated):
        ids = [c.id for c in changes]
        if self.fail_write_week is not None:
            weeks = {week_start(self.items[i].datetime.date()) for i in ids}
            if self.fail_write_week in weeks:
                raise AvailabilityWriteError(collection_id, ids)
        self.writes.append(ids)
        stamp = stac_timestamp(updated)
        for c in changes:
            old = self.items[c.id]
            self.items[c.id] = StoredAvailability(
                id=old.id, datetime=old.datetime, product=old.product, values=c.new
            )
            self.stamps[c.id] = stamp
        return WriteResult(
            written=sorted(ids),
            skipped=[],
            fingerprints={i: f"fp-{i}" for i in ids},
            expected={c.id: {**c.new, UPDATED: stamp} for c in changes},
        )

    def fingerprints(self, collection_id, ids):
        return {i: f"fp-{i}" + ("-drifted" if i in self.drift else "") for i in ids}

    def refreshed(self, collection_id, ids):
        return {i: {**self.items[i].values, UPDATED: self.stamps[i]} for i in ids}


TODAY = date(2026, 10, 7)  # a Wednesday
WEEK_1, WEEK_2, WEEK_3 = date(2026, 9, 13), date(2026, 9, 20), date(2026, 9, 27)
WHEN = datetime(2026, 10, 6, 19, 0, tzinfo=UTC)


def _recheck(store, search, token="L2", **kw):
    return recheck_product(
        store=store,
        collection_id="c",
        product_window={"token": token, "operational_start": "2016-01-01"},
        search=search,
        today=TODAY,
        updated=WHEN,
        **kw,
    )


def _portal(**ready: bool):
    """A search answering with one scene per id, Ready or not as given."""
    return lambda pw: _qt({i: _scene(i, r) for i, r in ready.items()})


def test_weeks_are_checked_newest_first_and_written_one_at_a_time():
    store = _FakeStore(
        [
            _stored("w1", READY, WEEK_1, "L2"),
            _stored("w3", READY, WEEK_3, "L2"),
            _stored("w2", ARCHIVED, WEEK_2, "L2"),
        ]
    )
    searched: list[date] = []
    seen: list[tuple[date, list[str]]] = []

    def search(pw):
        searched.append(pw.week)
        return _portal(w1=False, w2=True, w3=False)(pw)

    res = _recheck(
        store,
        search,
        on_week=lambda wk: seen.append(
            (wk.product_week.week, [c.id for c in wk.written])
        ),
    )
    assert searched == [WEEK_3, WEEK_2, WEEK_1]
    # Each week is written on its own, before the next one is searched.
    assert store.writes == [["w3"], ["w2"], ["w1"]]
    assert seen == [(WEEK_3, ["w3"]), (WEEK_2, ["w2"]), (WEEK_1, ["w1"])]
    assert res.checked == 3
    assert res.changed == res.written == 3
    assert res.weeks_written == 3
    assert res.transitions == {("Ready", "Archived"): 2, ("Archived", "Ready"): 1}
    assert res.problems == 0
    assert store.stamps["w1"] == "2026-10-06T19:00:00Z"


def test_a_week_with_no_change_writes_nothing():
    store = _FakeStore([_stored("same", READY, WEEK_1, "L2")])
    seen = []
    res = _recheck(store, _portal(same=True), on_week=seen.append)
    assert store.writes == []
    assert res.unchanged == 1
    assert [wk.written for wk in seen] == [[]]


def test_failed_search_is_retried_after_every_other_week():
    store = _FakeStore(
        [
            _stored("a", READY, WEEK_1, "L2"),
            _stored("b", READY, WEEK_2, "L2"),
            _stored("c", READY, WEEK_3, "L2"),
        ]
    )
    calls: list[date] = []
    flaky = {WEEK_2: 1}

    def search(pw):
        calls.append(pw.week)
        if flaky.get(pw.week, 0) > 0:
            flaky[pw.week] -= 1
            raise TimeoutError("portal timed out")
        return _portal(a=False, b=False, c=False)(pw)

    res = _recheck(store, search, retries=1)
    assert calls == [WEEK_3, WEEK_2, WEEK_1, WEEK_2]
    assert store.writes == [["c"], ["a"], ["b"]]
    assert res.failed == []
    assert res.written == 3


def test_scenes_of_a_week_that_keeps_failing_are_never_written():
    store = _FakeStore(
        [_stored("ok", READY, WEEK_1, "L2"), _stored("bad", READY, WEEK_2, "L2")]
    )

    def search(pw):
        if pw.week == WEEK_2:
            raise ConnectionError("portal down")
        return _portal(ok=False)(pw)

    res = _recheck(store, search, retries=1)
    assert store.writes == [["ok"]]
    assert res.not_checked == 1
    assert res.not_returned == 0
    assert [o.product_week.label for o in res.failed] == ["L2|2026-09-20"]
    assert res.failed[0].attempts == 2


def test_not_returned_items_are_left_unchanged_and_counted():
    store = _FakeStore([_stored("gone", READY, WEEK_1, "L2")])
    res = _recheck(store, _portal())
    assert res.not_returned == 1
    assert res.changed == 0
    assert store.writes == []


def test_incomplete_search_counts_missing_items_as_not_verified():
    store = _FakeStore([_stored("maybe", READY, WEEK_1, "L2")])
    res = _recheck(store, lambda pw: _qt({}, capped=True))
    assert res.not_returned == 0
    assert res.not_verified == 1
    assert res.weeks_incomplete == 1


def test_unmatched_portal_scenes_are_counted_not_added():
    store = _FakeStore([_stored("known", READY, WEEK_1, "L2")])
    res = _recheck(store, _portal(known=True, new_scene=True))
    assert res.unmatched == 1
    assert res.changed == 0
    assert "new_scene" not in store.items


def test_only_the_product_asked_for_is_read_and_written():
    store = _FakeStore(
        [
            _stored("l2", READY, WEEK_1, "L2"),
            _stored("other", READY, WEEK_1, "L1"),
            _stored("default", READY, WEEK_1, None),
        ]
    )
    res = _recheck(store, _portal(l2=False, other=False, default=False))
    assert store.weeks_asked == ["L2"]
    assert store.writes == [["l2"]]
    assert res.checked == 1
    # The default product is the one whose scenes carry no product.
    res = _recheck(store, _portal(l2=False, other=False, default=False), token="")
    assert store.weeks_asked[-1] is None
    assert store.writes[-1] == ["default"]
    assert res.checked == 1


def test_weeks_the_ingest_does_not_search_are_counted_not_searched():
    store = _FakeStore(
        [
            # The week that has not ended yet: Sunday 4 October to Saturday 10.
            _stored("this-week", READY, date(2026, 10, 5), "L2"),
            # Before the product's operational start.
            _stored("too-early", READY, date(2015, 6, 1), "L2"),
            _stored("due", READY, WEEK_1, "L2"),
        ]
    )
    searched: list[date] = []

    def search(pw):
        searched.append(pw.week)
        return _qt({})

    res = _recheck(store, search)
    assert searched == [WEEK_1]
    assert res.not_planned == 2
    assert res.checked == 1


def test_no_week_starts_once_the_stop_time_is_reached():
    store = _FakeStore(
        [
            _stored("a", READY, WEEK_1, "L2"),
            _stored("b", READY, WEEK_2, "L2"),
            _stored("c", READY, WEEK_3, "L2"),
        ]
    )
    stop = datetime(2026, 10, 11, 18, 0, tzinfo=UTC)
    ticks = iter([stop - timedelta(minutes=1), stop])
    res = _recheck(
        store,
        _portal(a=False, b=False, c=False),
        stop_at=stop,
        clock=lambda: next(ticks),
    )
    assert store.writes == [["c"]]
    assert res.weeks_not_reached == [WEEK_2, WEEK_1]
    assert res.not_reached == 2
    assert "stop time" in res.stopped


def test_a_rolled_back_write_stops_the_run():
    store = _FakeStore(
        [
            _stored("a", READY, WEEK_1, "L2"),
            _stored("b", READY, WEEK_2, "L2"),
            _stored("c", READY, WEEK_3, "L2"),
        ],
        fail_write_week=WEEK_2,
    )
    seen = []
    res = _recheck(store, _portal(a=False, b=False, c=False), on_week=seen.append)
    assert store.writes == [["c"]]
    assert res.write_error is not None
    assert "rolled back" in res.stopped
    assert res.weeks_not_reached == [WEEK_1]
    # The rolled-back week is never reported as written.
    assert [wk.product_week.week for wk in seen] == [WEEK_3]
    assert res.written == 1
    assert res.changed == 2


def test_a_scene_that_reads_back_differently_is_a_problem():
    store = _FakeStore([_stored("a", READY, WEEK_1, "L2")])
    store.drift.add("a")
    res = _recheck(store, _portal(a=False))
    assert res.problems == 1
    assert res.first_problems == ["c/a: other fields changed"]


def test_dry_run_writes_nothing():
    store = _FakeStore([_stored("stale", READY, WEEK_1, "L2")])
    seen = []
    res = _recheck(store, _portal(stale=False), dry_run=True, on_week=seen.append)
    assert res.changed == 1
    assert res.written == 0
    assert store.writes == []
    assert [len(wk.changes) for wk in seen] == [1]
    assert [wk.written for wk in seen] == [[]]


@pytest.mark.parametrize("retries", [0, 1])
def test_portal_calls_and_search_time_are_totalled(retries):
    store = _FakeStore(
        [_stored("a", READY, WEEK_1, "L2"), _stored("b", READY, WEEK_2, "L2")]
    )
    res = _recheck(store, _portal(a=True, b=True), retries=retries)
    assert res.portal_calls == 2
    assert res.weeks_searched == 2
    assert res.search_seconds >= 0
