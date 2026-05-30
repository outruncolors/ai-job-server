# Blaboratory Config Tab — Build Plan

> Adds an in-app **Config** tab so operators can manage the sim from the UI:
> sim controls (start/stop, fire-now) move off the timeline row into a dedicated
> tab, and the existing env-var knobs (tick interval, memory caps, hybrid
> retrieval) become editable forms whose values **apply hot** — no server
> restart, no shelling into env files.
>
> Same conventions as the other build plans in this folder: `.venv/bin/python`,
> `.venv/bin/pytest` (`asyncio_mode=auto`), `py_compile` for syntax checks;
> stores write under `config/` (gitignored). No new dependencies.

## Decisions locked

| Decision | Choice | Consequence |
|----------|--------|-------------|
| Tab routing | **Hash route** (`/apps/blaboratory/#rooms`, `#config`). Default = rooms. | Bookmarkable + back/forward. Cheap to implement. |
| Tab markup | **`switchTab()` + `.tab-btn[data-tab]` + `.tab-pane#tab-<name>`** — same as Server/Voice/Image. | Reuses the project pattern; same CSS treatment. |
| Settings storage | New `config/blaboratory/settings.json` (file-per-doc not needed — flat dict). | Matches the `occupancy.json` / `embeddings.json` flat-JSON-doc pattern already in `config/blaboratory/`. |
| Env-var role | **First-boot fallback only.** File overrides env. Same precedence as `clock_state.json`. | Existing `BLAB_*` env vars still seed initial values; a deleted settings file = back to env defaults. |
| Hot-application | **Per-key getter functions** wrapping the settings dict, called by consumers on each iteration. | Tick interval changes apply on the **next** tick (current `asyncio.sleep` keeps running for its current cycle). Memory caps apply on the next context build. |
| Validation | Server-side: positive ints; min `1`, max sane (e.g. tick interval ≤ 86400). Reject with 422 + field-keyed error. | UI shows the message inline next to the field. |
| Save UX | **One Save button per section.** Each section is its own form. | Less risk of accidentally pushing half-edited values from another section. |
| Sim controls placement | **Move** `Fire tick` / `Start clock` / status text to a "Simulation" section at the top of the Config tab. | Timeline scrubber (◀ ▶ Jump to latest) stays in the Rooms tab — that's *viewing*, not control. |
| Embeddings config | **Out of scope** for v1. Already lives in `config/blaboratory/embeddings.json` with its own surface area. Revisit later if needed. | Keeps this plan focused. |
| Lore / world.json | **Out of scope** for v1. Content editing is a separate UX (markdown-ish editor, much bigger). | This tab is for *numeric/boolean knobs*. |

---

## Settings schema (v1)

```json
{
  "tick_interval_seconds": 300,
  "max_memory_items":       30,
  "max_memory_chars":     4000,
  "recency_floor_items":    10,
  "relevant_top_k":         10
}
```

Defaults are the same numeric values currently baked into `app/apps/blaboratory/config.py`.
First boot with no `settings.json`: the getters return the env-defaulted values from `config.py`;
first write creates the file with the full dict. After that, the file is the source of truth.

`clock_state.json` stays separate — it's runtime state (running/stopped), not a configured knob.

---

## Backend

### New: `app/apps/blaboratory/settings_store.py`

Mirrors the `activity_store.py` shape:

```python
def get_settings() -> dict          # merge env defaults <- file overrides
def update_settings(patch: dict) -> dict  # validate, merge, atomic write, return new full dict

# Per-key getters that consumers call on each access:
def tick_interval_seconds() -> int
def max_memory_items()      -> int
def max_memory_chars()      -> int
def recency_floor_items()   -> int
def relevant_top_k()        -> int
```

`get_settings()` reads the file once per call (cheap — small JSON, file system cache is fine
for the read rate we have). No in-memory cache to invalidate.

### New routes (in `router.py`)

- `GET  /v1/apps/blaboratory/settings` → full dict
- `PUT  /v1/apps/blaboratory/settings` → body is **partial** (Pydantic model with `Optional` fields); returns full dict

### Refactor consumers to use getters

Three call sites today import constants directly from `config.py`:

| Site | Currently | Change to |
|------|-----------|-----------|
| `sim_clock.py` `_loop()` | `await asyncio.sleep(TICK_INTERVAL_SECONDS)` | `await asyncio.sleep(tick_interval_seconds())` |
| `context_pipeline.apply_caps()` | imports `MAX_MEMORY_ITEMS`, `MAX_MEMORY_CHARS` | call `max_memory_items()` / `max_memory_chars()` |
| `context_pipeline.retrieve_memories()` (hybrid path) | imports `RECENCY_FLOOR_ITEMS`, `RELEVANT_TOP_K` | call `recency_floor_items()` / `relevant_top_k()` |

`config.py` keeps the env-default constants as the **defaults** the getters fall back to — that
file remains the single place env-var names + numeric defaults are declared.

---

## Frontend

### `static/apps/blaboratory/index.html`

Insert a tab strip between `#lab-header` and the existing content, then wrap that content in a
`.tab-pane#tab-rooms` and add a new `.tab-pane#tab-config`:

```
#lab-header
  ⚗ Blaboratory  /  subtitle

.tab-strip
  [Rooms]  [Config]

#tab-rooms.tab-pane
  #timeline (scrubber only — sim controls removed)
  #grid

#tab-config.tab-pane
  Simulation
    [▶ Start clock] [⊕ Fire tick]   status text
  Clock
    Tick interval (seconds) [____] [Save]
  Memory
    Max items [__] [Save]      Max chars [____] [Save]
  Hybrid retrieval (D1)
    Recency floor items [__] [Save]   Relevant top-K [__] [Save]
```

(Layout uses the same dark-panel styling as elsewhere; section rendering helper TBD inline in
`blaboratory.js` — only ~5 fields, no need for a separate module.)

### Hash routing

```js
function syncTab() { switchTab(location.hash.replace('#','') || 'rooms'); }
addEventListener('hashchange', syncTab);
syncTab();
```

Tab buttons set `location.hash` rather than calling `switchTab()` directly.

### Sim-controls relocation

Today: `index.html` has `.tl-sim` (Fire / Start clock / status) inside `#timeline`. That whole
block moves into `#tab-config` under the "Simulation" section. The JS hookups
(`tl-fire.addEventListener`, `tl-clock.addEventListener`, `reflectClock`, `toggleClock`,
`fireTick`) stay byte-identical — only the DOM location changes.

### Settings form wiring

One small helper to fetch + render initial values, plus per-section save handlers that
`PUT /settings` with the relevant subset and reflect the response. Inline error rendering on 422.

---

## Phasing

1. **Backend foundation** — settings store + getters + GET/PUT routes + Pydantic patch model + unit tests for store + route.
2. **Hot-reload refactor** — switch the 3 call sites to getters. Add a test that mutating settings changes the values returned by `tick_interval_seconds()` etc.
3. **Frontend tab structure** — add tab strip + hash routing, wrap existing content in `#tab-rooms`, empty `#tab-config` pane. No functional change to behavior.
4. **Move sim controls** — relocate `.tl-sim` into the Config tab's Simulation section. JS handlers unchanged.
5. **Config form** — add the four numeric-input sections + per-section save buttons + initial fetch.

Each phase is independently testable and shippable. Phases 1–2 are pure backend (no UI), phase 3 is pure UI (no behavior change), phases 4–5 are the visible payoff.

---

## Verification

- `pytest tests/apps/blaboratory/test_settings_store.py` — round-trip, env fallback, partial update, validation rejection.
- `curl -X PUT .../settings -d '{"tick_interval_seconds": 60}'` then watch the sim — next tick fires ~60s later, not ~300s.
- Browser: toggle Start clock, edit tick interval, set fire-now — confirm everything still works after restart (state persists, settings persist, fire-now respects current interval).

---

## Out of scope (next time)

- Embeddings config editor (port, model path, query prefix) — has its own surface area in `embeddings.json` + the embed server lifecycle UI.
- `[Everyone Knows]` / lore content editing — that's a markdown-ish editor, much bigger.
- Multi-resident bulk actions, occupancy reset, residents-store browser — Manage-y features, separate tab.
- Sim "step N ticks" button — would need a different runner shape.
