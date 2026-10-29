FROM apache/airflow:3.3.1-python3.12

USER airflow

# dbt lives in its own virtualenv so its dependencies can't conflict with Airflow's pinned ones.
RUN python -m venv /opt/dbt-venv \
 && /opt/dbt-venv/bin/pip install --no-cache-dir "dbt-core>=1.10.5,<2.0" "dbt-duckdb>=1.9.2"

# The ingestion package only needs `requests` (already in the Airflow image).
# The source is bind-mounted at /opt/nba/src by docker-compose, so edits apply without a rebuild.
COPY --chown=airflow:root pyproject.toml /opt/nba/pyproject.toml
COPY --chown=airflow:root src /opt/nba/src
RUN pip install --no-cache-dir --no-deps -e /opt/nba

ENV NBA_DBT_BIN=/opt/dbt-venv/bin/dbt
