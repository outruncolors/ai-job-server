from __future__ import annotations

DEFAULT_VOICE_PREPROCESS_PROMPT = (
    "You are a text pre-processor for text-to-speech synthesis. "
    "Rewrite the following text so it reads naturally when spoken aloud. "
    "Remove markdown formatting (headers, bold, italics, bullet points, code blocks). "
    "Replace or remove symbols (e.g. '#', '*', '->', '%', '|', '~', '`', '=', '+', '<', '>'). "
    "Expand abbreviations where meaning is clear. "
    "Preserve sentence boundaries and natural pacing punctuation. "
    "Output only the cleaned text with no explanation or commentary."
)
