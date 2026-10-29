"""Command-line entry point.

    nba-pipeline backfill --season 2026 [--max-games 50]
    nba-pipeline refresh --season 2026 [--days 3]
    nba-pipeline scoreboard
    nba-pipeline status
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict

from .config import Settings
from .ingest import backfill_season, refresh_recent_games, snapshot_scoreboard
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nba-pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    bf = sub.add_parser("backfill", help="incrementally ingest every final game of a season")
    bf.add_argument("--season", type=int, required=True, help="season start year, e.g. 2026 for 2026-27")
    bf.add_argument("--max-games", type=int, default=None, help="stop after N new games (for testing)")

    rf = sub.add_parser("refresh", help="re-pull recent games to pick up NBA stat corrections")
    rf.add_argument("--season", type=int, required=True)
    rf.add_argument("--days", type=int, default=3)

    sub.add_parser("scoreboard", help="snapshot today's scoreboard")
    sub.add_parser("status", help="print watermarks and the last runs")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()

    if args.command == "backfill":
        stats = backfill_season(args.season, settings=settings, max_new_games=args.max_games)
    elif args.command == "refresh":
        stats = refresh_recent_games(args.season, days=args.days, settings=settings)
    elif args.command == "scoreboard":
        stats = snapshot_scoreboard(settings=settings)
    else:
        state = StateStore(settings.state_file)._load_all()
        print(json.dumps(state, indent=2))
        if settings.run_log_file.exists():
            for line in settings.run_log_file.read_text().splitlines()[-5:]:
                print(line)
        return 0

    print(json.dumps(asdict(stats), indent=2))
    return 1 if stats.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
