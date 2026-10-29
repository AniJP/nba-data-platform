"""Runtime configuration, read from environment variables with sensible defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ESPN's public site API. NBA.com's own CDN (cdn.nba.com) started answering 403 to scripted
# requests on every network in mid-2026, so the platform migrated here (see docs/SOURCE_MIGRATION.md).
ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

DEFAULT_HEADERS = {
    "User-Agent": "nba-data-platform/0.2 (portfolio project; +https://github.com/AniJP)",
    "Accept": "application/json",
}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("NBA_DATA_DIR", "data")))
    base_url: str = field(default_factory=lambda: os.environ.get("NBA_API_BASE_URL", ESPN_BASE_URL))
    # Minimum seconds between requests: be a polite client of a free public API.
    min_request_interval: float = field(
        default_factory=lambda: float(os.environ.get("NBA_MIN_REQUEST_INTERVAL", "0.5"))
    )
    timeout_seconds: float = field(default_factory=lambda: float(os.environ.get("NBA_TIMEOUT_SECONDS", "20")))
    max_retries: int = field(default_factory=lambda: int(os.environ.get("NBA_MAX_RETRIES", "4")))

    @property
    def bronze_dir(self) -> Path:
        return self.data_dir / "bronze"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "bronze" / "_quarantine"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "_state" / "watermarks.json"

    @property
    def run_log_file(self) -> Path:
        return self.data_dir / "_state" / "run_log.jsonl"
