"""Daily NBA pipeline: extract → load (bronze) → transform + test (dbt) → report.

Runs every morning after the previous night's games are final:

    snapshot_scoreboard ──────────────────────────┐
                                                  ├─► dbt_build ─► dbt_source_freshness ─► report_run
    backfill_boxscores ─► refresh_recent_games ───┘

* Ingestion is incremental and idempotent, so retries and backfills are safe.
* ``refresh_recent_games`` re-pulls the last 3 days so NBA stat corrections replace stale rows.
* Any task failure posts to a Slack/Discord webhook (``NBA_ALERT_WEBHOOK_URL``).
* ``dbt build`` runs snapshots, models, unit tests *and* data tests. A failing test fails the
  task, so bad data never silently reaches the marts.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

from nba_pipeline.alerts import airflow_failure_callback

PROJECT_DIR = os.environ.get("NBA_PROJECT_DIR", "/opt/nba")
DBT_DIR = f"{PROJECT_DIR}/transform"
DBT = os.environ.get("NBA_DBT_BIN", "dbt")
SEASON_START_YEAR = int(os.environ.get("NBA_SEASON_START_YEAR", "2026"))

default_args = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    "on_failure_callback": airflow_failure_callback,
}


@dag(
    dag_id="nba_daily_pipeline",
    description="Ingest NBA box scores & play-by-play, build and test the warehouse",
    schedule="15 11 * * *",  # 11:15 UTC ≈ 7:15 am ET, after West Coast games are final
    start_date=datetime(2026, 10, 20),
    catchup=False,
    max_active_runs=1,  # the watermark state file is not built for concurrent writers
    default_args=default_args,
    tags=["nba", "elt", "dbt"],
)
def nba_daily_pipeline():

    @task
    def snapshot_scoreboard() -> dict:
        from dataclasses import asdict

        from nba_pipeline.ingest import snapshot_scoreboard as run

        stats = run()
        if stats.status == "failed":
            raise RuntimeError(f"scoreboard snapshot failed: {stats.errors}")
        return asdict(stats)

    @task
    def backfill_boxscores() -> dict:
        from dataclasses import asdict

        from nba_pipeline.ingest import backfill_season

        stats = backfill_season(SEASON_START_YEAR)
        if stats.status == "failed":
            # Games that failed are not marked done, so the retry picks them up.
            raise RuntimeError(f"{len(stats.errors)} game(s) failed: {stats.errors[:5]}")
        return asdict(stats)

    @task
    def refresh_recent_games() -> dict:
        from dataclasses import asdict

        from nba_pipeline.ingest import refresh_recent_games as run

        stats = run(SEASON_START_YEAR, days=3)
        if stats.status == "failed":
            raise RuntimeError(f"refresh failed: {stats.errors[:5]}")
        return asdict(stats)

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {DBT_DIR} && {DBT} build --profiles-dir . --target dev",
    )

    dbt_source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        bash_command=f"cd {DBT_DIR} && {DBT} source freshness --profiles-dir . --target dev",
    )

    @task
    def report_run(scoreboard: dict, backfill: dict, refresh: dict) -> None:
        summary = {
            "games_loaded": backfill["games_written"],
            "stat_corrections": refresh["games_corrected"],
            "watermark": f"{backfill['watermark_before']} -> {backfill['watermark_after']}",
            "requests": backfill["requests"] + scoreboard["requests"] + refresh["requests"],
            "quarantined": backfill["quarantined"] + scoreboard["quarantined"],
            "todays_games": scoreboard["games_written"],
        }
        print("NBA pipeline run summary:", json.dumps(summary))

    sb, bf = snapshot_scoreboard(), backfill_boxscores()
    rf = refresh_recent_games()
    bf >> rf
    [sb, rf] >> dbt_build >> dbt_source_freshness
    dbt_source_freshness >> report_run(sb, bf, rf)


dag = nba_daily_pipeline()
