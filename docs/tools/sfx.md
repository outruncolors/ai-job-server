# SFX (sound effects)

A platform-level subsystem (`app/sfx/`) that turns vendor sound packs into one
**normalized manifest** shape and serves clips over HTTP. Prattletale's
[SFX plugin](../apps/prattletale/index.md) consumes it to attach an optional
emote after-cue to `action`/`narration` items; Hoodat characters pick the emote
**identity** that represents them.

## Pack model

Every pack is normalized to `SFX_ROOT/normalized/<pack_id>/manifest.json` (env
`SFX_ROOT`, default `/opt/ai-stack/sfx`). Item `path` values are **relative to
`SFX_ROOT`**, so vendor originals are read in place and never copied — only pitch
derivatives (below) are generated, under `normalized/<pack_id>/files/`.

A pack's `binding` discriminates how it's addressed:

- **`identity`** — character-bound emote packs. Profiles are standard **identity**
  enums (below) plus `_low` / `_high` pitch variants. A Hoodat character selects
  one identity; the resolver draws that profile's items.
- **`global`** — not character-bound. A single `_global` profile whose items carry
  a `domain` (`lewd`, and later `footsteps` / `nature` / …). A Prattletale
  conversation opts a domain in via `config.sfx_domains` (the NSFW gate).

Items carry `category` (flat lowercase snake-case), free `tags`, `duration_ms`,
`weight`, and a `source` block for traceability. The chooser prompt only ever sees
a compact **category summary** (count + sample descriptions + tags), never the raw
file list.

### Identity enum

Gender presentation × five age bands (`app/sfx/models.py:Identity`):

```
child:        little_girl    little_boy
teen:         teen_girl      teen_boy
young_adult:  young_woman    young_man     (20s–30s)
mature_adult: mature_woman   mature_man    (40s–50s)
elderly:      elderly_woman  elderly_man   (60s–70s)
```

Each identity also has pitch variants: `young_woman`, `young_woman_low`,
`young_woman_high`.

### Pitch / formant variants

For every identity profile the importer writes `_low` and `_high` siblings whose
items are PSOLA pitch+formant-shifted copies of the base clips, via
[`praat-parselmouth`](https://parselmouth.readthedocs.io) (in `requirements.txt`;
no system binary needed). Vocal pitch shifting must move **formants together with
pitch** — a pure resample sounds like a chipmunk and pitch-only shifting sounds
unnatural — so the importer uses Praat's `Change gender` (PSOLA, duration
preserved) with modest ratios (`_high` ≈ pitch ×1.15 / formant ×1.10, `_low` ≈
pitch ×0.87 / formant ×0.92; tunable constants in the importer). Derivatives are
downsampled to 48 kHz. Global packs get no pitch variants.

## Importer

```bash
.venv/bin/python scripts/import_sfx_pack.py \
    "/opt/ai-stack/sfx/Articulated--Universal_Emotes--Separated_01" \
    --pack-id universal_emotes --binding identity --display-name "Universal Emotes"

.venv/bin/python scripts/import_sfx_pack.py \
    "/opt/ai-stack/sfx/Shinlalala's Lewd Sound Pack" \
    --pack-id shinlalala_lewd --binding global --domain lewd \
    --display-name "Shinlalala Lewd Pack"
```

`--no-pitch` skips variant generation; `--limit N` caps files per folder (testing).
For identity packs the speaker folder name (`EMOTE Ashley, Woman, 40s`) maps to an
identity; macOS `._` sidecar files are skipped. Emote categories derive from the
vendor `CatID` prefix (`HMNSneez`→`sneeze`, `VOXLaff`→`laugh`, …); global
categories from the source folder name.

## API (`/v1/sfx`)

| Route | Purpose |
| --- | --- |
| `GET /packs` | every normalized pack |
| `GET /packs/{id}` | one pack |
| `GET /packs/{id}/profiles/{pid}` | a profile + its category summary |
| `GET /identities` | selectable identity profiles (base + pitch), for Hoodat |
| `POST /preview` | resolve one clip (by `effect_id`, or weighted-random in a category) → served URL |
| `GET /file/{rel_path}` | serve a clip (path-traversal guarded under `SFX_ROOT`) |

## Resolver

`app/sfx/resolver.py:resolve_sfx` is platform-level and app-agnostic. Given a
line's text/type, a character identity, and the enabled global domains it: gates
the type (`action`/`narration` only) → **rolls the chance before any LLM call** →
builds a candidate pool (identity emotes + domain items) → runs the editable
`sfx.choose_emote` Prompt Pal chooser and its guard as a 2-step in-request chain →
weighted-random picks a variant in the chosen category. It returns a compact
descriptor (`status` ∈ `skipped` / `none` / `rejected` / `resolved` / `error`) plus
a verbose trace. See the [Prattletale SFX plugin](../apps/prattletale/index.md) for
how it's wired into the chat.
