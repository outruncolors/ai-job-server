# Utility Prompts

Two system prompts power the voice pipeline. Both are stored in `config/omnivoice.json` and editable on this tab.

## Pre-Processing Prompt

`voice_preprocess_prompt` — used when a step has `voice_preprocess: true`. The LLM is asked to rewrite the input so it reads naturally as speech: remove markdown, expand abbreviations, drop bracketed citations, etc. The cleaned text is what actually gets sent to OmniVoice.

## Segmentation Prompt

`voice_auto_segment_prompt` — used when a step has `voice_auto_segment: true` or the [Use Voice](use-voice.md) tab's auto-segment box is checked. The LLM is told to split the transcript into natural speech segments and assign a pause (in milliseconds) after each. The expected output shape is the `format_voice_segments` MCP tool's arguments.

## Editing

Each field has **Save** (writes the field via `PUT /v1/omnivoice/config`) and **Reset to Default** (clears the field; the server falls back to the built-in default constant in `app/omnivoice/constants.py`).

Leaving a field blank is the right move when the default works; only set it when you want different behavior. Saved prompts are used immediately — no restart.
