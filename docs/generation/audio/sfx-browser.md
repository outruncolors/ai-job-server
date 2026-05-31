# SFX browser

The **SFX** section of the Audio page (`/voice`, L1 nav → **SFX**) is where you work with the
sound-effect / emote clips imported into the SFX service. It has an **L2 nav** with two tabs:

- **Explorer** — a read-only grid to scan and audition clips (browse + play only).
- **Synthesis** — combine clips into a new sample with delays between them, then save it.

## Explorer

The Explorer loads `GET /v1/sfx/packs` once on first open and does all filtering and sorting
client-side from the cached structure (one round trip, no per-clip calls).

Scope a view with the two leftmost selectors, then narrow and order it:

- **Pack** — an installed SFX pack (e.g. *Universal Emotes*, *Shinlalala Lewd Pack*).
- **Profile** — a profile within the pack. Identity packs expose one profile per
  identity × pitch variant (e.g. *Mature Woman*); global packs expose a single *Global*
  profile. Scoping by profile keeps the grid manageable (large packs hold tens of thousands
  of clips spread across profiles).
- **Search** — substring match over description, id, category, tags and domain.
- **Category** — filter to one category (cough, laugh, sneeze, cum, …); options are derived
  from the selected profile.
- **Tag / domain** — filter to a single tag, or (for global packs) a domain such as `lewd`.
- **Sort** — by name, category, or duration.

Each card shows the clip's category, duration, description and tag chips, with a **▶ Play**
button and a **➕** button that adds the clip to the Synthesis builder. Playback runs through
one shared `<audio>` player at the top of the view; the active card is highlighted. Clips
stream from `GET /v1/sfx/file/{path}`.

## Synthesis

The Synthesis tab combines clips into a single new sample. Add clips from the Explorer with
**➕** (the tab shows a count), then in **Synthesis**:

- Reorder rows (↑ / ↓), remove them (✕), and set a **delay (ms)** of silence inserted *after*
  each clip — the trailing delay of the last clip is ignored.
- **Synthesize** posts the clip list to `POST /v1/sfx/synthesize`, which concatenates the
  clips (normalized to 48 kHz mono 16-bit) and returns one WAV to preview.
- **Save** (with a name) persists it via `POST /v1/sfx/synthesis`. Saved samples are listed
  below with play (`GET /v1/sfx/synthesis/{id}/file`) and delete; they live in the gitignored
  `config/sfx_synthesis/` tree (`index.json` + `<id>.wav`), mirroring the voice-presets layout.

This tab is the first step of a feature that will grow over time. Current limits:

- **WAV clips only at runtime** — synthesis decodes with parselmouth, which can't read OGG, so
  the Explorer's ➕ button is disabled for any `.ogg` clip and the endpoint rejects them. To
  bring an OGG pack into play, transcode it to WAV once with
  `scripts/convert_ogg_to_wav.py` (libsndfile) — see the [SFX tool docs](../../tools/sfx.md).
  The bundled lewd pack has already been converted, so all installed clips are usable.

## Related

- Backend service, importer and data model: [SFX tool docs](../../tools/sfx.md)
- Per-character emote configuration lives in Hoodat's character **Audio** tab (which pack /
  identity / pitch a character uses), not here.
