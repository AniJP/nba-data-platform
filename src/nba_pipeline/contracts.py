"""Data contracts for ESPN payloads, plus the trimming applied before landing.

A payload is only accepted if the fields downstream models depend on are present. Anything else
is quarantined with the reason, so source-side schema drift fails loudly instead of silently
producing NULLs in the warehouse.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .seasons import INCLUDED_SEASON_TYPES, NBA_FRANCHISE_IDS


class ContractViolation(Exception):
    pass


def _get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx >= len(cur):
                raise ContractViolation(f"missing field: {path}")
            cur = cur[idx]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise ContractViolation(f"missing field: {path}")
    return cur


# --- summary (one game) ------------------------------------------------------
SUMMARY_REQUIRED = [
    "header.id",
    "header.season.year",
    "header.season.type",
    "header.competitions.0.date",
    "header.competitions.0.status.type.completed",
    "header.competitions.0.status.type.name",
    "header.competitions.0.competitors",
    "boxscore.players",
    "plays",
]
COMPETITOR_REQUIRED = ["id", "homeAway", "score", "team.abbreviation", "team.displayName", "linescores"]
PLAYER_STAT_KEYS_REQUIRED = [
    "minutes", "points", "rebounds", "assists", "steals", "blocks", "turnovers", "fouls",
    "offensiveRebounds", "defensiveRebounds", "plusMinus",
    "fieldGoalsMade-fieldGoalsAttempted",
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
    "freeThrowsMade-freeThrowsAttempted",
]
ATHLETE_REQUIRED = ["athlete.id", "athlete.displayName", "didNotPlay", "stats"]
PLAY_REQUIRED = ["id", "sequenceNumber", "period.number", "clock.displayValue", "type.text",
                 "homeScore", "awayScore"]


def validate_summary(payload: dict[str, Any], expected_event_id: str | None = None) -> None:
    for path in SUMMARY_REQUIRED:
        _get(payload, path)
    if expected_event_id and str(payload["header"]["id"]) != str(expected_event_id):
        raise ContractViolation(f"event id mismatch: expected {expected_event_id}, got {payload['header']['id']}")

    competitors = payload["header"]["competitions"][0]["competitors"]
    if sorted(c.get("homeAway") for c in competitors) != ["away", "home"]:
        raise ContractViolation("expected exactly one home and one away competitor")
    for c in competitors:
        for f in COMPETITOR_REQUIRED:
            _get(c, f)

    teams = payload["boxscore"]["players"]
    if len(teams) != 2:
        raise ContractViolation(f"expected 2 teams in boxscore.players, got {len(teams)}")
    for t in teams:
        _get(t, "team.id")
        block = _get(t, "statistics.0")
        keys = _get(block, "keys")
        missing = [k for k in PLAYER_STAT_KEYS_REQUIRED if k not in keys]
        if missing:
            raise ContractViolation(f"player stat keys missing: {missing}")
        athletes = _get(block, "athletes")
        if not athletes:
            raise ContractViolation(f"team {t['team']['id']} has no athletes")
        for a in athletes:
            for f in ATHLETE_REQUIRED:
                _get(a, f)
            if not a["didNotPlay"] and a["stats"] and len(a["stats"]) != len(keys):
                raise ContractViolation(f"athlete {a['athlete']['id']}: {len(a['stats'])} stats for {len(keys)} keys")

    plays = payload["plays"]
    if not plays:
        raise ContractViolation("no plays")
    for f in PLAY_REQUIRED:
        _get(plays[0], f)


def summary_is_final(payload: dict[str, Any]) -> bool:
    status = payload["header"]["competitions"][0]["status"]["type"]
    return bool(status.get("completed")) and status.get("name") == "STATUS_FINAL"


# Sections kept in bronze. The full summary also carries news, videos, odds and standings,
# which change constantly and are irrelevant here (and would make every re-fetch look "changed").
KEPT_SUMMARY_SECTIONS = ("header", "boxscore", "plays", "gameInfo", "winprobability", "format")


def trim_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: payload[k] for k in KEPT_SUMMARY_SECTIONS if k in payload}


def stats_digest(payload: dict[str, Any]) -> str:
    """Hash of only the game facts (scores, box score, plays). A change means a stat correction."""
    facts = {
        "competitors": [
            {k: c.get(k) for k in ("id", "score", "linescores", "winner")}
            for c in payload["header"]["competitions"][0]["competitors"]
        ],
        "boxscore": payload.get("boxscore"),
        "plays": payload.get("plays"),
    }
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- scoreboard (one day) ----------------------------------------------------
def validate_scoreboard(payload: dict[str, Any]) -> None:
    _get(payload, "events")
    for e in payload["events"]:
        for f in ("id", "date", "season.type", "competitions.0.status.type.state",
                  "competitions.0.status.type.name", "competitions.0.competitors"):
            _get(e, f)


def is_included_event(event: dict[str, Any]) -> bool:
    """Regular season, play-in and playoffs between two NBA franchises (no All-Star/exhibitions)."""
    if int(event["season"]["type"]) not in INCLUDED_SEASON_TYPES:
        return False
    team_ids = {str(c["team"]["id"]) for c in event["competitions"][0]["competitors"]}
    return len(team_ids) == 2 and team_ids <= NBA_FRANCHISE_IDS


def event_status(event: dict[str, Any]) -> str:
    """'final' | 'postponed' | 'canceled' | 'in_progress' | 'scheduled'"""
    t = event["competitions"][0]["status"]["type"]
    name = t.get("name", "")
    if name == "STATUS_POSTPONED":
        return "postponed"
    if name in ("STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_FORFEIT"):
        return "canceled"
    if t.get("state") == "post" and t.get("completed"):
        return "final"
    if t.get("state") == "in":
        return "in_progress"
    return "scheduled"
