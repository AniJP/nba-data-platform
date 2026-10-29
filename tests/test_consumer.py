"""Runs in CI (needs duckdb + kafka-python); skipped where those aren't installed."""
from types import SimpleNamespace

import pytest

from nba_pipeline.live import GameState, LiveGameTracker, naive_home_win_probability
from tests.test_live import snap

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("kafka")

from streaming.consumer import DDL, write_batch  # noqa: E402


def messages(events, start_offset=0):
    return [SimpleNamespace(value=e.to_record(), offset=start_offset + i) for i, e in enumerate(events)]


def test_events_are_written_once_even_when_replayed():
    con = duckdb.connect(":memory:")
    con.execute(DDL)
    t = LiveGameTracker()
    events = t.update(snap(home=0, away=0)) + t.update(snap(home=2, away=0))
    assert write_batch(con, messages(events)) == len(events)
    assert write_batch(con, messages(events, start_offset=100)) == 0  # redelivery after a crash
    assert con.execute("select count(*) from live.game_events").fetchone()[0] == len(events)


def test_latest_state_view_matches_python_win_probability():
    con = duckdb.connect(":memory:")
    con.execute(DDL)
    t = LiveGameTracker()
    t.update(snap(period=3, clock="6:00", home=70, away=70))
    events = t.update(snap(period=3, clock="5:30", home=74, away=70))
    write_batch(con, messages(events))
    row = con.execute("select home_margin, seconds_remaining, naive_home_win_prob "
                      "from live.latest_game_state").fetchone()
    state = GameState.from_espn_event(snap(period=3, clock="5:30", home=74, away=70))
    assert row[0] == 4 and row[1] == state.seconds_remaining == 720 + 330
    assert row[2] == pytest.approx(naive_home_win_probability(4, state.seconds_remaining))
