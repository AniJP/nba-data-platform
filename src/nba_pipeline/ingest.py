"""Extract jobs: incremental season backfill, stat-correction refresh, daily scoreboard snapshots."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .client import Blocked, EspnClient, FetchError, NotAvailable
from .config import Settings
from .contracts import (
    ContractViolation,
    event_status,
    is_included_event,
    stats_digest,
    summary_is_final,
    trim_summary,
    validate_scoreboard,
    validate_summary,
)
from .seasons import espn_season_year, fallback_season_dates, season_label, to_espn_date
from .state import StateStore, append_run_log
from .storage import (
    atomic_write_json_gz,
    envelope,
    game_path,
    quarantine_path,
    read_json_gz,
    scoreboard_path,
    utcnow,
)

log = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")  # NBA game dates are US Eastern


@dataclass
class RunStats:
    run_id: str
    job: str
    started_at: str
    season: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    requests: int = 0
    dates_scanned: int = 0
    games_written: int = 0
    not_final: int = 0
    postponed: int = 0
    not_available: int = 0
    quarantined: int = 0
    games_checked: int = 0
    games_corrected: int = 0
    errors: list[str] = field(default_factory=list)
    watermark_before: str | None = None
    watermark_after: str | None = None
    status: str = "running"

    def finish(self, started_monotonic_s: float) -> None:
        self.finished_at = utcnow().isoformat()
        self.duration_s = round(time.monotonic() - started_monotonic_s, 3)
        self.status = "failed" if self.errors else "success"


def _new_run_id() -> str:
    return f"{utcnow():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"


def _quarantine(settings: Settings, entity: str, key: str, payload: Any, reason: str, run_id: str) -> None:
    ts = utcnow()
    atomic_write_json_gz(
        quarantine_path(settings.quarantine_dir, entity, key, ts),
        {"_meta": {"reason": reason, "run_id": run_id, "quarantined_at": ts.isoformat()}, "payload": payload},
    )


def season_game_dates(client: EspnClient, season_start_year: int) -> list[str]:
    """Game days of the season, from ESPN's league calendar (one request).

    The calendar lists preseason and regular-season game days. Every day after its last entry
    (through Jun 30) is appended so play-in and playoff games are scanned too; future days are
    filtered out by the caller, so this costs nothing during the regular season. If no calendar is
    available for the season, every day Oct 1 to Jun 30 is scanned.
    """
    every_day = fallback_season_dates(season_start_year)
    board = client.scoreboard(f"{season_start_year}1101")
    try:
        league = board["leagues"][0]
        if int(league["season"]["year"]) == espn_season_year(season_start_year):
            days = sorted({str(d)[:10] for d in league["calendar"] if isinstance(d, str)})
            if days:
                return days + [d for d in every_day if d > days[-1]]
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    log.info("ESPN calendar unavailable for %s; scanning every day", season_label(season_start_year))
    return every_day


def _land_summary(settings, client, stats, season, event_id) -> bool:
    """Fetch, validate and land one game. Returns True if landed."""
    try:
        payload = client.summary(event_id)
    except NotAvailable:
        stats.not_available += 1
        return False
    try:
        validate_summary(payload, expected_event_id=event_id)
    except ContractViolation as exc:
        _quarantine(settings, "summary", event_id, trim_summary(payload), str(exc), stats.run_id)
        stats.quarantined += 1
        return False
    if not summary_is_final(payload):  # scoreboard said final, summary disagrees: retry next run
        stats.not_final += 1
        return False
    atomic_write_json_gz(
        game_path(settings.bronze_dir, "summary", season, event_id),
        envelope(trim_summary(payload), client.summary_url(event_id), stats.run_id),
    )
    return True


def backfill_season(
    season_start_year: int,
    client: EspnClient | None = None,
    settings: Settings | None = None,
    max_new_games: int | None = None,
    now: datetime | None = None,
) -> RunStats:
    """Land every final game of a season that isn't in bronze yet.

    * Incremental: resumes the day after the date watermark (``settled_through``).
    * Idempotent: landed events are skipped, so re-runs re-download nothing.
    * Resumable: state is saved after every game.
    * Postponed or canceled games don't block the watermark. An in-progress or scheduled game
      does, so that date is re-scanned on the next run.
    * A blocked source (HTTP 401/403) aborts the run as *failed*, never as "0 new games".
    """
    settings = settings or Settings()
    client = client or EspnClient(settings)
    store = StateStore(settings.state_file)
    season = season_label(season_start_year)
    key = f"espn:{season}"
    state = store.load(key)
    today_et = (now or utcnow()).astimezone(EASTERN).date().isoformat()

    stats = RunStats(run_id=_new_run_id(), job="backfill_season", started_at=utcnow().isoformat(), season=season)
    stats.watermark_before = state.settled_through
    t0 = time.monotonic()
    requests_before = client.request_count

    try:
        dates = [d for d in season_game_dates(client, season_start_year)
                 if (state.settled_through is None or d > state.settled_through) and d <= today_et]
        can_advance = True
        for day in dates:
            if max_new_games is not None and stats.games_written >= max_new_games:
                break
            board = client.scoreboard(to_espn_date(day))
            validate_scoreboard(board)
            stats.dates_scanned += 1
            settled, budget_hit = True, False

            for event in board["events"]:
                if not is_included_event(event):
                    continue
                event_id = str(event["id"])
                if state.is_ingested(event_id):
                    continue
                status = event_status(event)
                if status in ("postponed", "canceled"):
                    stats.postponed += 1
                    continue
                if status != "final":
                    stats.not_final += 1
                    settled = False
                    continue
                if max_new_games is not None and stats.games_written >= max_new_games:
                    settled, budget_hit = False, True
                    break
                if _land_summary(settings, client, stats, season, event_id):
                    state.mark_ingested(event_id)
                    stats.games_written += 1
                    store.save(key, state)
                else:
                    settled = False

            if settled and can_advance:
                state.settled_through = day
                store.save(key, state)
            else:
                can_advance = False
            if budget_hit:
                break
    except Blocked as exc:
        stats.errors.append(f"source blocked the pipeline: {exc}")
    except ContractViolation as exc:
        stats.errors.append(f"scoreboard contract violation: {exc}")
    except (NotAvailable, FetchError) as exc:
        stats.errors.append(f"{type(exc).__name__}: {exc}")

    stats.watermark_after = state.settled_through
    stats.requests = client.request_count - requests_before
    stats.finish(t0)
    append_run_log(settings.run_log_file, asdict(stats))
    log.info("backfill %s: %s", season, asdict(stats))
    return stats


def refresh_recent_games(
    season_start_year: int,
    days: int = 3,
    client: EspnClient | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> RunStats:
    """Re-fetch games played in the last ``days`` days and re-land any whose stats changed.

    Leagues issue stat corrections after games end (an assist or rebound reassigned, say).
    Only the game facts are compared (``stats_digest``), never volatile extras. A changed game is
    re-landed with a new ``ingested_at``, so the incremental ``fct_player_games`` model picks it up
    and its delete+insert strategy replaces the stale rows.
    """
    settings = settings or Settings()
    client = client or EspnClient(settings)
    cutoff = (now or utcnow()) - timedelta(days=days)
    season = season_label(season_start_year)
    stats = RunStats(run_id=_new_run_id(), job="refresh_recent_games", started_at=utcnow().isoformat(),
                     season=season)
    t0 = time.monotonic()
    requests_before = client.request_count

    season_dir = settings.bronze_dir / "summary" / f"season={season}"
    for path in sorted(season_dir.glob("event_id=*.json.gz")):
        stored = read_json_gz(path)["payload"]
        tip = datetime.fromisoformat(stored["header"]["competitions"][0]["date"].replace("Z", "+00:00"))
        if tip < cutoff:
            continue
        event_id = str(stored["header"]["id"])
        stats.games_checked += 1
        try:
            fresh = client.summary(event_id)
            validate_summary(fresh, expected_event_id=event_id)
        except Blocked as exc:
            stats.errors.append(f"source blocked the pipeline: {exc}")
            break
        except ContractViolation as exc:
            stats.errors.append(f"{event_id} refresh contract: {exc}")
            continue
        except (NotAvailable, FetchError) as exc:
            stats.errors.append(f"{event_id} refresh: {type(exc).__name__}: {exc}")
            continue
        if not summary_is_final(fresh) or stats_digest(fresh) == stats_digest(stored):
            continue
        atomic_write_json_gz(path, envelope(trim_summary(fresh), client.summary_url(event_id), stats.run_id))
        stats.games_corrected += 1
        log.info("stat correction landed for %s", event_id)

    stats.requests = client.request_count - requests_before
    stats.finish(t0)
    append_run_log(settings.run_log_file, asdict(stats))
    return stats


def snapshot_scoreboard(client: EspnClient | None = None, settings: Settings | None = None) -> RunStats:
    """Land today's scoreboard as an immutable, timestamped snapshot (game-status history)."""
    settings = settings or Settings()
    client = client or EspnClient(settings)
    stats = RunStats(run_id=_new_run_id(), job="snapshot_scoreboard", started_at=utcnow().isoformat())
    t0 = time.monotonic()
    requests_before = client.request_count
    payload: Any = None
    try:
        payload = client.scoreboard()
        validate_scoreboard(payload)
        atomic_write_json_gz(
            scoreboard_path(settings.bronze_dir, utcnow()),
            envelope(payload, client.scoreboard_url(), stats.run_id),
        )
        stats.games_written = len(payload["events"])
    except ContractViolation as exc:
        _quarantine(settings, "scoreboard", "today", payload, str(exc), stats.run_id)
        stats.quarantined += 1
        stats.errors.append(f"scoreboard contract: {exc}")
    except Blocked as exc:
        stats.errors.append(f"source blocked the pipeline: {exc}")
    except (NotAvailable, FetchError) as exc:
        stats.errors.append(f"scoreboard: {type(exc).__name__}: {exc}")
    stats.requests = client.request_count - requests_before
    stats.finish(t0)
    append_run_log(settings.run_log_file, asdict(stats))
    return stats
