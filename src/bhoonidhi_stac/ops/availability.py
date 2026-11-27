"""Re-check the availability of a product's scenes against the portal.

The portal moves scenes between staged (Ready) and archived, so a stored
scene's availability goes stale. ``recheck_product`` takes one product of one
collection and, one week at a time, newest week first, re-runs the search the
weekly ingest runs for that week, compares what the portal returns with what
pgSTAC holds, and writes only the availability fields that changed (see
``bhoonidhi_stac.core.availability``). Each week is written before the next
one is searched, so a run that stops part way keeps every week it finished.

Weeks follow the ingest's grid: a week starts on Sunday (UTC), only weeks that
have ended are searched, and each week is clamped to the product's
operational window, so the re-check asks the portal exactly what an ingest of
the same week would.

A week whose search fails is searched again after every other week. If it
still fails, nothing is written for its scenes and they are counted as not
checked, so a portal outage can never mark scenes as missing or change them.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bhoonidhi_stac.core.availability import (
    REFRESHABLE,
    AvailabilityChange,
    AvailabilityStore,
    AvailabilityWriteError,
    reconcile,
    scene_availability,
    scene_item_id,
)
from bhoonidhi_stac.ops.spatial import QuadtreeResult

logger = logging.getLogger(__name__)

#: The label the ingest's partitions use for a product with no token.
DEFAULT_PRODUCT = "(default)"

#: How many problem descriptions a result keeps; the counts are always full.
MAX_PROBLEMS = 20


def week_start(day: date) -> date:
    """The Sunday that starts the week containing ``day``."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


@dataclass(frozen=True)
class ProductWeek:
    """One product searched over one ingest week."""

    #: The manifest's product token; empty for a sensor's default product.
    token: str
    #: The Sunday the week starts on, the ingest's week partition key.
    week: date
    #: The search window, clamped to the product's operational window.
    start: datetime
    end: datetime

    @property
    def product(self) -> str | None:
        """The product passed to the portal search; None for the default."""
        return self.token or None

    @property
    def label(self) -> str:
        """``product|week``, the form the ingest's partition keys take."""
        return f"{self.token or DEFAULT_PRODUCT}|{self.week.isoformat()}"


def product_week(window: Mapping[str, Any], week: date) -> ProductWeek | None:
    """The search for ``week`` of the product in ``window``, as the ingest runs it.

    The week is clamped to the product's operational window. None when the
    week lies wholly outside it, since the ingest skips such weeks.
    """
    start, end = week, week + timedelta(days=7)
    op_start = window.get("operational_start")
    op_end = window.get("operational_end")
    if op_start:
        first = date.fromisoformat(op_start)
        if end <= first:
            return None
        start = max(start, first)
    if op_end:
        last = date.fromisoformat(op_end)
        if start >= last:
            return None
        end = min(end, last)
    return ProductWeek(
        token=window.get("token") or "",
        week=week,
        start=datetime.combine(start, datetime.min.time()),
        end=datetime.combine(end, datetime.min.time()),
    )


#: Runs the portal search for one product-week and returns the scenes found.
SearchFn = Callable[[ProductWeek], QuadtreeResult]


@dataclass
class ProductWeekOutcome:
    """What searching one product-week gave."""

    product_week: ProductWeek
    #: ``ok``, ``incomplete`` (a quadtree cell was left capped or skipped,
    #: so the portal may hold scenes the search did not return) or ``failed``.
    status: str = "failed"
    scenes: int = 0
    calls: int = 0
    seconds: float = 0.0
    attempts: int = 0
    error: str | None = None

    @property
    def searched(self) -> bool:
        return self.status in ("ok", "incomplete")


def _search_once(search: SearchFn, out: ProductWeekOutcome) -> dict[str, dict]:
    """Run one attempt, record it on ``out``, and return the scenes by item id."""
    out.attempts += 1
    t0 = time.perf_counter()
    try:
        qt = search(out.product_week)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded the same way
        out.seconds += time.perf_counter() - t0
        out.status = "failed"
        out.error = f"{type(exc).__name__}: {exc}"[:300]
        return {}
    out.seconds += time.perf_counter() - t0
    out.calls += qt.calls
    out.status = "incomplete" if (qt.residual_capped or qt.skipped_low_yield) else "ok"
    out.error = None
    scenes: dict[str, dict] = {}
    for scene in qt.scenes.values():
        item_id = scene_item_id(scene)
        if item_id:
            scenes[item_id] = scene
    out.scenes = len(scenes)
    return scenes


@dataclass
class WeekRecheck:
    """One week of one product, searched, compared and (unless a dry run) written."""

    outcome: ProductWeekOutcome
    #: Ready or Archived scenes in our record for this week.
    checked: int = 0
    unchanged: int = 0
    #: Scenes whose values on the portal today differ from our record.
    changes: list[AvailabilityChange] = field(default_factory=list)
    #: The changes that were written; empty in a dry run.
    written: list[AvailabilityChange] = field(default_factory=list)
    #: Changes left unwritten because the scene changed after it was read.
    skipped: list[str] = field(default_factory=list)
    #: Scenes a complete search did not return; left unchanged.
    not_returned: int = 0
    #: Scenes an incomplete search did not return; left unchanged.
    not_verified: int = 0
    #: Portal scenes with no item in pgSTAC; the weekly ingest adds those.
    unmatched: int = 0

    @property
    def product_week(self) -> ProductWeek:
        return self.outcome.product_week


@dataclass
class ProductRecheck:
    """The outcome of re-checking one product of one collection.

    Holds counts only, so a run over hundreds of weeks keeps one week's
    scenes in memory at a time.
    """

    collection_id: str
    token: str
    #: Weeks whose search succeeded, first try or on retry.
    weeks_searched: int = 0
    weeks_incomplete: int = 0
    weeks_written: int = 0
    #: Weeks whose search still failed after the retries.
    failed: list[ProductWeekOutcome] = field(default_factory=list)
    #: Weeks never started, because of ``stop_at`` or a rolled-back write.
    weeks_not_reached: list[date] = field(default_factory=list)
    #: Why the run stopped before the last week; empty when it did not.
    stopped: str = ""
    checked: int = 0
    unchanged: int = 0
    #: Changes found, by (before, after) label, e.g. (Ready, Archived).
    transitions: Counter[tuple[str, str]] = field(default_factory=Counter)
    changed: int = 0
    written: int = 0
    write_skipped: int = 0
    not_returned: int = 0
    not_verified: int = 0
    #: Scenes in weeks whose search failed; never compared or written.
    not_checked: int = 0
    #: Scenes in weeks the ingest does not search: outside the product's
    #: window, or a week that has not ended yet.
    not_planned: int = 0
    #: Scenes in weeks the run did not reach.
    not_reached: int = 0
    unmatched: int = 0
    portal_calls: int = 0
    search_seconds: float = 0.0
    #: Set when a write was rolled back; that week was not written.
    write_error: str | None = None
    #: Written scenes that, read back after the commit, differ in anything
    #: but the availability fields or do not hold the values written.
    problems: int = 0
    first_problems: list[str] = field(default_factory=list)

    def _add_week(self, week: WeekRecheck) -> None:
        self.weeks_searched += 1
        if week.outcome.status == "incomplete":
            self.weeks_incomplete += 1
        if week.written:
            self.weeks_written += 1
        self.checked += week.checked
        self.unchanged += week.unchanged
        self.changed += len(week.changes)
        self.transitions.update(c.transition for c in week.changes)
        self.written += len(week.written)
        self.write_skipped += len(week.skipped)
        self.not_returned += week.not_returned
        self.not_verified += week.not_verified
        self.unmatched += week.unmatched

    def _problem(self, text: str) -> None:
        self.problems += 1
        if len(self.first_problems) < MAX_PROBLEMS:
            self.first_problems.append(text)


def _verify(
    store: AvailabilityStore,
    collection_id: str,
    fingerprints: Mapping[str, str],
    expected: Mapping[str, Mapping[str, Any]],
    result: ProductRecheck,
) -> None:
    """Read the written scenes back after the commit and record any difference."""
    ids = list(fingerprints)
    now_fp = store.fingerprints(collection_id, ids)
    now_fields = store.refreshed(collection_id, ids)
    for item_id in ids:
        if item_id not in now_fp:
            result._problem(f"{collection_id}/{item_id}: missing")
        elif now_fp[item_id] != fingerprints[item_id]:
            result._problem(f"{collection_id}/{item_id}: other fields changed")
        elif now_fields.get(item_id) != expected[item_id]:
            result._problem(f"{collection_id}/{item_id}: values differ")


def recheck_product(
    *,
    store: AvailabilityStore,
    collection_id: str,
    product_window: Mapping[str, Any],
    search: SearchFn,
    today: date,
    updated: datetime,
    retries: int = 1,
    pause_seconds: float = 0.0,
    dry_run: bool = False,
    stop_at: datetime | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_week: Callable[[WeekRecheck], None] | None = None,
    log: logging.Logger | Any = logger,
) -> ProductRecheck:
    """Search, compare and write one product's Ready and Archived scenes.

    ``product_window`` is the product's entry in the collections manifest.
    Only weeks holding at least one Ready or Archived scene in our record are
    searched, newest first, and only their availability fields and
    ``updated`` are written. No week is started once ``clock()`` reaches
    ``stop_at``. ``on_week`` is called after each searched week, once its
    changes are written. A rolled-back write stops the run: nothing more is
    written.
    """
    token = product_window.get("token") or ""
    result = ProductRecheck(collection_id=collection_id, token=token)
    last_ended = week_start(today)
    plan: list[tuple[ProductWeek, int]] = []
    for week, count in store.weeks(collection_id, token or None, REFRESHABLE):
        pw = product_week(product_window, week) if week < last_ended else None
        if pw is None:
            result.not_planned += count
        else:
            plan.append((pw, count))
    plan.sort(key=lambda p: p[0].week, reverse=True)

    outcomes = {pw.week: ProductWeekOutcome(product_week=pw) for pw, _ in plan}
    pending = plan
    first = True
    for attempt in range(retries + 1):
        still_failed: list[tuple[ProductWeek, int]] = []
        for i, (pw, count) in enumerate(pending):
            if not result.stopped and stop_at is not None and clock() >= stop_at:
                result.stopped = f"reached the stop time {stop_at.isoformat()}"
            if result.stopped:
                rest = pending[i:]
                result.weeks_not_reached += [p.week for p, _ in rest]
                result.not_reached += sum(n for _, n in rest)
                break
            if not first and pause_seconds > 0:
                time.sleep(pause_seconds)
            first = False
            out = outcomes[pw.week]
            found = _search_once(search, out)
            if not out.searched:
                log.warning(
                    "%s: search failed on attempt %d: %s",
                    pw.label,
                    out.attempts,
                    out.error,
                )
                still_failed.append((pw, count))
                continue
            week = _check_week(store, collection_id, out, found)
            if week.changes and not dry_run:
                try:
                    write = store.write(collection_id, week.changes, updated)
                except AvailabilityWriteError as exc:
                    result.write_error = str(exc)
                    result.stopped = f"a write was rolled back in week {pw.week}"
                    log.error("%s: %s", pw.label, exc)
                    result._add_week(week)
                    continue
                kept = set(write.written)
                week.written = [c for c in week.changes if c.id in kept]
                week.skipped = write.skipped
                _verify(
                    store, collection_id, write.fingerprints, write.expected, result
                )
            result._add_week(week)
            log.info(
                "%s: %d checked, %d changed, %d written (%s, %d calls, %.1fs)",
                pw.label,
                week.checked,
                len(week.changes),
                len(week.written),
                out.status,
                out.calls,
                out.seconds,
            )
            if on_week is not None:
                on_week(week)
        pending = still_failed
        if not pending or result.stopped:
            break
        if attempt < retries:
            log.info("searching %d failed week(s) again", len(pending))

    for pw, count in pending:
        result.failed.append(outcomes[pw.week])
        result.not_checked += count
    for out in outcomes.values():
        result.portal_calls += out.calls
        result.search_seconds += out.seconds
    result.search_seconds = round(result.search_seconds, 2)
    log.info(
        "%s %s: %d checked, %d changed, %d written, %d not returned, "
        "%d not verified, %d not checked, %d not reached, %d unmatched portal scenes",
        collection_id,
        token or DEFAULT_PRODUCT,
        result.checked,
        result.changed,
        result.written,
        result.not_returned,
        result.not_verified,
        result.not_checked,
        result.not_reached,
        result.unmatched,
    )
    return result


def _check_week(
    store: AvailabilityStore,
    collection_id: str,
    out: ProductWeekOutcome,
    found: dict[str, dict],
) -> WeekRecheck:
    """Compare one searched week's scenes in our record with the portal today."""
    pw = out.product_week
    since = datetime.combine(pw.week, datetime.min.time(), UTC)
    stored = [
        s
        for s in store.stored(
            collection_id, since, since + timedelta(days=7), REFRESHABLE
        )
        if (s.product or "") == pw.token
    ]
    fresh = {item_id: scene_availability(s) for item_id, s in found.items()}
    rec = reconcile(stored, fresh)
    week = WeekRecheck(
        outcome=out,
        checked=len(stored),
        unchanged=len(rec.unchanged),
        changes=rec.changes,
        unmatched=len(set(found) - store.existing_ids(collection_id, list(found))),
    )
    if out.status == "incomplete":
        week.not_verified = len(rec.not_returned)
    else:
        week.not_returned = len(rec.not_returned)
    return week
