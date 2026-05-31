# SP6 — Voice + timing

Sub-phase **SP6** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** [05 — SP5](05-sp5-frontend.md) · **Next:** [07 — SP7 hardening + docs](07-sp7-hardening-docs.md) · [Sequence](README.md)

Depends on **SP3–SP5**, committed. Needs the `voice` capability for the manual check; degrades to
text without it.

```
Implement Phase 1 sub-phase SP6 of Prattletale (iMessage-style roleplay chat): voice synthesis +
typing/reveal timing. The text-only loop (SP1–SP5) is committed. This is the text-first/voice
split: voice is additive and must degrade cleanly to text.

Read first:
- docs/apps/prattletale/design.md — "Voice + timing (SP6 summary)".
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP6" section.
- app/chain/steps/voice.py — run_voice_step (TTS synthesis, auto-segmentation, wav output).
- app/omnivoice/runner.py — OmniVoiceEphemeralRunner.
- app/voice_presets.py — get_preset / resolve_preset_wav.
- app/voice_presets_router.py — the _wav_duration(bytes) helper (reuse the wave-module approach).
- app/server.py — requires_capability("voice") and get_local_capabilities().
- The /v1/jobs/voice route in app/main.py — how voice jobs are gated + run.
- Committed SP3 generator + SP5 frontend.

Build:
- Activate config.voice_enabled / typing_timing_enabled (they already exist, inert). Add a UI
  toggle on the conversation (or the new-conversation form) and a new app-level NARRATOR voice
  preset setting (a small config doc under config/prattletale/, with a CRUD helper + a Server-page
  or app-settings control — keep it minimal).
- In the generator (or a sibling app/apps/prattletale/voice.py): after a successful text turn, if
  voice is enabled AND the "voice" capability is available, synthesize:
  - model `dialogue` items -> the COUNTERPART's voice preset (character.speaking_style
    .voice_preset_id; if absent, skip audio for that item);
  - model `narration` / `narration_emotion` items -> the app-level narrator voice;
  - NEVER synthesize user-authored items.
  Write media/<item>.wav under the conversation folder and set item.audio = {path, duration_ms,
  voice_preset_id}. Compute duration_ms from the wav (reuse the _wav_duration approach). If the
  voice capability is missing (requires_capability would 503) or voice is disabled, skip synthesis
  and leave item.audio = null with no media files.
- Reveal schedule: compute a per-item typing duration from text length (plus the clip duration
  when audio exists) plus jitter, and store the schedule in the trace. The frontend plays the
  reveal cadence (typing dots -> reveal -> audio after reveal); user-authored items reveal
  immediately.

Done when:
- automated (tests/apps/test_prattletale_voice.py, stub the synth + monkeypatch capabilities): with
  voice enabled, a model turn sets item.audio on dialogue/narration items and writes media/*.wav;
  with voice disabled OR the "voice" capability removed, the same turn returns text-only (audio
  null, no media files);
- manual (real LLM + voice node): a model turn plays a believable typing -> reveal -> audio cadence
  and the audio uses the right voices.
Run the full suite — the generator changed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
