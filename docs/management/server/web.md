# Server / Web

Live view of this FastAPI server's resource usage and job counts, plus a restart control.

## What's on the page

- **Resources** — animated bars for CPU %, memory (used/total), disk (used/total)
- **Jobs** — four badges: queued, running, done, failed
- **Server info** — hostname, Python version, process uptime
- **Restart Server** — gracefully replaces the process

The page polls `/v1/server/stats` every 5 seconds. An action log at the bottom records restart attempts and reconnect outcomes.

## Restart behavior

Clicking **Restart Server** posts to `/v1/server/restart`. The handler schedules `schedule_restart()` on the background thread, which calls `os.execv()` to replace the process with a fresh one (same argv, same env). The browser then retries `/v1/server/stats` on a Fibonacci backoff (1, 1, 2, 3, 5, 8, 13, 21, 34, 55 s, max 10 tries) and shows a countdown toast until the server answers.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/server/stats` | CPU / memory / disk / job counts / uptime |
| POST | `/v1/server/restart` | Schedule a process restart |

`psutil.cpu_percent()` is called once at module import to prime the sampler — every subsequent stats call passes `interval=None` and returns the delta since the previous call. Job counts are cached for 5 s in `_get_job_counts()` to avoid repeated walks of the jobs directory; on disk a job's `status.json` may say `"error"` but the API maps this to `"failed"` (see `_STATUS_MAP` in `app/server.py`).
