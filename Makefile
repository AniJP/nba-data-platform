SEASON ?= 2026
export NBA_DATA_DIR ?= $(CURDIR)/data
export NBA_WAREHOUSE_PATH ?= $(CURDIR)/warehouse/nba.duckdb

.PHONY: setup test lint backfill refresh scoreboard status sample dbt-build dbt-docs dashboard airflow-up airflow-down stream-broker stream-produce stream-consume clean

setup:            ## install the package with dbt, dashboard, streaming and dev extras
	pip install -e ".[dev,transform,dashboard,streaming]"

test:             ## unit tests
	pytest --cov=nba_pipeline

lint:
	ruff check src tests orchestration streaming dashboard

backfill:         ## ingest all final games of the season not yet loaded (run from a home network)
	nba-pipeline backfill --season $(SEASON)

refresh:          ## re-pull the last 3 days to pick up NBA stat corrections
	nba-pipeline refresh --season $(SEASON) --days 3

scoreboard:       ## snapshot today's scoreboard
	nba-pipeline scoreboard

status:           ## watermarks + last runs
	nba-pipeline status

sample:           ## seed bronze with sample data (no network needed)
	nba-pipeline-sample --data-dir data --games 24

dbt-build:        ## build + test the warehouse
	mkdir -p warehouse && cd transform && dbt build --profiles-dir .

dbt-docs:         ## browse lineage graph + column docs at http://localhost:8081
	cd transform && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir . --port 8081

dashboard:        ## Streamlit dashboard at http://localhost:8501
	streamlit run dashboard/app.py

airflow-up:       ## local Airflow at http://localhost:8080 (credentials printed in the container logs)
	docker compose up --build -d && docker compose logs -f airflow | grep -m1 -i "password"

airflow-down:
	docker compose down

stream-broker:    ## start Redpanda (Kafka API on localhost:9092)
	docker compose --profile streaming up -d redpanda

stream-produce:   ## poll live games and publish events (run during games)
	python streaming/producer.py

stream-consume:   ## write events into warehouse/live.duckdb
	python streaming/consumer.py

clean:
	rm -rf transform/target transform/logs warehouse/*.duckdb
