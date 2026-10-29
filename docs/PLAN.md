# Roadmap and status

All code for weeks 1–5 is written. The remaining items need your machine, your accounts or real data. They're what turn the repo into something you can talk about in interviews.

## Built
| Week | What | Where |
|---|---|---|
| 1 | Ingestion: client, watermark backfill, contracts, quarantine, run log, CLI | `src/nba_pipeline/` |
| 2 | dbt warehouse: staging, marts, incremental fact, SCD2 snapshot, trade-history stints, rolling form, 61 data tests and 2 unit tests | `transform/` |
| 3 | Stat-correction refresh, Slack/Discord failure alerts, pipeline-health models, Airflow DAG | `ingest.py`, `alerts.py`, `transform/models/ops/`, `orchestration/` |
| 4 | Streamlit dashboard, MotherDuck and S3 configuration, cloud guide | `dashboard/`, `transform/profiles.yml`, `docs/CLOUD.md` |
| 5 | Live streaming: change detection, Redpanda producer, idempotent DuckDB consumer, live win probability | `src/nba_pipeline/live.py`, `streaming/` |
| 6 | Source migration NBA.com → ESPN after the NBA CDN started refusing scripted traffic; explicit blocked/not-found failure classes; win-probability calibration mart | `docs/SOURCE_MIGRATION.md` |

## Your checklist

**First run (about 30 minutes)**
- [ ] `make setup && make test`
- [x] `make sample && make dbt-build`: all 67 nodes pass on sample data
- [ ] `make dashboard` to see the dashboard on sample data
- [x] Real-data probe: NBA.com is blocked, ESPN works, so the pipeline was migrated (see `docs/SOURCE_MIGRATION.md`)
- [ ] `rm -rf data warehouse && make sample && make dbt-build` to re-check everything on the new ESPN-format sample data
- [ ] `rm -rf data warehouse && nba-pipeline backfill --season 2026 --max-games 5`, then `make dbt-build`
- [ ] `make backfill && make dbt-build` for the whole season so far. Fix any failing data tests; they exist to catch real issues.

**GitHub**
- [ ] Push the repo and get CI green. CI is the first time dbt, the dashboard and the DAG run for real.
- [ ] Add screenshots to the README: dashboard tabs, the dbt lineage graph (`make dbt-docs`), the Airflow graph view

**Run it for real**
- [ ] `make airflow-up` and let the DAG run daily for a week. Set `NBA_ALERT_WEBHOOK_URL` to a Slack or Discord webhook.
- [ ] Run the streaming pipeline during one evening of games and screenshot `live.latest_game_state`
- [ ] Optional: move the warehouse to MotherDuck and deploy the dashboard on Streamlit Community Cloud (`docs/CLOUD.md`), then link the live dashboard in the README

## Resume bullets (fill in the real numbers)
- Built an end-to-end NBA data platform (Python, Airflow, dbt, DuckDB/MotherDuck) ingesting **X** games and **Y**K play-by-play events, with watermark-based idempotent loads, data contracts and quarantine for schema drift, and automatic re-processing of stat corrections
- Diagnosed a silent upstream failure (the source began returning HTTP 403 to all scripted traffic, which the old client counted as "no new games") and migrated the pipeline to a new API in a day, changing only the ingestion and staging layers; added explicit failure classification so a blocked source fails loudly
- Modeled an 18-model dbt warehouse with an incremental fact table, SCD2 snapshots, gaps-and-islands trade history and a win-probability calibration mart (Brier score, ESPN vs. baseline), enforced by 61 data tests and unit tests; built a Streamlit dashboard on top
- Added real-time ingestion of live games via Redpanda (Kafka) with at-least-once delivery and idempotent sinks, plus CI that builds and tests the full warehouse from synthetic data on every push

## Interview talking points
1. **Why a watermark, and why "contiguous"?** It makes loads idempotent and resumable, and it handles postponed games without skipping them.
2. **How do late corrections reach the marts?** Content hash → re-land with a new `ingested_at` → incremental `delete+insert`.
3. **Snapshot vs. gaps-and-islands for player history:** when the warehouse *observed* a change vs. when it *happened*.
4. **Exactly-once:** at-least-once delivery plus deterministic event IDs and primary-key dedupe.
5. **Testing without the API:** synthetic data proven to match real captured payloads, plus invariant tests that hold for any real game.
6. **The source migration:** how you noticed (zero rows reported as success), how you diagnosed it (probes ruling out "no games yet"), why the blast radius was small (source logic only in client and staging), and what you changed so it can't happen silently again.
