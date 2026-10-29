"""Poll live games and publish change events to Redpanda/Kafka.

    docker compose --profile streaming up -d redpanda
    python streaming/producer.py            # runs until no games are live for 30 min

One scoreboard request per poll covers every game (score, period, clock). Each event is keyed by
game_id, so all events for a game land in one partition, in order.
"""
from __future__ import annotations

import json
import logging
import os
import time

from kafka import KafkaProducer

from nba_pipeline.client import Blocked, EspnClient, FetchError, NotAvailable
from nba_pipeline.live import LiveGameTracker

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC = os.environ.get("NBA_LIVE_TOPIC", "nba.live.events")
POLL_SECONDS = float(os.environ.get("NBA_LIVE_POLL_SECONDS", "20"))
IDLE_EXIT_MINUTES = float(os.environ.get("NBA_LIVE_IDLE_EXIT_MINUTES", "30"))

log = logging.getLogger("producer")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = EspnClient()
    tracker = LiveGameTracker()
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP,
        key_serializer=str.encode,
        value_serializer=lambda v: json.dumps(v).encode(),
        acks="all",            # wait for the broker to persist each event
        linger_ms=50,
    )
    idle_since = time.monotonic()
    sent = 0

    while True:
        try:
            events = client.scoreboard()["events"]
        except Blocked:
            log.error("ESPN is refusing requests (HTTP 401/403); stopping")
            raise
        except (NotAvailable, FetchError) as exc:
            log.warning("scoreboard unavailable: %s", exc)
            events = []

        states = [e["competitions"][0]["status"]["type"].get("state") for e in events]
        if "in" in states:
            idle_since = time.monotonic()

        for event in events:
            state = event["competitions"][0]["status"]["type"].get("state")
            # Track games while live, and one more poll after they end (to emit game_final).
            # Games that were already over when the producer started are skipped.
            if state == "pre" or (state == "post" and str(event["id"]) not in tracker.states):
                continue
            for change in tracker.update(event):
                producer.send(TOPIC, key=change.game_id, value=change.to_record())
                sent += 1
                log.info("%s %s %s-%s", change.event_type, change.game_id, change.home_score, change.away_score)
        producer.flush()

        if time.monotonic() - idle_since > IDLE_EXIT_MINUTES * 60:
            log.info("no live games for %.0f min, exiting (sent %d events)", IDLE_EXIT_MINUTES, sent)
            break
        time.sleep(POLL_SECONDS)

    producer.close()


if __name__ == "__main__":
    main()
