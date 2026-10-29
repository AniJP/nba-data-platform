"""Live-game change detection: turn successive scoreboard snapshots into a stream of events.

Pure functions (no I/O) so the streaming logic is unit-tested. ``streaming/producer.py`` and
``streaming/consumer.py`` wrap them with Kafka/Redpanda and DuckDB.

Event types: ``game_started``, ``score_change``, ``lead_change``, ``period_change``, ``game_final``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

_CLOCK_RE = re.compile(r"(?:(\d+):)?(\d+(?:\.\d+)?)")


def clock_seconds(clock: str | None) -> float:
    """ESPN display clock -> seconds left in the period: '5:32' -> 332.0, '44.6' -> 44.6"""
    if not clock:
        return 0.0
    m = _CLOCK_RE.fullmatch(clock.strip())
    if not m:
        return 0.0
    return int(m.group(1) or 0) * 60 + float(m.group(2))


@dataclass(frozen=True)
class GameState:
    game_id: str
    status: int
    period: int
    clock: str
    home_tricode: str
    away_tricode: str
    home_score: int
    away_score: int

    @classmethod
    def from_espn_event(cls, event: dict[str, Any]) -> GameState:
        """Build from one entry of ESPN's scoreboard ``events`` list."""
        comp = event["competitions"][0]
        st = comp["status"]
        state = st["type"].get("state")
        status = 3 if state == "post" and st["type"].get("completed") else 2 if state == "in" else 1
        side = {c["homeAway"]: c for c in comp["competitors"]}
        return cls(
            game_id=str(event["id"]),
            status=status,
            period=int(st.get("period") or 0) if status > 1 else 0,
            clock=str(st.get("displayClock") or ""),
            home_tricode=side["home"]["team"]["abbreviation"],
            away_tricode=side["away"]["team"]["abbreviation"],
            home_score=int(side["home"].get("score") or 0),
            away_score=int(side["away"].get("score") or 0),
        )

    @property
    def margin(self) -> int:
        return self.home_score - self.away_score

    @property
    def leader(self) -> str | None:
        return None if self.margin == 0 else (self.home_tricode if self.margin > 0 else self.away_tricode)

    @property
    def seconds_remaining(self) -> float:
        """Regulation seconds left (overtime periods count as 0)."""
        if self.status == 3:
            return 0.0
        if self.period == 0:
            return 48 * 60.0
        left_in_period = clock_seconds(self.clock)
        return max(0.0, (4 - self.period) * 12 * 60 + left_in_period) if self.period <= 4 else 0.0


@dataclass
class LiveEvent:
    event_type: str
    game_id: str
    period: int
    clock: str
    home_score: int
    away_score: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        """Deterministic id: replaying the same snapshot yields the same id, so sinks can dedupe."""
        key = json.dumps([self.event_type, self.game_id, self.period, self.clock, self.home_score,
                          self.away_score, self.detail], sort_keys=True)
        return hashlib.sha1(key.encode()).hexdigest()[:20]

    def to_record(self) -> dict[str, Any]:
        return {"event_id": self.event_id, **asdict(self)}


def diff_states(prev: GameState | None, curr: GameState) -> list[LiveEvent]:
    def ev(kind: str, **detail) -> LiveEvent:
        return LiveEvent(kind, curr.game_id, curr.period, curr.clock, curr.home_score, curr.away_score, detail)

    events: list[LiveEvent] = []
    if prev is None:
        if curr.status >= 2:
            events.append(ev("game_started"))
        return events
    if prev.status < 2 <= curr.status:
        events.append(ev("game_started"))
    if curr.period != prev.period and curr.period > 0:
        events.append(ev("period_change", from_period=prev.period, to_period=curr.period))
    if (curr.home_score, curr.away_score) != (prev.home_score, prev.away_score):
        events.append(ev("score_change",
                         home_points=curr.home_score - prev.home_score,
                         away_points=curr.away_score - prev.away_score))
        if curr.leader and prev.leader and curr.leader != prev.leader:
            events.append(ev("lead_change", new_leader=curr.leader, margin=abs(curr.margin)))
    if prev.status != 3 and curr.status == 3:
        winner = curr.home_tricode if curr.margin > 0 else curr.away_tricode
        events.append(ev("game_final", winner=winner, margin=abs(curr.margin)))
    return events


class LiveGameTracker:
    """Keeps the last state per game; ``update`` returns only what changed since last poll."""

    def __init__(self) -> None:
        self.states: dict[str, GameState] = {}

    def update(self, event: dict[str, Any]) -> list[LiveEvent]:
        curr = GameState.from_espn_event(event)
        events = diff_states(self.states.get(curr.game_id), curr)
        self.states[curr.game_id] = curr
        return events


def naive_home_win_probability(margin: int, seconds_remaining: float, home_edge: float = 2.0) -> float:
    """A deliberately simple baseline: logistic in margin, scaled by sqrt(time left).

    As time runs out, a fixed lead becomes more decisive. Good enough to demo live features;
    a proper model would be trained on historical play-by-play (see the data science project).
    """
    if seconds_remaining <= 0:
        return 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
    minutes_left = seconds_remaining / 60.0
    z = (margin + home_edge * minutes_left / 48.0) / (0.9 * math.sqrt(minutes_left + 1.0))
    return 1.0 / (1.0 + math.exp(-z))
