---
name: create-tickets
description: Break a user's high-level goal or brief into a small set of well-scoped tickets and post them to the ai-job-server ticket queue. Use when the user wants to seed the autonomous-iteration queue with work — phrasings like "create tickets for…", "queue up tickets to…", "plan tickets that…".
---

# create-tickets

Turn a brief into 3–8 actionable tickets, each with `file_hints` pointing to the most relevant existing code, then post them in priority order.

## Inputs

- A free-form description of what the user wants done. The user may also specify an approximate ticket count or scope hints.

## Workflow

1. **Read the lay of the land.** Open `CLAUDE.md` and skim the "Key files" table so you can pick accurate `file_hints` per ticket. Read `docs/` if the brief touches a documented area.

2. **Write the shared overall-effort blurb first.** Before drafting any ticket, write a 3–6 sentence "Overall effort" paragraph that captures the goal of the whole batch — the user's high-level intent, the end state, and the strategy connecting the tickets. This paragraph is critical: each ticket gets embedded into a fresh autonomous iteration with no memory of this conversation, so without it the agent has no idea why the ticket exists. Re-use this paragraph verbatim at the top of EVERY ticket's description.

3. **Decompose.** Break the brief into 3–8 tickets in priority order (most foundational/blocking first). Each ticket must:
   - Have a short imperative title (e.g. "Add /about page route", "Wire up status filter to /v1/tickets").
   - Have a description with this exact structure:
     1. `## Overall effort` — the shared paragraph from step 2, identical across all tickets in this batch.
     2. `## Previously completed` — for tickets after the first, a short bulleted recap of what earlier tickets in the batch already delivered (one bullet per prior ticket, titled in past tense — "Defined MasterProfile schema…"). For ticket #1, write `## Previously completed` with a single line "Nothing — this is the first ticket in the batch." so the structure is consistent.
     3. `## This ticket` — the actual task: WHY this slice exists in service of the overall effort, what to build, and acceptance criteria ("Done = …").
   - Have `file_hints`: the actual file paths in this repo most worth reading first. Aim for 2–5 concrete paths per ticket. The point of these hints is to keep future iterations from re-discovering the same files.
   - Be scoped so a single iteration can finish it in one branch/commit (roughly 10–60 minutes of focused work).

4. **Post immediately.** No need to confirm with the user first — they will review/edit/reorder in the UI. POST each ticket in priority order so the array index matches priority:

   ```bash
   curl -s -X POST http://127.0.0.1:8090/v1/tickets \
     -H 'content-type: application/json' \
     -d '{"title":"…","description":"…","file_hints":["app/…","static/…"]}'
   ```

5. **Report.** Print a numbered list of the tickets created (priority, title, id) and link to `http://<host>:8090/tickets/` so the user can drag/edit if they want.

## Updating an existing batch

If the user asks to revise tickets you (or a previous session) already posted — e.g., to add the shared context, fix scope, change order — use `PATCH /v1/tickets/{id}` with a JSON body of the fields to change (typically `description`). Re-derive the shared "Overall effort" paragraph from the existing batch first so all tickets stay consistent.

## Output format

```
Created N tickets:
  1. <title> (id: <short>)
  2. <title> (id: <short>)
  …
Review/reorder at /tickets/
```

## Failure handling

- If a POST returns 422, surface the message and continue with the next ticket.
- If the server is not running (connection refused), tell the user to start it with `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090` and stop.
- Never invent file paths in `file_hints` — only paths you have verified exist in this repo.
