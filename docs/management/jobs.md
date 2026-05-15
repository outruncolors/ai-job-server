# Jobs

The Jobs page (`/jobs`) lists every job ever submitted, in newest-first order, paginated 25 per page.

## What's on the page

- **List** — id (truncated), type (`chain` / `voice` / `image`), status (color-coded), created-at timestamp
- **Bulk actions** — checkboxes per row, **Clear** removes selected, **Clear All** removes everything
- **Detail panel** (right) — opens when a row is selected:
  - Metadata: id, type, status, created/updated, error (when status is `error`)
  - **Artifacts** — inline previews:
    - audio (`.wav`, `.mp3`, `.ogg`) → `<audio>` player
    - images (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`) → `<img>`
    - text (`.txt`) → preformatted block
    - other → download link
  - **Files** — direct downloads for `request.json`, `status.json`, `logs.txt`
  - **Recreate** — stores the job id in `sessionStorage` and navigates to the originating page (Chain / Voice / Image), which pre-fills its form from the job's `request.json`
  - **Delete** — removes the job folder

## Storage layout

Jobs live under `JOBS_BASE/YYYY-MM-DD/<uuid>/` (date is the submission date):

```
request.json     # the original submission payload
status.json      # { status, progress, error, … }
logs.txt         # append-only execution log
artifacts.json   # list of file paths the job produced
final_output.txt # chain jobs: the final llm step's text
steps/           # chain jobs: per-step subfolders
```

On disk the four statuses are `queued`, `running`, `done`, `error`; the server stats API renames `error` to `failed` for display.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/jobs` | Paginated list (`limit`, `offset`, optional `status` / `type`) |
| GET | `/v1/jobs/{id}` | Full record |
| GET | `/v1/jobs/{id}/files/{path}` | Serve any file in the job folder |
| DELETE | `/v1/jobs/{id}` | Delete the job and all its files |
| DELETE | `/v1/jobs` | Delete pending jobs (queued + running) |
| DELETE | `/v1/jobs/all` | Delete everything |
