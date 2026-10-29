"""Consume live events from Redpanda/Kafka into DuckDB, with exactly-once *results*.

    python streaming/consumer.py

Delivery is at-least-once: offsets are committed only after a batch is written. Events carry a
deterministic ``event_id`` that is the table's primary key, so replays are ignored and the table
ends up as if every event arrived exactly once.

Writes go to a separate ``warehouse/live.duckdb`` so the streaming writer never contends with
dbt's lock on the batch warehouse.
"""
from __future__ import annotations

import json
import logging
import os

import duckdb
from kafka import KafkaConsumer

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.environ.get("NBA_LIVE_TOPIC", "nba.live.events")
LIVE_DB = os.environ.get("NBA_LIVE_DB_PATH", "warehouse/live.duckdb")
BATCH = int(os.environ.get("NBA_LIVE_BATCH", "200"))

log = logging.getLogger("consumer")

DDL = r"""
create schema if not exists live;
create table if not exists live.game_events (
    event_id     varchar primary key,
    event_type   varchar not null,
    game_id      varchar not null,
    period       integer,
    clock        varchar,
    home_score   integer,
    away_score   integer,
    detail       json,
    kafka_offset bigint,
    received_at  timestamptz default current_timestamp
);
create or replace view live.latest_game_state as
with latest as (
    select *,
           home_score - away_score as home_margin,
           case when period > 4 then 0
                else (4 - period) * 720
                     + case when clock like '%:%'                       -- ESPN clock: '5:32' or '44.6'
                            then try_cast(split_part(clock, ':', 1) as double) * 60
                                 + try_cast(split_part(clock, ':', 2) as double)
                            else coalesce(try_cast(clock as double), 0)
                       end
           end as seconds_remaining
    from live.game_events
    qualify row_number() over (partition by game_id order by received_at desc, kafka_offset desc) = 1
)
select
    game_id, period, clock, home_score, away_score, home_margin, seconds_remaining,
    event_type as last_event, received_at,
    -- same baseline as nba_pipeline.live.naive_home_win_probability
    case
        when event_type = 'game_final' or seconds_remaining <= 0
            then case when home_margin > 0 then 1.0 when home_margin < 0 then 0.0 else 0.5 end
        else 1 / (1 + exp(-(home_margin + 2.0 * (seconds_remaining / 60) / 48)
                          / (0.9 * sqrt(seconds_remaining / 60 + 1))))
    end as naive_home_win_prob
from latest;
"""


def write_batch(con: duckdb.DuckDBPyConnection, messages: list) -> int:
    rows = [
        (m.value["event_id"], m.value["event_type"], m.value["game_id"], m.value["period"],
         m.value["clock"], m.value["home_score"], m.value["away_score"],
         json.dumps(m.value.get("detail", {})), m.offset)
        for m in messages
    ]
    before = con.execute("select count(*) from live.game_events").fetchone()[0]
    con.executemany(
        "insert or ignore into live.game_events "
        "(event_id, event_type, game_id, period, clock, home_score, away_score, detail, kafka_offset) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return con.execute("select count(*) from live.game_events").fetchone()[0] - before


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(os.path.dirname(LIVE_DB) or ".", exist_ok=True)
    con = duckdb.connect(LIVE_DB)
    con.execute(DDL)

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP,
        group_id="nba-live-duckdb",
        enable_auto_commit=False,          # commit only after the batch is durable in DuckDB
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode()),
    )
    log.info("consuming %s -> %s", TOPIC, LIVE_DB)
    while True:
        polled = consumer.poll(timeout_ms=1000, max_records=BATCH)
        messages = [m for batch in polled.values() for m in batch]
        if not messages:
            continue
        inserted = write_batch(con, messages)
        consumer.commit()
        log.info("batch of %d events, %d new (%d duplicates ignored)",
                 len(messages), inserted, len(messages) - inserted)


if __name__ == "__main__":
    main()
