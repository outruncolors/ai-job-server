# SFX browser

The **SFX** section of the Audio page (`/voice`, L1 nav → **SFX**) is a read-only grid for
scanning and auditioning the sound-effect / emote clips that have been imported into the SFX
service. It does not edit, tag, import, or delete clips — just browse and play.

## How it works

The page loads `GET /v1/sfx/packs` once on first open and does all filtering and sorting
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
button. Playback runs through one shared `<audio>` player at the top of the view; the active
card is highlighted. Clips stream from `GET /v1/sfx/file/{path}`.

## Related

- Backend service, importer and data model: [SFX tool docs](../../tools/sfx.md)
- Per-character emote configuration lives in Hoodat's character **Audio** tab (which pack /
  identity / pitch a character uses), not here.
