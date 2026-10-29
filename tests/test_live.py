import copy

import pytest

from nba_pipeline import sample_data
from nba_pipeline.live import (
    GameState,
    LiveGameTracker,
    clock_seconds,
    diff_states,
    naive_home_win_probability,
)
from tests.conftest import load_fixture


def snap(state="in", period=1, clock="10:00", home=0, away=0, completed=False):
    ev = copy.deepcopy(sample_data.scoreboard_event(1, status="in_progress"))
    st = ev["competitions"][0]["status"]
    st["type"] = {"name": {"in": "STATUS_IN_PROGRESS", "pre": "STATUS_SCHEDULED", "post": "STATUS_FINAL"}[state],
                  "state": state, "completed": completed}
    st["period"], st["displayClock"] = period, clock
    for c in ev["competitions"][0]["competitors"]:
        c["score"] = str(home if c["homeAway"] == "home" else away)
    return ev


def kinds(events):
    return [e.event_type for e in events]


def test_clock_parsing():
    assert clock_seconds("5:32") == 332.0
    assert clock_seconds("12:00") == 720.0
    assert clock_seconds("44.6") == 44.6
    assert clock_seconds("") == 0.0 and clock_seconds("garbage") == 0.0


def test_state_from_real_espn_scoreboard():
    ev = load_fixture("espn_scoreboard_20261028.json.gz")["events"][0]
    s = GameState.from_espn_event(ev)
    assert (s.game_id, s.status, s.home_tricode, s.away_tricode) == ("401909881", 3, "ATL", "MIA")
    assert (s.home_score, s.away_score) == (117, 129) and s.leader == "MIA"


def test_first_live_snapshot_emits_game_started():
    assert kinds(LiveGameTracker().update(snap())) == ["game_started"]


def test_scheduled_game_emits_nothing_until_tipoff():
    t = LiveGameTracker()
    assert t.update(snap(state="pre", period=0, clock="0.0")) == []
    assert kinds(t.update(snap(period=1))) == ["game_started", "period_change"]


def test_unchanged_snapshot_emits_nothing():
    t = LiveGameTracker()
    t.update(snap(home=10, away=8))
    assert t.update(snap(home=10, away=8)) == []


def test_score_and_lead_change():
    t = LiveGameTracker()
    t.update(snap(home=10, away=8))
    ev = t.update(snap(home=10, away=11, clock="9:40"))
    assert kinds(ev) == ["score_change", "lead_change"]
    assert ev[0].detail == {"home_points": 0, "away_points": 3}
    assert ev[1].detail["margin"] == 1


def test_tie_is_not_a_lead_change():
    t = LiveGameTracker()
    t.update(snap(home=10, away=8))
    assert kinds(t.update(snap(home=10, away=10))) == ["score_change"]


def test_game_final():
    t = LiveGameTracker()
    t.update(snap(period=4, clock="0:05", home=101, away=99))
    ev = t.update(snap(state="post", completed=True, period=4, clock="0.0", home=101, away=99))
    assert kinds(ev) == ["game_final"]
    assert ev[0].detail["margin"] == 2


def test_event_ids_are_deterministic_and_distinct():
    prev = GameState.from_espn_event(snap(home=2, away=0))
    curr = GameState.from_espn_event(snap(home=2, away=3))
    a, b = diff_states(prev, curr), diff_states(prev, curr)
    assert [e.event_id for e in a] == [e.event_id for e in b]
    assert len({e.event_id for e in a}) == len(a)
    assert a[0].to_record()["event_id"] == a[0].event_id


def test_seconds_remaining():
    assert GameState.from_espn_event(snap(period=1, clock="12:00")).seconds_remaining == 48 * 60
    assert GameState.from_espn_event(snap(period=4, clock="1:30")).seconds_remaining == 90
    assert GameState.from_espn_event(snap(period=5, clock="3:00")).seconds_remaining == 0


@pytest.mark.parametrize("margin", [-10, -1, 1, 10])
def test_win_probability_behaves(margin):
    early = naive_home_win_probability(margin, 40 * 60)
    late = naive_home_win_probability(margin, 60)
    assert 0 < early < 1 and 0 < late < 1
    if margin > 0:
        assert late > early > 0.5   # a lead late in the game is worth more
    else:
        assert late < early


def test_win_probability_at_the_buzzer():
    assert naive_home_win_probability(3, 0) == 1.0
    assert naive_home_win_probability(-3, 0) == 0.0
    assert naive_home_win_probability(0, 48 * 60) > 0.5  # home edge
