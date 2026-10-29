"""Pipeline state: per-season date watermark plus ingested-event set, and an append-only run log."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SeasonState:
    # Latest game date (ISO) such that it *and every earlier date* is settled: all its games are
    # either landed as final, or postponed/canceled. The next run starts the day after.
    settled_through: str | None = None
    # Every event landed so far. Lets a run skip finished games on a not-yet-settled date, and
    # catches up postponed games when they are replayed on a later date.
    ingested_events: list[str] = field(default_factory=list)

    def is_ingested(self, event_id: str) -> bool:
        return str(event_id) in self._ingested

    def mark_ingested(self, event_id: str) -> None:
        if not self.is_ingested(event_id):
            self.ingested_events.append(str(event_id))
            self._ingested.add(str(event_id))

    def __post_init__(self) -> None:
        self._ingested = set(map(str, self.ingested_events))


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def load(self, key: str) -> SeasonState:
        raw = self._load_all().get(key)
        if not raw:
            return SeasonState()
        return SeasonState(settled_through=raw.get("settled_through"),
                           ingested_events=list(raw.get("ingested_events", [])))

    def save(self, key: str, state: SeasonState) -> None:
        data = self._load_all()
        data[key] = {k: v for k, v in asdict(state).items() if not k.startswith("_")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tmp_state_")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)


def append_run_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
