#!/usr/bin/env bash
# Mirror the local bronze layer and run log to S3 (only new/changed files are uploaded).
#   NBA_S3_URI=s3://my-bucket/nba ./scripts/sync_bronze_to_s3.sh
set -euo pipefail
: "${NBA_S3_URI:?set NBA_S3_URI, e.g. s3://my-bucket/nba}"
DATA_DIR="${NBA_DATA_DIR:-data}"
aws s3 sync "$DATA_DIR/bronze" "$NBA_S3_URI/bronze" --exclude "*/.tmp_*" --only-show-errors
aws s3 cp "$DATA_DIR/_state/run_log.jsonl" "$NBA_S3_URI/_state/run_log.jsonl" --only-show-errors
echo "synced $DATA_DIR -> $NBA_S3_URI"
