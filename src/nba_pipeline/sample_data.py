"""Deterministic sample payloads in ESPN's exact format.

Used by the unit tests and by ``nba-pipeline-sample`` to seed a bronze layer for CI, so the dbt
models can be built and tested on GitHub Actions without network access. The structure mirrors a
real ESPN game summary (see ``tests/fixtures/``, captured from the live API on 2026-10-29).
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# (ESPN team id, abbreviation, location, name)
TEAMS = [
    ("13", "LAL", "Los Angeles", "Lakers"),
    ("9", "GS", "Golden State", "Warriors"),
    ("2", "BOS", "Boston", "Celtics"),
    ("18", "NY", "New York", "Knicks"),
]
STAT_KEYS = [
    "minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted",
    "rebounds", "assists", "turnovers", "steals", "blocks", "offensiveRebounds",
    "defensiveRebounds", "fouls", "plusMinus",
]
STAT_NAMES = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]
NO_COORD = {"x": -214748340, "y": -214748365}  # ESPN's sentinel for plays without a location
FIRST_EVENT_ID = 401900001


def event_id(seq: int) -> str:
    return str(FIRST_EVENT_ID + seq - 1)


def tipoff(seq: int) -> datetime:
    """Six games per day starting 2026-10-21, tipping off 23:30 UTC."""
    return datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc) + timedelta(days=(seq - 1) // 6)


def _player_lines(rng: random.Random, team_id: str, n: int = 10) -> list[dict]:
    lines = []
    for i in range(n):
        pid = f"{int(team_id) * 1000 + i + 1}"
        athlete = {"id": pid, "displayName": f"Player {pid}", "shortName": f"P. {pid}",
                   "jersey": str(i + 1), "position": {"abbreviation": rng.choice(["G", "F", "C"])}}
        if i == n - 1:  # one DNP per team
            lines.append({"active": False, "athlete": athlete, "starter": False, "didNotPlay": True,
                          "reason": "COACH'S DECISION", "ejected": False, "stats": []})
            continue
        starter = i < 5
        fga = rng.randint(5, 20) if starter else rng.randint(0, 9)
        fgm = rng.randint(0, fga)
        tpa = rng.randint(0, min(fga, 10))
        tpm = rng.randint(0, min(tpa, fgm))
        fta = rng.randint(0, 8)
        ftm = rng.randint(0, fta)
        oreb, dreb = rng.randint(0, 3), rng.randint(0, 9)
        pts = 2 * (fgm - tpm) + 3 * tpm + ftm
        stats = [
            str(rng.randint(26, 40) if starter else rng.randint(5, 24)), str(pts),
            f"{fgm}-{fga}", f"{tpm}-{tpa}", f"{ftm}-{fta}", str(oreb + dreb),
            str(rng.randint(0, 10)), str(rng.randint(0, 5)), str(rng.randint(0, 3)), str(rng.randint(0, 3)),
            str(oreb), str(dreb), str(rng.randint(0, 5)), f"{rng.randint(-15, 15):+d}",
        ]
        lines.append({"active": True, "athlete": athlete, "starter": starter, "didNotPlay": False,
                      "reason": "", "ejected": False, "stats": stats})
    return lines


def _points(line: dict) -> int:
    return int(line["stats"][1]) if line["stats"] else 0


def summary(seq: int, status: str = "final", seed: int | None = None) -> dict:
    """One game summary. status: final | in_progress | scheduled."""
    rng = random.Random(seed if seed is not None else seq)
    home, away = rng.sample(TEAMS, 2)
    lines = {home[0]: _player_lines(rng, home[0]), away[0]: _player_lines(rng, away[0])}
    score = {tid: sum(_points(a) for a in ls) for tid, ls in lines.items()}
    if score[home[0]] == score[away[0]]:  # no ties in the NBA: give the home starter a free throw
        a = lines[home[0]][0]["stats"]
        m, att = map(int, a[4].split("-"))
        a[4], a[1] = f"{m + 1}-{att + 1}", str(int(a[1]) + 1)
        score[home[0]] += 1

    def quarters(total: int) -> list[dict]:
        q = [total // 4] * 4
        q[3] += total - sum(q)
        return [{"displayValue": str(v)} for v in q]

    def competitor(team: tuple, side: str) -> dict:
        tid = team[0]
        opp = away[0] if side == "home" else home[0]
        return {"id": tid, "homeAway": side, "winner": score[tid] > score[opp] if status == "final" else False,
                "score": str(score[tid]), "linescores": quarters(score[tid]),
                "team": {"id": tid, "abbreviation": team[1], "location": team[2], "name": team[3],
                         "displayName": f"{team[2]} {team[3]}"}}

    state_name, state, completed = {"final": ("STATUS_FINAL", "post", True),
                                    "in_progress": ("STATUS_IN_PROGRESS", "in", False),
                                    "scheduled": ("STATUS_SCHEDULED", "pre", False)}[status]
    eid = event_id(seq)
    tip = tipoff(seq)

    plays, n, hs, as_ = [], 0, 0, 0
    for tid in (home[0], away[0]):
        for a in lines[tid][:4]:
            n += 1
            made = _points(a) > 0
            three = n % 3 == 0
            pts = 3 if three else 2
            if made:
                if tid == home[0]:
                    hs += pts
                else:
                    as_ += pts
            dist = 24 if three else 3 + n
            angle = (n * 37) % 180
            plays.append({
                "id": f"{eid}{n:04d}", "sequenceNumber": str(n * 3),
                "type": {"id": "92", "text": "Jump Shot" if three else "Driving Layup Shot"},
                "text": f"{a['athlete']['displayName']} {'makes' if made else 'misses'} shot",
                "homeScore": hs, "awayScore": as_,
                "period": {"number": 1 + (n - 1) % 4, "displayValue": "Quarter"},
                "clock": {"displayValue": f"{11 - n % 11}:{(n * 7) % 60:02d}"},
                "scoringPlay": made, "scoreValue": pts if made else 0, "team": {"id": tid},
                "participants": [{"athlete": {"id": a["athlete"]["id"]}}],
                "wallclock": (tip + timedelta(minutes=n * 5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "shootingPlay": True, "pointsAttempted": pts,
                "coordinate": {"x": round(25 + dist * math.cos(math.radians(angle))),
                               "y": round(dist * math.sin(math.radians(angle)))},
                "shortDescription": f"+{pts} Points" if made else "Missed Shot",
            })
    n += 1
    plays.append({"id": f"{eid}{n:04d}", "sequenceNumber": str(n * 3), "type": {"id": "412", "text": "End Period"},
                  "text": "End of Game", "homeScore": hs, "awayScore": as_,
                  "period": {"number": 4, "displayValue": "4th Quarter"}, "clock": {"displayValue": "0.0"},
                  "scoringPlay": False, "scoreValue": 0, "shootingPlay": False, "pointsAttempted": 0,
                  "coordinate": NO_COORD, "wallclock": (tip + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")})

    def box_team(team: tuple) -> dict:
        return {"team": {"id": team[0], "abbreviation": team[1], "displayName": f"{team[2]} {team[3]}"},
                "statistics": [{"names": list(STAT_NAMES), "keys": list(STAT_KEYS), "labels": list(STAT_NAMES),
                                "athletes": lines[team[0]], "totals": []}]}

    return {
        "header": {
            "id": eid,
            "season": {"year": 2027, "type": 2},
            "competitions": [{
                "id": eid, "date": tip.strftime("%Y-%m-%dT%H:%MZ"),
                "status": {"type": {"id": "3", "name": state_name, "state": state, "completed": completed}},
                "competitors": [competitor(home, "home"), competitor(away, "away")],
            }],
        },
        "boxscore": {"teams": [], "players": [box_team(away), box_team(home)]},
        "plays": plays,
        "gameInfo": {"venue": {"fullName": f"{home[3]} Arena"}, "attendance": rng.randint(15000, 20000)},
        "winprobability": [
            {"playId": p["id"], "tiePercentage": 0.0,
             "homeWinPercentage": round(min(0.99, max(0.01, 0.5 + (p["homeScore"] - p["awayScore"]) / 40)), 3)}
            for p in plays
        ],
        "format": {"regulation": {"periods": 4}},
        # sections the pipeline trims before landing (present in real responses)
        "news": {"articles": [{"headline": "volatile"}]},
        "odds": [{"provider": "volatile"}],
    }


def scoreboard_event(seq: int, status: str = "final", season_type: int = 2) -> dict:
    """The scoreboard entry for game ``seq`` (same teams and score as ``summary(seq)``)."""
    s = summary(seq, status="scheduled" if status == "postponed" else status)
    comp = s["header"]["competitions"][0]
    if status == "postponed":
        comp["status"]["type"] = {"id": "6", "name": "STATUS_POSTPONED", "state": "post", "completed": False}
    status_block = dict(comp["status"])
    status_block.update({"period": 4 if status == "final" else 2 if status == "in_progress" else 0,
                         "displayClock": "0.0" if status == "final" else "6:12" if status == "in_progress" else "0.0"})
    return {"id": s["header"]["id"], "date": comp["date"], "season": {"year": 2027, "type": season_type},
            "competitions": [{"status": status_block, "competitors": comp["competitors"]}]}


def scoreboard(events: list[dict], calendar: list[str] | None = None, season_year: int = 2027) -> dict:
    league = {"season": {"year": season_year}, "calendar": [f"{d}T07:00Z" for d in (calendar or [])]}
    return {"leagues": [league], "events": events}


def write_sample_bronze(data_dir: Path, season_start_year: int = 2026, n_games: int = 12) -> int:
    """Seed ``data_dir/bronze`` with sample final games (for CI / local dbt development)."""
    from .contracts import trim_summary
    from .seasons import season_label
    from .storage import atomic_write_json_gz, envelope, game_path

    season = season_label(season_start_year)
    for seq in range(1, n_games + 1):
        s = summary(seq)
        atomic_write_json_gz(game_path(data_dir / "bronze", "summary", season, s["header"]["id"]),
                             envelope(trim_summary(s), "sample://summary", "sample"))
    _write_sample_run_log(data_dir, season)
    return n_games


def _write_sample_run_log(data_dir: Path, season: str) -> None:
    """A few days of plausible run-log records so the ops models have data in CI."""
    from .state import append_run_log

    log_file = data_dir / "_state" / "run_log.jsonl"
    if log_file.exists() and "sample-0-" in log_file.read_text():
        return  # already seeded
    start = datetime(2026, 10, 21, 11, 15, tzinfo=timezone.utc)
    for day in range(5):
        ts = start + timedelta(days=day)
        failed = day == 2
        for job, games, reqs in (("snapshot_scoreboard", 6, 1), ("backfill_season", 0 if failed else 6, 8)):
            append_run_log(log_file, {
                "run_id": f"sample-{day}-{job}", "job": job,
                "season": season if job == "backfill_season" else None,
                "started_at": ts.isoformat(), "finished_at": (ts + timedelta(seconds=10 + day)).isoformat(),
                "duration_s": 10.0 + day, "requests": reqs, "dates_scanned": 1 if job == "backfill_season" else 0,
                "games_written": games, "not_final": 0, "postponed": 0, "not_available": 0, "quarantined": 0,
                "games_checked": 0, "games_corrected": 0,
                "errors": ["FetchError: HTTP 503 from sample"] if failed and job == "backfill_season" else [],
                "watermark_before": None, "watermark_after": None,
                "status": "failed" if failed and job == "backfill_season" else "success",
            })


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Write sample bronze data for local/CI dbt runs")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--games", type=int, default=12)
    a = ap.parse_args()
    n = write_sample_bronze(Path(a.data_dir), n_games=a.games)
    print(f"wrote {n} sample games to {a.data_dir}/bronze")


if __name__ == "__main__":
    main()
