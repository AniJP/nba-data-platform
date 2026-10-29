# Incident write-up: migrating the source from NBA.com to ESPN

**Date:** 2026-10-29 · **Impact:** no data could be ingested · **Status:** resolved

## What happened
The first real backfill reported `status: success` with **0 games written**: all 15 requests were classed as "game not available yet".

## Diagnosis
| Probe (from a residential connection) | Result |
|---|---|
| `cdn.nba.com` scoreboard, plain user agent | 403 |
| `cdn.nba.com` box score from last season (a game that certainly exists) | 403 |
| `cdn.nba.com` with full Firefox browser headers + Referer | 403 |
| `stats.nba.com` box score endpoint with browser headers | no response (timeout) |
| `site.api.espn.com` scoreboard | **200** |

A 403 even for a long-finished game ruled out "games not played yet". Public reports confirm that NBA's CDN started answering 403 to scripted requests on every network in mid-2026, and several open-source projects moved to ESPN's site API.

## Root causes
1. **External:** the upstream source began denying all non-browser traffic.
2. **Ours:** the client mapped HTTP 403 to `NotAvailable` ("game not played yet"), because the old CDN used 403 that way. A blocked source therefore looked like a quiet day, **a silent failure**.

## Fix
- **New source: ESPN's public site API.** One summary request per game returns the box score, play-by-play and ESPN's own per-play win probability.
- **Failure classification:** `401/403 → Blocked` (fails the run and alerts), `404 → NotAvailable`, `429/5xx → retry with backoff`. A blocked source can no longer pass as "no new data".
- **Discovery and watermark redesign:** the old pipeline walked sequential NBA game IDs. ESPN event IDs aren't sequential, so the pipeline now reads ESPN's season calendar, scans each game day's scoreboard, and keeps a **date watermark** (`settled_through`): the latest date on which every game is landed or postponed. Postponed games don't block it; in-progress games do.
- **Payload trimming:** the summary also carries news, odds and videos that change constantly. Bronze stores only the game sections, and stat-correction detection hashes only the game facts, so editorial churn never registers as a "correction".
- **Schema-first rewrite:** before writing any code, real ESPN responses were captured and committed as test fixtures (`tests/fixtures/`). The contracts, the parsers and the synthetic CI data are all tested against the real structure. Writing the original NBA code without being able to fetch a real response is exactly what left the pipeline exposed.

## What stayed the same
The layered design paid off. The marts, dashboard, Airflow DAG, alerting and ops models were untouched apart from team-code mapping. The change was contained to the client, the contracts and the staging models.

## Lessons
- Classify upstream failures explicitly; never let an error code double as a business state.
- "Success with zero rows" deserves an alert of its own. Follow-up: a dbt freshness check on bronze (already in place) plus a volume anomaly check.
- Capture real payloads as fixtures before writing parsers.
- Keep source-specific logic at the edges (client and staging), so a source swap doesn't ripple through the warehouse.
