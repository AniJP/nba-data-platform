import copy

import pytest

from nba_pipeline import sample_data
from nba_pipeline.contracts import (
    ContractViolation,
    event_status,
    is_included_event,
    stats_digest,
    summary_is_final,
    trim_summary,
    validate_scoreboard,
    validate_summary,
)
from nba_pipeline.storage import atomic_write_json_gz, read_json_gz
from tests.conftest import load_fixture

REAL_SUMMARY = "espn_summary_401909881.json.gz"
REAL_SCOREBOARD = "espn_scoreboard_20261028.json.gz"


def test_atomic_write_roundtrip_and_no_temp_files(tmp_path):
    p = tmp_path / "a" / "b.json.gz"
    atomic_write_json_gz(p, {"x": 1})
    assert read_json_gz(p) == {"x": 1}
    assert [f.name for f in p.parent.iterdir()] == ["b.json.gz"]


def test_atomic_write_is_deterministic(tmp_path):
    a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    atomic_write_json_gz(a, {"k": [1, 2], "z": "y"})
    atomic_write_json_gz(b, {"z": "y", "k": [1, 2]})
    assert a.read_bytes() == b.read_bytes()


# --- the real ESPN payloads captured from the live API ---------------------------------
def test_real_summary_satisfies_contract():
    s = load_fixture(REAL_SUMMARY)
    validate_summary(s, expected_event_id="401909881")
    assert summary_is_final(s)


def test_real_summary_scores_are_consistent():
    s = load_fixture(REAL_SUMMARY)
    comps = {c["id"]: int(c["score"]) for c in s["header"]["competitions"][0]["competitors"]}
    for team in s["boxscore"]["players"]:
        block = team["statistics"][0]
        i = block["keys"].index("points")
        pts = sum(int(a["stats"][i]) for a in block["athletes"] if a["stats"])
        assert pts == comps[team["team"]["id"]]


def test_real_scoreboard():
    sb = load_fixture(REAL_SCOREBOARD)
    validate_scoreboard(sb)
    assert len(sb["events"]) == 12
    assert all(is_included_event(e) and event_status(e) == "final" for e in sb["events"])
    assert sb["leagues"][0]["season"]["year"] == 2027


def test_sample_payloads_mirror_the_real_structure():
    real, fake = load_fixture(REAL_SUMMARY), sample_data.summary(1)
    validate_summary(fake, expected_event_id=fake["header"]["id"])
    assert fake["boxscore"]["players"][0]["statistics"][0]["keys"] == \
        real["boxscore"]["players"][0]["statistics"][0]["keys"]
    real_play_keys = set().union(*(p.keys() for p in real["plays"]))
    assert set().union(*(p.keys() for p in fake["plays"])) <= real_play_keys


def test_sample_scores_are_consistent():
    for seq in range(1, 30):
        s = sample_data.summary(seq)
        comps = s["header"]["competitions"][0]["competitors"]
        assert comps[0]["score"] != comps[1]["score"]
        for c in comps:
            assert int(c["score"]) == sum(int(q["displayValue"]) for q in c["linescores"])


# --- contract failures ----------------------------------------------------------------
def test_contract_rejects_missing_stat_key_and_id_mismatch():
    s = sample_data.summary(1)
    with pytest.raises(ContractViolation, match="mismatch"):
        validate_summary(s, expected_event_id="1")
    s["boxscore"]["players"][1]["statistics"][0]["keys"].remove("assists")
    with pytest.raises(ContractViolation, match="assists"):
        validate_summary(s)


def test_contract_rejects_misaligned_stats():
    s = sample_data.summary(1)
    s["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"].pop()
    with pytest.raises(ContractViolation, match="stats for"):
        validate_summary(s)


def test_trim_and_digest():
    s = load_fixture(REAL_SUMMARY)
    noisy = copy.deepcopy(s)
    noisy["news"] = {"articles": ["changes every hour"]}
    noisy["header"]["timeValid"] = not noisy["header"].get("timeValid")
    assert stats_digest(noisy) == stats_digest(s)  # volatile extras don't count as corrections
    assert set(trim_summary(noisy)) == {"header", "boxscore", "plays", "gameInfo", "winprobability", "format"}
    corrected = copy.deepcopy(s)
    corrected["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["stats"][6] = "99"
    assert stats_digest(corrected) != stats_digest(s)


def test_event_status_mapping():
    ev = sample_data.scoreboard_event(1)
    assert event_status(ev) == "final"
    assert event_status(sample_data.scoreboard_event(1, status="postponed")) == "postponed"
    assert event_status(sample_data.scoreboard_event(1, status="in_progress")) == "in_progress"
    assert event_status(sample_data.scoreboard_event(1, status="scheduled")) == "scheduled"
