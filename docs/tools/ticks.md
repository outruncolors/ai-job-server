# Ticks

A tick is a schedule that fires a saved [sequence](../generation/text/sequences.md) on an interval or cron expression. Use ticks for recurring chain jobs — a daily digest, a "summarize the latest" loop, anything you'd otherwise run by hand.

## What's on the page

- **Left** — list of ticks. Each row shows name, target sequence, schedule summary, time-until-next, and a ▶ Fire Now button.
- **Right** — editor:
  - **Name** and **Sequence** (dropdown of saved sequences)
  - **Schedule** — toggle between *interval mode* (every N minutes / hours / days / weeks, with an optional HH:MM anchor) and *cron mode* (raw cron expression with a live preview of the next three fire times)
  - **Enabled** checkbox
  - **Recent jobs** — when editing, the last 10 jobs spawned by this tick

## Data model

Stored in `config/ticks/index.json`:

| Field | Type | Notes |
|-------|------|-------|
| `id`, `name`, `sequence_id` | | |
| `schedule` | object | always stored as a cron expression in UTC; interval mode is converted client-side |
| `enabled` | bool | default `true` |
| `last_fire_at`, `last_job_id`, `last_skip_reason` | | populated by the scheduler |
| `next_fire_at` | ISO 8601 | precomputed |

## Scheduler

`TickScheduler` (`app/ticks/scheduler.py`) is an async loop polled every 10 s. On each tick:

1. Load all enabled ticks.
2. For each with `next_fire_at <= now`:
   - If the previous job (`last_job_id`) is still `queued` or `running`, skip with `last_skip_reason = "overlap"`.
   - If the target sequence is gone, skip with `"sequence_missing"`.
   - If no default LLM preset is set, skip with `"no_default_llm"`.
   - Otherwise create a chain job whose single step is `{type: "sequence", sequence_id}`, tag it with `fired_by_tick: <tick_id>`, and record `last_job_id`.
3. Recompute `next_fire_at` from the cron expression.

The scheduler starts in the FastAPI lifespan and is cancelled at shutdown.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/ticks` | List |
| POST | `/v1/ticks` | Upsert |
| DELETE | `/v1/ticks/{id}` | Remove |
| POST | `/v1/ticks/{id}/enable` | Toggle `enabled` |
| POST | `/v1/ticks/{id}/fire` | Fire now (respects overlap unless `force=true`) |
| GET | `/v1/ticks/{id}/recent-jobs` | Jobs filtered by `fired_by_tick` |
| POST | `/v1/ticks/preview` | Preview the next three fire times for a cron string |

## Gotchas

- All schedules are stored and evaluated in UTC. The HH:MM anchor in interval mode is interpreted as UTC.
- Cron expressions are validated by `croniter` at save time; invalid strings return `422`.
- Clock jumps backward can re-fire a tick. Forward jumps catch up at the next poll.
- Overlap is checked against `queued`/`running` only; finished jobs don't block.
