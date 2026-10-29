"""HTTP client for ESPN's public NBA site API, with rate limiting, retries and explicit
classification of failures (blocked vs. not found vs. transient)."""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import requests

from .config import DEFAULT_HEADERS, Settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class NotAvailable(Exception):
    """404: the resource does not exist (yet)."""


class Blocked(Exception):
    """401/403: the source is refusing us. Never treated as 'no data'; this must fail loudly.

    (The original NBA-CDN pipeline counted 403s as "game not played yet", so a blocked source
    looked like a successful run with zero games. This exception exists so that can't recur.)
    """


class FetchError(Exception):
    """The request failed after all retries, or returned something unusable."""


class EspnClient:
    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or Settings()
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self.request_count = 0

    # --- endpoints ----------------------------------------------------------
    def scoreboard_url(self, espn_date: str | None = None) -> str:
        params = {"limit": 100}
        if espn_date:
            params["dates"] = espn_date
        return f"{self.settings.base_url}/scoreboard?{urlencode(params)}"

    def summary_url(self, event_id: str) -> str:
        return f"{self.settings.base_url}/summary?{urlencode({'event': event_id})}"

    def scoreboard(self, espn_date: str | None = None) -> dict[str, Any]:
        """Games on one day (``espn_date`` = 'YYYYMMDD'), or today's when omitted."""
        return self.get_json(self.scoreboard_url(espn_date))

    def summary(self, event_id: str) -> dict[str, Any]:
        """One game: header, box score, play-by-play, win probability, plus (unused) news/odds."""
        return self.get_json(self.summary_url(event_id))

    # --- core ---------------------------------------------------------------
    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self.settings.min_request_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def get_json(self, url: str) -> dict[str, Any]:
        last_error = ""
        for attempt in range(self.settings.max_retries + 1):
            self._throttle()
            self.request_count += 1
            try:
                resp = self.session.get(url, timeout=self.settings.timeout_seconds)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise FetchError(f"non-JSON 200 response from {url}") from exc
                if resp.status_code in (401, 403):
                    raise Blocked(f"HTTP {resp.status_code} from {url}")
                if resp.status_code == 404:
                    raise NotAvailable(url)
                if resp.status_code not in RETRYABLE_STATUS:
                    raise FetchError(f"HTTP {resp.status_code} from {url}")
                last_error = f"HTTP {resp.status_code}"

            if attempt < self.settings.max_retries:
                backoff = min(2 ** attempt, 30) + random.uniform(0, 0.5)  # exponential + jitter
                log.warning("retrying %s in %.1fs (%s)", url, backoff, last_error)
                self._sleep(backoff)

        raise FetchError(f"gave up on {url} after {self.settings.max_retries + 1} attempts: {last_error}")
