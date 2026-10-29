# Running in the cloud

The pipeline runs locally by default (bronze on disk, DuckDB file). Going to the cloud needs no
code changes, only configuration.

## 1. Warehouse → MotherDuck
1. Create a free account at motherduck.com and copy a token.
2. `export MOTHERDUCK_TOKEN=... NBA_DBT_TARGET=motherduck`
3. `make dbt-build` builds the same models and tests in `md:nba`.
4. Dashboard: `NBA_WAREHOUSE_PATH=md:nba make dashboard`

## 2. Bronze → S3
1. Create a bucket and configure AWS credentials (`aws configure` or an IAM role).
2. After each ingestion run: `NBA_S3_URI=s3://<bucket>/nba ./scripts/sync_bronze_to_s3.sh`
3. Point dbt at it: `export NBA_DATA_DIR=s3://<bucket>/nba` (the `motherduck` target loads
   `httpfs` and an S3 secret from the AWS credential chain).

The watermark state (`data/_state/watermarks.json`) stays with the ingestion worker, which is the
only writer.

## 3. Where should ingestion run?
ESPN's API has been reported to answer from cloud servers (several projects run it on Vercel and GitHub Actions), so the whole stack can live in the cloud. Check from the target machine first:
```bash
curl -s -o /dev/null -w "%{http_code}\n" "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"   # 200 = OK
```
- **200:** run the Airflow stack there (`docker compose up -d`), or schedule `nba-pipeline backfill` from a cron or a GitHub Actions workflow and sync bronze to S3.
- **Blocked:** keep ingestion on a home machine that syncs bronze to S3, and run dbt plus the dashboard in the cloud. The pipeline reports a block as a failed run, so you'll know.

## 4. Dashboard hosting
Streamlit Community Cloud (free): connect the GitHub repo, set `NBA_WAREHOUSE_PATH=md:nba` and
`MOTHERDUCK_TOKEN` as app secrets, and set the main file to `dashboard/app.py`.

## At larger scale
| Concern | Today | At scale |
|---|---|---|
| Storage | gzipped JSON | Parquet/Iceberg tables in object storage, partitioned by date |
| Warehouse | DuckDB / MotherDuck | Snowflake / BigQuery, same dbt models with an adapter swap |
| State | JSON watermark file | Watermark table in the warehouse, or orchestrator-managed partitions |
| Orchestration | Airflow standalone | Managed Airflow (MWAA / Cloud Composer / Astronomer), Postgres metadata DB, Celery/K8s executors |
| Quality | dbt tests + contracts | Plus anomaly detection on volumes and distributions, data-observability tooling |
| Concurrency | `max_active_runs=1` | Partition-level locking, so backfills and daily runs can run in parallel |
