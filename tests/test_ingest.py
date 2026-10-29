import json
from datetime import datetime, timezone

from nba_pipeline import sample_data
from nba_pipeline.ingest import backfill_season, snapshot_scoreboard
from nba_pipeline.state import StateStore
from nba_pipeline.storage import game_path, read_json_gz
from tests.conftest import FakeResponse

SEASON = "2026-27"
NOW = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)  # all sample games (Oct 21-24) are in the past


def run(client, settings, **kw):
    kw.setdefault("now", NOW)
    return backfill_season(2026, client=client, settings=settings, **kw)


def state(settings):
    return StateStore(settings.state_file).load(f"espn:{SEASON}")


def test_backfill_lands_trimmed_summaries_with_lineage(client, settings, espn):
    ids = [espn.game(seq)[0] for seq in (1, 2, 7)]  # two dates
    stats = run(client, settings)

    assert stats.status == "success" and stats.games_written == 3
    assert stats.dates_scanned >= 2  # both game days, plus empty days after the calendar's end
    doc = read_json_gz(game_path(settings.bronze_dir, "summary", SEASON, ids[0]))
    assert doc["payload"]["header"]["id"] == ids[0]
    assert "news" not in doc["payload"] and "odds" not in doc["payload"]  # volatile sections trimmed
    assert doc["_meta"]["source_url"].endswith(f"summary?event={ids[0]}")
    assert stats.watermark_after == "2026-10-30"  # every day through "today" (ET) is settled


def test_rerun_is_idempotent(client, settings, session, espn):
    espn.game(1)
    espn.game(2)
    run(client, settings)
    before = len(session.calls)
    second = run(client, settings)
    assert second.games_written == 0
    new_calls = session.calls[before:]
    assert not any("summary" in u for u in new_calls)  # nothing re-downloaded
    assert len(new_calls) == 1  # just the calendar lookup; settled dates are not re-scanned


def test_blocked_source_fails_loudly(client, settings, session, espn):
    espn.game(1)
    session.set(client.scoreboard_url("20261101"), FakeResponse(403))
    stats = run(client, settings)
    assert stats.status == "failed" and stats.games_written == 0
    assert "blocked" in stats.errors[0]


def test_in_progress_game_holds_the_watermark_and_is_picked_up_later(client, settings, espn):
    _, day1 = espn.game(1)
    live_id, _ = espn.game(2, status="in_progress")
    espn.game(7)  # next day
    first = run(client, settings)
    assert first.games_written == 2 and first.not_final == 1
    assert first.watermark_after is None  # day 1 isn't settled, so nothing after it is either
    assert state(settings).is_ingested(espn.days[day1][0]["id"])

    espn.game(2, status="final")
    second = run(client, settings)
    assert second.games_written == 1  # only the newly finished game is fetched
    assert second.watermark_after is not None and second.watermark_after > day1
    assert state(settings).is_ingested(live_id)


def test_postponed_game_does_not_block_the_watermark(client, settings, espn):
    _, day = espn.game(1)
    espn.game(2, status="postponed")
    stats = run(client, settings)
    assert stats.postponed == 1 and stats.games_written == 1
    assert stats.watermark_after is not None and stats.watermark_after >= day  # moved past the postponement


def test_contract_violation_is_quarantined_and_retried(client, settings, espn):
    broken = sample_data.summary(1)
    del broken["boxscore"]["players"][0]["statistics"][0]["keys"][1]  # 'points' disappears
    eid, _ = espn.game(1, summary_override=broken)
    stats = run(client, settings)
    assert stats.quarantined == 1 and stats.games_written == 0
    assert not game_path(settings.bronze_dir, "summary", SEASON, eid).exists()
    q = list((settings.quarantine_dir / "summary").glob(f"{eid}_*.json.gz"))
    assert len(q) == 1 and "points" in read_json_gz(q[0])["_meta"]["reason"]
    assert not state(settings).is_ingested(eid)


def test_excludes_preseason_and_non_franchise_games(client, settings, espn, session):
    espn.game(1)
    pre = sample_data.scoreboard_event(2, season_type=1)
    allstar = sample_data.scoreboard_event(3)
    allstar["competitions"][0]["competitors"][0]["team"]["id"] = "31"
    day = next(iter(espn.days))
    espn.days[day] += [pre, allstar]
    espn._publish()
    stats = run(client, settings)
    assert stats.games_written == 1


def test_max_new_games(client, settings, espn):
    for seq in range(1, 6):
        espn.game(seq)
    stats = run(client, settings, max_new_games=2)
    assert stats.games_written == 2 and stats.watermark_after is None
    rest = run(client, settings)
    assert rest.games_written == 3 and rest.watermark_after is not None


def test_future_dates_are_not_requested(client, settings, session, espn):
    espn.game(1)
    run(client, settings, now=datetime(2026, 10, 20, 12, tzinfo=timezone.utc))
    assert not any("dates=2026102" in u and "dates=20261101" not in u for u in session.calls)


def test_run_log_records_metrics(client, settings, espn):
    espn.game(1)
    run(client, settings)
    rec = json.loads(settings.run_log_file.read_text().splitlines()[-1])
    assert rec["job"] == "backfill_season" and rec["games_written"] == 1
    # calendar + one scoreboard per day through "today" + one summary
    assert rec["requests"] == 1 + rec["dates_scanned"] + 1


def test_scoreboard_snapshot(client, settings, session):
    payload = sample_data.scoreboard([sample_data.scoreboard_event(1)])
    session.add(client.scoreboard_url(), FakeResponse(200, payload))
    stats = snapshot_scoreboard(client=client, settings=settings)
    assert stats.status == "success" and stats.games_written == 1
    files = list((settings.bronze_dir / "scoreboard").rglob("*.json.gz"))
    assert len(files) == 1 and "snapshot_date=" in str(files[0])


def test_scoreboard_snapshot_blocked(client, settings, session):
    session.add(client.scoreboard_url(), FakeResponse(403))
    stats = snapshot_scoreboard(client=client, settings=settings)
    assert stats.status == "failed" and "blocked" in stats.errors[0]
