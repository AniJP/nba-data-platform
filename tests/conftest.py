from __future__ import annotations

import gzip
import json
from collections import defaultdict, deque
from pathlib import Path

import pytest
import requests

from nba_pipeline import sample_data
from nba_pipeline.client import EspnClient
from nba_pipeline.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with gzip.open(FIXTURES / name, "rt") as f:
        return json.load(f)


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Routes URLs to queued responses. A queue's last item repeats once the queue is drained."""

    def __init__(self):
        self.headers = {}
        self.routes: dict[str, deque] = defaultdict(deque)
        self.calls: list[str] = []
        self.default_status = 404

    def add(self, url: str, *responses):
        self.routes[url].extend(responses)

    def set(self, url: str, *responses):
        self.routes[url] = deque(responses)

    def get(self, url, timeout=None):
        self.calls.append(url)
        q = self.routes.get(url)
        if not q:
            if "/scoreboard?" in url:  # like ESPN: a day without games is an empty scoreboard
                return FakeResponse(200, {"leagues": [], "events": []})
            return FakeResponse(self.default_status)
        item = q.popleft() if len(q) > 1 else q[0]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", base_url="https://espn.test/nba",
                    min_request_interval=0.0, timeout_seconds=1, max_retries=2)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(settings, session) -> EspnClient:
    return EspnClient(settings, session=session, sleep=lambda s: None)


class FakeEspn:
    """A tiny fake ESPN: a season calendar, per-day scoreboards and per-game summaries."""

    def __init__(self, client: EspnClient, session: FakeSession):
        self.client, self.session = client, session
        self.days: dict[str, list[dict]] = defaultdict(list)
        self.calendar_days: list[str] = []

    def game(self, seq: int, status: str = "final", summary_override=None, summary_status: int = 200):
        """Put game ``seq`` on its date's scoreboard; serve its summary unless postponed."""
        day = sample_data.tipoff(seq).astimezone(_eastern()).date().isoformat()
        ev = sample_data.scoreboard_event(seq, status=status)
        self.days[day] = [e for e in self.days[day] if e["id"] != ev["id"]] + [ev]
        if day not in self.calendar_days:
            self.calendar_days.append(day)
        self._publish()
        if status != "postponed":
            body = summary_override if summary_override is not None else sample_data.summary(
                seq, status="final" if status == "final" else status)
            self.session.set(self.client.summary_url(ev["id"]), FakeResponse(summary_status, body))
        return ev["id"], day

    def _publish(self):
        cal = sorted(self.calendar_days)
        self.session.set(self.client.scoreboard_url("20261101"),
                         FakeResponse(200, sample_data.scoreboard([], calendar=cal)))
        for day, events in self.days.items():
            self.session.set(self.client.scoreboard_url(day.replace("-", "")),
                             FakeResponse(200, sample_data.scoreboard(events, calendar=cal)))


def _eastern():
    from zoneinfo import ZoneInfo
    return ZoneInfo("America/New_York")


@pytest.fixture
def espn(client, session) -> FakeEspn:
    return FakeEspn(client, session)


__all__ = ["FakeResponse", "FakeSession", "load_fixture", "requests"]
