# Design Voice

Generate a fresh voice sample by describing the speaker. Useful when you don't have a reference recording but know what the speaker should sound like.

## What's on the page

- **Sample text** — what to speak (aim for 3–10 seconds of speech)
- **Voice traits** — language, gender, age, pitch, style, English accent, Chinese dialect, speed (0.5–1.5×)
- **Advanced** — inference steps (4–64, default 32), guidance scale (0–4, default 2.0)
- **Generate Sample** — submit the job
- **Save as preset** — appears after generation if the sample is between 3 and 10 seconds long

## What happens on submit

The page posts to `POST /v1/jobs/voice` with the sample text and an `instruct` string that joins the selected traits. The job runs OmniVoice with no reference audio and writes `output.wav` to the job folder. The audio player on the page polls `/v1/jobs/<id>` until the job is done, then renders the result.

If you click **Save as preset**, the page posts to `POST /v1/voice-presets/from-job`, which copies the job's `output.wav` to `config/voice_presets/{uuid}.wav` and records the metadata in `config/voice_presets/index.json` (name, caption = sample text, timestamp).

## When to use this vs. Clone Voice

- **Design** if you have no recording and want to specify the speaker abstractly.
- **[Clone](clone-voice.md)** if you have a clean 3–10 s WAV of the target speaker.

Either way, the resulting preset works the same way in [Use Voice](use-voice.md) and chain `voice` steps.
