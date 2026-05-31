# Audio

The Audio page (`/voice`) is the home for everything audio-related. A top-level **L1 nav** switches between two sections:

- **Voice** — synthesis on **OmniVoice** (an ephemeral subprocess invoked per synthesis), storing reusable voices on disk as **voice presets**
- **[SFX](sfx-browser.md)** — a read-only browser to scan and audition imported sound-effect / emote clips

The **Voice** section has four sub-tabs (L2 nav):

- **[Design Voice](design-voice.md)** — synthesize a sample from scratch by describing the speaker
- **[Clone Voice](clone-voice.md)** — turn an existing WAV recording into a preset
- **[Use Voice](use-voice.md)** — synthesize text with a saved preset, with optional LLM-driven segmentation
- **[Utility Prompts](utility-prompts.md)** — edit the system prompts that power pre-processing and auto-segmentation

All four tabs submit voice jobs through `POST /v1/jobs/voice` (except Clone Voice, which just uploads a WAV via `POST /v1/voice-presets`). Voice presets live at `config/voice_presets/{uuid}.wav` with metadata in `config/voice_presets/index.json`.

OmniVoice configuration (model id, base CLI command, default speed, system prompts) lives in `config/omnivoice.json`; see [Utility Prompts](utility-prompts.md) for the editable fields and [Configuration](../../reference/configuration.md) for the rest.
