# Clone Voice

Turn an existing WAV recording into a voice preset that can be reused for synthesis. The recording acts as the reference audio for OmniVoice's speaker-conditioned mode.

## What's on the page

- **WAV file** — file picker for the reference recording (3–10 seconds, mono or stereo accepted)
- **Preset name** — display label; collisions get a `(2)`, `(3)`, … suffix automatically
- **Caption** — the exact transcript of what's spoken in the WAV. OmniVoice uses this as the reference text alongside the audio
- **Save Preset** — uploads and persists

## What happens on submit

The page posts the file and metadata as `multipart/form-data` to `POST /v1/voice-presets`. The server:

1. Validates the WAV duration (rejects outside 3–10 s)
2. Copies the file to `config/voice_presets/{uuid}.wav`
3. Appends a record to `config/voice_presets/index.json` with `id`, `name`, `caption`, `wav_filename`, `created_at`

The new preset is immediately selectable in [Use Voice](use-voice.md) and in chain `voice` steps.

## What makes a good sample

- Clean speech, no music or background noise
- Natural cadence — not a list, not a whisper
- The caption must match the audio word-for-word; OmniVoice uses it as the reference text and a mismatch degrades the clone

If your recording is longer than 10 seconds, trim it first; the validator will reject the upload otherwise.
