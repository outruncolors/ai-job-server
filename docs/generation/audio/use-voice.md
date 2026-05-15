# Use Voice

Synthesize audio using a saved [voice preset](clone-voice.md). The tab has two modes: manual segmentation (you control the chunks and pause timing) and auto-segmentation (an LLM splits the text for you).

## Common controls

- **Voice preset** — dropdown populated from `/v1/voice-presets`
- **Speed** — 0.5–1.5×
- **Advanced** — inference steps (default 32), guidance scale (default 2.0)
- **Synthesize** — submit the job

## Manual segmentation (default)

The page shows a segment list widget (`static/js/voice-segments.js`). Each segment has:

- **Text** — what to speak
- **Delay (ms)** — silence *after* this segment (the last segment is forced to 0)

Use **+ Add segment** to extend, the remove button to shrink. On submit, the page posts to `POST /v1/jobs/voice` with `segments: [{text, delay_ms}, …]` and the selected `voice_preset_id`. The server synthesizes each segment, concatenates the WAVs with the requested silence between them, and writes `output.wav` to the job folder.

## Auto-segmentation

Check **Auto-segment with LLM** to reveal:

- **LLM preset** — picked from `/v1/llm-presets`
- **Transcript** — the full text to synthesize

On submit, the page posts `auto_segment: true`, the transcript as `text`, plus the LLM base URL and model. The server:

1. Loads the segmentation prompt from `config/omnivoice.json` (`voice_auto_segment_prompt`) or falls back to the built-in default
2. Calls the LLM's chat endpoint with `format_voice_segments` as an available MCP tool
3. Parses the tool call's `segments` argument (or JSON in the message body as a fallback)
4. Writes the segments to `auto_segment_segments.json` in the job folder
5. Synthesizes each segment and merges them with the requested pauses

The same auto-segmentation path is used by chain `voice` steps with `voice_auto_segment: true`. The prompt that drives it is edited in **[Utility Prompts](utility-prompts.md)**.

## Output

`output.wav` plus, when auto-segmentation is on, `auto_segment_segments.json`. The UI fetches the segments file and renders a collapsible breakdown showing each segment's text and pause.
