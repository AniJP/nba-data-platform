import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from nba_pipeline import sample_data
from nba_pipeline.alerts import format_airflow_failure, send_alert
from nba_pipeline.ingest import backfill_season, refresh_recent_games
from nba_pipeline.storage import game_path, read_json_gz
from tests.conftest import FakeResponse

SEASON = "2026-27"
NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)  # the morning after games 1-6


def _land(client, settings, espn, seqs):
    for seq in seqs:
        espn.game(seq)
    backfill_season(2026, client=client, settings=settings, now=NOW)


def test_refresh_lands_stat_corrections_only(client, settings, session, espn):
    _land(client, settings, espn, (1, 2))
    eid = sample_data.event_id(1)
    corrected = copy.deepcopy(sample_data.summary(1))
    corrected["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][6] = "12"  # assist reassigned
    corrected["news"] = {"articles": ["new headline"]}  # volatile change on the other game is ignored
    session.set(client.summary_url(eid), FakeResponse(200, corrected))
    other = sample_data.summary(2)
    other["news"] = {"articles": ["only news changed"]}
    session.set(client.summary_url(sample_data.event_id(2)), FakeResponse(200, other))

    stats = refresh_recent_games(2026, days=3, client=client, settings=settings, now=NOW)

    assert stats.status == "success"
    assert stats.games_checked == 2 and stats.games_corrected == 1
    after = read_json_gz(game_path(settings.bronze_dir, "summary", SEASON, eid))
    assert after["payload"]["boxscore"] == corrected["boxscore"]
    assert after["_meta"]["run_id"] == stats.run_id  # new ingested_at -> incremental model reprocesses it


def test_refresh_skips_games_outside_window(client, settings, espn):
    _land(client, settings, espn, (1,))
    stats = refresh_recent_games(2026, days=3, client=client, settings=settings, now=NOW + timedelta(days=10))
    assert stats.games_checked == 0 and stats.requests == 0


def test_refresh_reports_a_block(client, settings, session, espn):
    _land(client, settings, espn, (1,))
    session.set(client.summary_url(sample_data.event_id(1)), FakeResponse(403))
    stats = refresh_recent_games(2026, days=3, client=client, settings=settings, now=NOW)
    assert stats.status == "failed" and "blocked" in stats.errors[0]


def test_send_alert_without_webhook_only_logs(monkeypatch):
    monkeypatch.delenv("NBA_ALERT_WEBHOOK_URL", raising=False)
    assert send_alert("hello") is False


def test_send_alert_posts_slack_and_discord_keys():
    calls = []

    class S:
        def post(self, url, json, timeout):
            calls.append((url, json))
            return SimpleNamespace(raise_for_status=lambda: None)

    assert send_alert("boom", webhook_url="https://hooks.test/x", session=S()) is True
    assert calls == [("https://hooks.test/x", {"text": "boom", "content": "boom"})]


def test_send_alert_never_raises():
    class S:
        def post(self, *a, **k):
            raise ConnectionError("down")

    assert send_alert("boom", webhook_url="https://hooks.test/x", session=S()) is False


def test_format_airflow_failure():
    ti = SimpleNamespace(dag_id="nba_daily_pipeline", task_id="dbt_build", try_number=3,
                         log_url="http://localhost:8080/log")
    ctx = {"ti": ti, "dag_run": SimpleNamespace(run_id="scheduled__2026-10-28"),
           "exception": RuntimeError("2 tests failed")}
    msg = format_airflow_failure(ctx)
    assert "nba_daily_pipeline.dbt_build" in msg and "try 3" in msg
    assert "2 tests failed" in msg and "scheduled__2026-10-28" in msg and "http://localhost:8080/log" in msg


def test_sample_data_writes_run_log(tmp_path):
    sample_data.write_sample_bronze(tmp_path, n_games=2)
    lines = (tmp_path / "_state" / "run_log.jsonl").read_text().splitlines()
    assert len(lines) >= 3


def test_sample_tipoffs_are_utc():
    assert sample_data.tipoff(1).tzinfo == timezone.utc
