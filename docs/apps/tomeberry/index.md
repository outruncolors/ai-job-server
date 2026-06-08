# Tomeberry

A Cursor-like two-pane studio that guides creation of **tales of arbitrary length** —
input as vague as "a princess is saved" or as complete as an outline plus drafted
chapters. Tomeberry is the fourth consumer app (after Blaboratory, Hoodat,
Prattletale) and builds entirely on existing backend tools — the chain executor,
Prompt Pal, prompt templating, the job-dir trace, plus the standardized
[MCP](../../tools/mcp.md) gateway for reading/writing workspace files.

## Layout

- **Left pane** (2/3) swaps **Content ↔ Organization**:
  - *Content* — a rich `contenteditable` editor for the current structural unit.
    A DOM selection becomes a `selection` scope (char range). A model proposal
    renders **inline** (insert=green, delete=red) with Accept / Reject / Iterate.
  - *Organization* — premise editor, the structural tree (add/rename/delete/select
    units), narrative-construct and story-entity lists, and a relationship
    inspector over typed `links[]`. Also: apply a starter template, export the tale.
- **Right pane** (1/3, persistent) — the **Assistant** chatroom + composer. Pick a
  mode + (optional) saved prompt, type an instruction, and the co-author responds.
- **Debug drawer** — per-request trace: resolved↔unresolved prompt toggle,
  populated variables, context concepts, MCP tool/resource calls, model output,
  the applied diff, and the user action.

## Concepts (the unit of meaning)

One `Concept` model covers all three classes:

- **structural_unit** — beat|scene|section|chapter|part|tale. The manuscript tree;
  `parent_id`/`children`/`order` are authoritative (`hierarchy.json` caches it).
- **narrative_construct** — premise|arc|plotline|theme|mystery|… Non-container.
- **story_entity** — character|place|object|event|… Non-container.

Non-container concepts relate via typed, directional `links[]` (cross-class).

## The 10 modes

Grouped Create / Shape / Check / Finish. Each mode has a contract (`MODE_SPECS` in
`prompts.py`): an `output_format` and a `change_policy` that decide what it proposes.

| Mode | Group | Proposes | MCP tools |
|---|---|---|---|
| Discover | Create | chat | — |
| Draft | Create | manuscript diff | fs read/list |
| Develop | Create | concept upsert | fs read/list |
| Organize | Shape | structure ops | — |
| Revise | Shape | manuscript diff | — |
| Plan | Shape | structure ops / chat | fs write |
| Edit | Check | manuscript diff | — |
| Diagnose | Check | chat | — |
| Track | Check | concept creates | fs read |
| Publish | Finish | manuscript diff / file | fs write |

## Generation pipeline (`generator.py`)

`POST /tales/{tid}/requests` → `run_assistant_request`:

1. Load tale, premise, current unit, selection, recent assistant messages, in-scope
   concepts.
2. `build_mode_variables` → the **14-variable contract** (pure, fully tested). Every
   var is always present (empty → `""`, so the renderer never falls back to a bare
   name); sections are self-labeling so empties render to nothing.
3. Assemble `tomeberry/base` + `tomeberry/mode.<mode>` via Prompt Pal **without**
   filling vars, then `render(final=True, track=True)` → `resolved_prompt` +
   `variable_substitutions` (keep the pre-render as `unresolved_template`).
4. One `ChainStep(llm)` with the mode's MCP tool set, run via `chain.oneshot`.
5. Parse per `output_format` (prose passthrough, or `chain.structured` lenient JSON).
6. Propose: a `textdiff` manuscript diff, a concept upsert/creates, or structure ops
   — chat/explain modes just post.
7. Persist a rich trace + assistant message(s) + concept history. **Never raises**
   into the caller — on failure it posts an error message (prattletale discipline).

## Diff loop

Propose → **Accept** (apply the diff to the unit body / create concepts / apply
ops, with `app/textdiff` drift detection) · **Reject** (untouched; the full
before/after stays inspectable) · **Iterate** (thread prior attempt + feedback into
a fresh request; the prior proposal is superseded and attempts link via `iterate_of`).

## Storage (tale-scoped, gitignored)

```
config/tomeberry/tales/<tale_id>/
  tale.json
  concepts/<concept_id>.json
  hierarchy.json
  assistant/<thread_id>.json
  traces/<request_id>.json
  workspace/                 # the MCP filesystem sandbox root for this tale
config/tomeberry/templates/  # global starter templates (tomeberry_template)
```

## Starters

Templates are server-wide globals (the `tomeberry_template` cruddable; shipped as
the `packs/tomeberry_template/starters.json` Pack, authorable via `/add-pack`):
three-act skeleton, hero's-journey beat sheet, character sheet. `apply-template`
**copies** a template's concept records into a tale's `concepts/`.

## Co-location note

Filesystem MCP tools act on the gateway machine's disk; tale workspaces live where
`config/tomeberry/` lives (the `web` node). Give the same node both `web` and `mcp`,
or make workspace paths peer-aware. See the [MCP](../../tools/mcp.md) doc.

## Shared building blocks (built first, reusable)

- `app/textdiff/` — content-addressed proposals (make/apply/render-inline).
- `app/chain/structured.py` — lenient JSON parsing for Track/Develop.
- `app/chain/oneshot.py` — `run_traced_llm` (create_job → execute → read).
