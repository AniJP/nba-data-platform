"""Failure alerting via a chat webhook (Slack- or Discord-compatible).

Set ``NBA_ALERT_WEBHOOK_URL`` to a Slack incoming-webhook or Discord webhook URL. Without it,
alerts are only logged, so local runs never fail because of alerting.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)


def send_alert(text: str, webhook_url: str | None = None, session: Any = None) -> bool:
    url = webhook_url or os.environ.get("NBA_ALERT_WEBHOOK_URL")
    log.error("ALERT: %s", text)
    if not url:
        return False
    try:
        # "text" is read by Slack, "content" by Discord; each ignores the other key.
        resp = (session or requests).post(url, json={"text": text, "content": text}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:  # alerting must never mask the original failure
        log.warning("could not deliver alert: %s", exc)
        return False


def format_airflow_failure(context: dict[str, Any]) -> str:
    ti = context.get("ti") or context.get("task_instance")
    dag_id = getattr(ti, "dag_id", None) or getattr(context.get("dag"), "dag_id", "unknown_dag")
    task_id = getattr(ti, "task_id", "unknown_task")
    run_id = getattr(context.get("dag_run"), "run_id", None) or context.get("run_id", "unknown_run")
    try_number = getattr(ti, "try_number", "?")
    exc = context.get("exception")
    lines = [
        f":rotating_light: *{dag_id}.{task_id}* failed (try {try_number})",
        f"run: `{run_id}`",
    ]
    if exc:
        lines.append(f"error: `{str(exc)[:500]}`")
    if getattr(ti, "log_url", None):
        lines.append(f"logs: {ti.log_url}")
    return "\n".join(lines)


def airflow_failure_callback(context: dict[str, Any]) -> None:
    """Use as ``on_failure_callback`` in a DAG's ``default_args``."""
    send_alert(format_airflow_failure(context))
