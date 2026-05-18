---
name: work-next-ticket
description: Pick the highest-priority todo ticket from the ai-job-server queue, branch from master, implement the work using the ticket's file_hints, update docs, and commit locally. Use when the user wants to advance the autonomous-iteration queue — phrasings like "work the next ticket", "do the next one", "pick up a ticket".
---

# work-next-ticket

Pull the next `todo` from the queue and complete it on a fresh branch with a local commit.

## Inputs

None. The skill operates on whatever is at the top of the queue.

## Workflow

1. **Verify clean tree.** Run `git status --porcelain`. If non-empty, abort with a clear message listing the dirty files and ask the user to commit/stash first. (`.claude/settings.local.json` and `config/` are gitignored and won't appear.)

2. **Fetch the next ticket.**
   ```bash
   curl -s http://127.0.0.1:8090/v1/tickets/next
   ```
   If 404, report "no todo tickets" and exit.

3. **Compute branch name.** `ticket/<first-8-chars-of-id>-<kebab-title-truncated-40>`. Example: `ticket/a3f9c12b-add-about-page-route`.

4. **Mark in-progress and record branch.**
   ```bash
   curl -s -X PATCH http://127.0.0.1:8090/v1/tickets/<id> \
     -H 'content-type: application/json' \
     -d '{"status":"in-progress","branch":"<branch>"}'
   ```

5. **Branch from master.**
   ```bash
   git checkout master && git checkout -b <branch>
   ```

6. **Read every file in `file_hints` first.** This is the whole point of the hints — start from known coordinates, don't re-explore the codebase. After reading, search/explore further only if the hints don't cover everything you need.

7. **Implement the work** described in title + description. Follow patterns in CLAUDE.md.

8. **Update documentation.**
   - If you touched a feature area documented in `docs/`, update the relevant page.
   - If you added a new Python module, append a row to the "Key files" table in `CLAUDE.md`.

9. **Verify.**
   - `.venv/bin/python -m py_compile <changed .py files>` — must pass.
   - If tests exist for the touched area, run them: `.venv/bin/pytest <path>`. (Note: `tests/test_omnivoice.py` and `tests/test_voice_presets.py` have pre-existing failures unrelated to your work — ignore those unless you touched voice code.)

10. **Commit locally** (no push).
    ```bash
    git add <specific files>
    git commit -m "<Area>: <imperative summary>"
    ```
    Match the project's commit style (see `git log --oneline -10`): `Area: imperative description`, no trailing period.

11. **Merge into master + clean up.** Fast-forward only — never use a merge commit. If the FF fails, something else has advanced master; report and stop.
    ```bash
    git checkout master && \
      git merge --ff-only <branch> && \
      git branch -d <branch>
    ```
    This keeps master always-current so the next ticket branches from a base that includes prior work. Never `git push`.

12. **Mark done.**
    ```bash
    curl -s -X PATCH http://127.0.0.1:8090/v1/tickets/<id> \
      -H 'content-type: application/json' \
      -d '{"status":"done"}'
    ```

## Output format

```
Ticket <id> done.
  Title:   <title>
  Branch:  <branch> (merged to master, deleted)
  Commit:  <sha>
  Files:   <count> changed
```

## Failure handling

- **Dirty tree at step 1**: abort, do not modify the ticket.
- **Compile/test failure at step 9**: leave the ticket as `in-progress`, do not commit, report the failure with logs. The user can decide to fix or revert.
- **FF-only merge fails at step 11**: leave the ticket as `in-progress` with the commit on its branch. Do not force-merge or create a merge commit. Report so the user can resolve.
- **Implementation blocked** (missing info, ambiguous requirements): leave as `in-progress`, report the blocker. Do not invent acceptance criteria.
- **Server down**: tell the user to start uvicorn and stop.
- Never `git push`, never `--no-verify`, never amend. New commits only.
