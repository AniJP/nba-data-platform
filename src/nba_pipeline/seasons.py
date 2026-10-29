"""Season helpers for ESPN's NBA data.

ESPN labels a season by the year it *ends* (2026-27 is ``season.year == 2027``); this project
uses the start year everywhere (``--season 2026``) and the label ``"2026-27"`` in storage.
"""
from __future__ import annotations

from datetime import date, timedelta

# ESPN season.type: 1 preseason, 2 regular season, 3 postseason, 4 off-season, 5 play-in
INCLUDED_SEASON_TYPES = {2: "regular", 3: "postseason", 5: "play-in"}

# ESPN team ids 1-30 are the NBA franchises; All-Star and exhibition teams use other ids.
NBA_FRANCHISE_IDS = frozenset(str(i) for i in range(1, 31))


def season_label(season_start_year: int) -> str:
    """2026 -> '2026-27'"""
    return f"{season_start_year}-{(season_start_year + 1) % 100:02d}"


def espn_season_year(season_start_year: int) -> int:
    """2026 (2026-27) -> 2027, ESPN's convention."""
    return season_start_year + 1


def fallback_season_dates(season_start_year: int) -> list[str]:
    """Every day from Oct 1 to Jun 30, used when ESPN's calendar is unavailable for a season."""
    d, end = date(season_start_year, 10, 1), date(season_start_year + 1, 6, 30)
    days = []
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def to_espn_date(iso_day: str) -> str:
    """'2026-10-28' -> '20261028' (the scoreboard's ?dates= format)."""
    return iso_day.replace("-", "")
