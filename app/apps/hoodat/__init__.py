"""Hoodat — a character creation/management app.

Create characters from a name + a free-text prompt; a generation chain best-
guesses every field of a versioned, standardized character template. Each field
can be regenerated on demand, the character gets a Discord-profile-style page,
and an avatar can be generated (ComfyUI `image` workflow) or uploaded. "Targeted
Exports" render the whole character doc at a configurable level of detail.

All the internal LLM prompts (create, per-field, export) are registered with
Prompt Pal (`app/prompt_pal/`) so they are editable in one place.
"""
