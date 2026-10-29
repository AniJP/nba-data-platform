"""Bronze-layer storage: raw payloads as gzipped JSON, Hive-style partitioned, written atomically.

Layout::

    data/bronze/summary/season=2026-27/event_id=401909881.json.gz     (one game: box score + plays)
    data/bronze/scoreboard/snapshot_date=2026-10-28/scoreboard_20261028T100000Z.json.gz

Each file is an envelope ``{"_meta": {...lineage...}, "payload": <raw response>}`` so every row in
the warehouse can be traced back to the exact request that produced it.
"""
from __future__ import annotations

import gzip
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def envelope(payload: dict[str, Any], source_url: str, run_id: str, ingested_at: datetime | None = None) -> dict:
    return {
        "_meta": {
            "source_url": source_url,
            "run_id": run_id,
            "ingested_at": (ingested_at or utcnow()).isoformat(),
            "schema_version": SCHEMA_VERSION,
        },
        "payload": payload,
    }


def atomic_write_json_gz(path: Path, obj: dict[str, Any]) -> None:
    """Write to a temp file in the same directory, then rename: readers never see partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json.gz")
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_json_gz(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt") as f:
        return json.load(f)


def game_path(bronze_dir: Path, entity: str, season: str, event_id: str) -> Path:
    return bronze_dir / entity / f"season={season}" / f"event_id={event_id}.json.gz"


def scoreboard_path(bronze_dir: Path, ts: datetime) -> Path:
    return (
        bronze_dir / "scoreboard" / f"snapshot_date={ts:%Y-%m-%d}" / f"scoreboard_{ts:%Y%m%dT%H%M%SZ}.json.gz"
    )


def quarantine_path(quarantine_dir: Path, entity: str, key: str, ts: datetime) -> Path:
    return quarantine_dir / entity / f"{key}_{ts:%Y%m%dT%H%M%SZ}.json.gz"

