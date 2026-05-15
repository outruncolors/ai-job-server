# Tickets

A minimal queue for autonomous iteration. Tickets are stored as JSON, sorted by priority, and worked through one at a time on fresh branches.

The goal is simple: describe a goal once (via the `create-tickets` skill), then keep saying "work the next ticket" (via the `work-next-ticket` skill) until the queue is empty. Each ticket carries `file_hints` — paths the iteration should read first — so successive runs don't re-explore the codebase.

## Data model

Stored at `config/tickets/index.json` (gitignored).

| Field | Notes |
|---|---|
| `id` | UUID |
| `title` | Imperative summary |
| `description` | What and why; acceptance criteria |
| `priority` | Integer; lower = higher priority. Matches array index after a reorder. |
| `status` | `todo` \| `in-progress` \| `done` |
| `file_hints` | List of paths to read first when picking up the ticket |
| `branch` | Set by `work-next-ticket` when work begins |
| `created_at` / `updated_at` | ISO timestamps |

## UI

`/tickets/` — two-panel layout:

- **Left**: ordered list. Drag a row up or down to change priority; the new order is POSTed to `/v1/tickets/reorder` and persists.
- **Right**: form for the selected ticket. Edit title/description/status/file_hints, save, delete. `Branch` is read-only (filled by the skill).

Click `+ New` to create one by hand. Mostly you'll create them via the `create-tickets` skill and just review here.

## REST API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/tickets` | List, sorted by priority |
| `GET` | `/v1/tickets/next` | Highest-priority `todo`; 404 if none |
| `POST` | `/v1/tickets` | Create. Body: `{title, description?, file_hints?}` |
| `GET` | `/v1/tickets/{id}` | Fetch one |
| `PATCH` | `/v1/tickets/{id}` | Update any of `title`/`description`/`status`/`file_hints`/`branch`/`priority` |
| `DELETE` | `/v1/tickets/{id}` | Remove; remaining priorities are compacted |
| `POST` | `/v1/tickets/reorder` | Body: `{ids: [...]}`. Reassigns priorities by index. 422 if the id set doesn't match. |

## Skills

Two Claude Code skills wrap the queue, both at `.claude/skills/<name>/SKILL.md`:

### `/create-tickets`

You describe a goal. The skill reads `CLAUDE.md` for orientation, decomposes the goal into 3–8 well-scoped tickets in priority order, and POSTs them. Each ticket gets concrete `file_hints` so the worker iteration knows where to start.

It does not stop to confirm — review and reorder in the UI afterward.

### `/work-next-ticket`

The skill:

1. Refuses if the working tree is dirty.
2. Pulls `GET /v1/tickets/next`.
3. Creates a fresh branch `ticket/<short-id>-<slug>` from `master`.
4. Marks the ticket `in-progress` and records the branch.
5. **Reads every path in `file_hints` first.**
6. Implements the work, updates docs (and the `CLAUDE.md` Key files table if new modules were added).
7. Runs `py_compile` and any relevant tests.
8. Commits locally (no push) with `Area: imperative description`.
9. Marks the ticket `done`.

On test/compile failure, the ticket stays `in-progress` and no commit is made.

## Typical session

```text
You:    /create-tickets — add a tag filter to the jobs page
Claude: Created 4 tickets:
          1. Add tag field to job model (id: a3f9c12b)
          2. Index jobs by tag (id: …)
          3. Add tag filter UI to jobs page (id: …)
          4. Update jobs docs (id: …)
        Review/reorder at /tickets/

You:    /work-next-ticket
Claude: Ticket a3f9c12b done.
          Title:  Add tag field to job model
          Branch: ticket/a3f9c12b-add-tag-field-to-job-model
          Commit: 1f0e3b2

You:    /work-next-ticket
…
```

You stay in the driver's seat: every commit is local, and every branch is reviewable before merge.
