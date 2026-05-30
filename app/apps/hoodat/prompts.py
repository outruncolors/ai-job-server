"""Hoodat's internal LLM prompts, registered with Prompt Pal.

Registered at import time:
- `IDEATE` / `ASSEMBLE` — the create-from-prompt chain (prose → strict Character
  JSON).
- one `field.<section>.<field>` per generatable field (built from
  `models.FIELD_SPECS`) — each takes `{{var.character}}` (the rendered doc) and
  emits just that field's value.
- `avatar.image_prompt` — a `{{var.*}}`-templated image prompt for the avatar
  generator (composed mechanically, no LLM round-trip).

All are seeded into the Prompt Pal store at startup and editable in its UI;
these in-code bodies are the defaults.
"""

from __future__ import annotations

from ...prompt_pal.registry import register
from .models import FIELD_SPECS

# ---- create-from-prompt chain ---------------------------------------------

IDEATE = """\
You are inventing a fictional character for a character library.

The user gives a name and a short description:
<request>
{{input}}
</request>

Invent a single, vivid, internally-consistent character that fits. Write a few \
rich paragraphs of character notes covering: their name, a one-line summary, a \
short tagline, age, sex, occupation; their full physical appearance — height, \
build, skin tone, hair (its color and its style/details), eyes (their color and \
any notable details), and distinguishing features — and one or more outfits they \
wear (each with a top, bottoms, underwear, socks & shoes, and accessories); their \
personality (traits, quirks, values, fears); their background (backstory, origin, \
key relationships, affiliations, notable skills); how they speak; and a couple of \
formative experiences from their past, each clearly positive or negative for \
them. Invent any detail the user left unspecified. Do not output JSON yet — just \
the prose notes."""

ASSEMBLE = """\
Convert the character notes below into a single JSON object. Use ONLY the \
information in the notes; do not invent new facts.

<notes>
{{previous}}
</notes>

Output a JSON object with EXACTLY this shape and types:
{
  "name": string,
  "summary": string,
  "tagline": string,
  "age": integer,
  "sex": string,
  "occupation": string,
  "appearance": {
    "height": string, "build": string, "skin": string,
    "hair_color": string, "hair_details": string,
    "eye_color": string, "eye_details": string,
    "distinguishing_features": [string],
    "outfits": [
      {"name": string, "top": string, "bottoms": string, "underwear": string,
       "socks_shoes": string, "accessories": string, "primary": boolean}
    ]
  },
  "personality": {
    "traits": [string], "quirks": [string], "values": [string], "fears": [string]
  },
  "background": {
    "backstory": string, "origin": string, "relationships": [string],
    "affiliations": [string], "skills": [string]
  },
  "speaking_style": { "description": string },
  "experiences": [
    {"description": string, "valence": "positive" | "negative"}
  ]
}

Provide at least one outfit, and set "primary": true on exactly one of them \
(false on the rest). Respond with JSON only — no markdown, no code fences, no \
commentary."""

register("hoodat", "IDEATE", title="Ideate character", prompt=IDEATE, tags=("create", "ideate"),
         description="Invent a character from a name + free-text description (prose).")
register("hoodat", "ASSEMBLE", title="Assemble character JSON", prompt=ASSEMBLE,
         tags=("create", "assemble"),
         description="Convert character prose notes into strict v1-schema JSON.")


# ---- per-field generation --------------------------------------------------

def _field_prompt_body(label: str, kind: str) -> str:
    if kind == "list":
        out_rule = (
            "Output a short newline-separated list (one item per line), no "
            "numbering, no preamble, no quotes."
        )
    elif kind == "int":
        out_rule = "Output only a single whole number, nothing else."
    else:
        out_rule = "Output only the value itself — no preamble, no label, no quotes."
    return (
        "Here is a character:\n<character>\n{{var.character}}\n</character>\n\n"
        f"Come up with a fitting value for the field: {label}.\n"
        "Keep it consistent with everything above. "
        f"{out_rule}"
    )


def _register_field_prompts() -> None:
    for section, fields in FIELD_SPECS.items():
        for field, spec in fields.items():
            register(
                "hoodat",
                f"field.{section}.{field}",
                title=f"Field — {section}.{field}",
                prompt=_field_prompt_body(spec["label"], spec["kind"]),
                tags=("field", section),
                description=f"Generate the {spec['label']} field from the rest of the character.",
            )


_register_field_prompts()


# ---- dialogue examples (list-aware, not a scalar field) --------------------

# Deliberately NOT registered via FIELD_SPECS: a dialogue example is one item of
# a growing list, generated from the character + the prior examples (few-shot),
# so it needs its own list-aware prompt rather than the per-scalar-field shape.
DIALOGUE_EXAMPLE = (
    "Here is a character:\n<character>\n{{var.character}}\n</character>\n\n"
    "Dialogue examples already written for them (may be empty):\n"
    "<examples>\n{{var.examples}}\n</examples>\n\n"
    "Write ONE new, distinct line or short exchange of dialogue spoken by this "
    "character. Match their voice and personality, stay consistent with "
    "everything above, and do not duplicate an existing example. Output only the "
    "dialogue text itself — no preamble, no label, no quotes, no code fences."
)

register("hoodat", "dialogue.example", title="Dialogue example",
         prompt=DIALOGUE_EXAMPLE, tags=("dialogue", "speaking_style"),
         description="Generate a new dialogue example from the character + prior examples.")


# ---- experiences (list-of-objects, AI also picks the valence) --------------

EXPERIENCE_EXAMPLE = (
    "Here is a character:\n<character>\n{{var.character}}\n</character>\n\n"
    "Experiences already written for them (may be empty):\n"
    "<experiences>\n{{var.experiences}}\n</experiences>\n\n"
    "Invent ONE new, distinct formative experience for this character — something "
    "that happened to them and shaped who they are — and optionally how it made "
    "them feel. Decide whether the experience was POSITIVE or NEGATIVE for them. "
    "Match their personality and background, stay consistent with everything "
    "above, and do not duplicate an existing experience.\n"
    "Respond with a single JSON object and nothing else:\n"
    '{"description": "<one or two sentences>", "valence": "positive" | "negative"}\n'
    "No markdown, no code fences, no commentary."
)

register("hoodat", "experience.example", title="Experience example",
         prompt=EXPERIENCE_EXAMPLE, tags=("experience",),
         description="Generate a new formative experience (description + valence).")


# ---- outfits (list-of-objects, slot-structured) ----------------------------

OUTFIT_FULL = (
    "Here is a character:\n<character>\n{{var.character}}\n</character>\n\n"
    "Their other outfits (may be empty):\n<outfits>\n{{var.outfits}}\n</outfits>\n\n"
    "Design ONE complete, distinct outfit for this character, consistent with who "
    "they are and different from their other outfits. Fill every garment slot.\n"
    "Respond with a single JSON object and nothing else:\n"
    '{"name": "<short outfit name>", "top": "<...>", "bottoms": "<...>", '
    '"underwear": "<...>", "socks_shoes": "<...>", "accessories": "<...>"}\n'
    "No markdown, no code fences, no commentary."
)

register("hoodat", "outfit.full", title="Outfit (full)",
         prompt=OUTFIT_FULL, tags=("outfit", "appearance"),
         description="Design a complete outfit (all garment slots) for the character.")

OUTFIT_SLOT = (
    "Here is a character:\n<character>\n{{var.character}}\n</character>\n\n"
    "The outfit being assembled so far:\n<outfit>\n{{var.outfit}}\n</outfit>\n\n"
    "Come up with a fitting value for this one garment slot: {{var.slot}}.\n"
    "Keep it consistent with the character and the rest of the outfit. "
    "Output only the value itself — no preamble, no label, no quotes."
)

register("hoodat", "outfit.slot", title="Outfit (one slot)",
         prompt=OUTFIT_SLOT, tags=("outfit", "appearance"),
         description="Generate one garment slot, consistent with the character + outfit.")


# ---- avatar image prompt ---------------------------------------------------

# Written as flowing natural-language prose per FLUX.2 [klein] guidance (its
# Qwen3 text encoder reads sentences, not tag soup): subject → appearance →
# wardrobe → expression → photographic style → camera/lighting/technical, most
# important first, ~80 words, no negatives. Tuned for a realistic photographic
# head-and-shoulders portrait. The `_clause` variables are pre-assembled in
# `avatar_prompt_variables` so empty fields never leave dangling fragments.
AVATAR_IMAGE_PROMPT = (
    "A realistic photographic head-and-shoulders portrait of a {{var.age}} "
    "{{var.sex}} {{var.occupation}}, framed tightly from the chest up so the face "
    "fills most of the frame. They have {{var.hair}} hair, {{var.eyes}} eyes and "
    "{{var.skin}} skin, a {{var.build}} build, {{var.features_clause}}dressed in "
    "{{var.primary_outfit}}, looking toward the camera with a calm, natural "
    "expression. Shot on a Sony A7 IV with an 85mm f/1.8 portrait lens, soft "
    "directional studio light from the left, shallow depth of field, softly "
    "blurred neutral background, sharp focus on the eyes, lifelike skin texture "
    "and natural skin tones. Professional studio portrait photography, only the "
    "head and shoulders visible, highly detailed, true to life."
)

register("hoodat", "avatar.image_prompt", title="Avatar image prompt",
         prompt=AVATAR_IMAGE_PROMPT, tags=("avatar",),
         description="Templated ComfyUI image prompt built from the character's appearance.")


# ---- context rendering -----------------------------------------------------

# Appearance sub-groupings used when rendering / gating.
_NUDE_SHARED = ("body_hair", "pubic_hair", "buttocks", "lips", "hands", "feet")
_NUDE_MALE = ("penis", "testicles")
_NUDE_FEMALE = ("breasts", "vulva")
_NUDE_LABELS = {
    "body_hair": "body hair", "pubic_hair": "pubic hair", "buttocks": "buttocks",
    "lips": "lips", "hands": "hands", "feet": "feet", "penis": "penis",
    "testicles": "testicles", "breasts": "breasts", "vulva": "vulva",
}
_OUTFIT_SLOT_LABELS = {
    "top": "top", "bottoms": "bottoms", "underwear": "underwear",
    "socks_shoes": "socks & shoes", "accessories": "accessories",
}


def _render_appearance(app: dict, lines: list[str]) -> None:
    """Explicitly render the v2 `Appearance` block (nested dicts/lists need it)."""
    def emit(label: str, value) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{label}: {value}")

    emit("Height", app.get("height"))
    emit("Build", app.get("build"))
    emit("Skin", app.get("skin"))
    hair = " ".join(p for p in (app.get("hair_color"), app.get("hair_details")) if p)
    emit("Hair", hair)
    eyes = " ".join(p for p in (app.get("eye_color"), app.get("eye_details")) if p)
    emit("Eyes", eyes)
    emit("Distinguishing features", app.get("distinguishing_features"))

    # Nude details — only non-empty fields, so sex-irrelevant blanks never appear.
    nude = [(_NUDE_LABELS[f], app.get(f)) for f in (_NUDE_SHARED + _NUDE_MALE + _NUDE_FEMALE)]
    nude = [(lbl, val) for lbl, val in nude if val]
    if nude:
        lines.append("Nude details:")
        for lbl, val in nude:
            lines.append(f"  {lbl}: {val}")

    outfits = app.get("outfits") or []
    if outfits:
        lines.append("Outfits:")
        for i, o in enumerate(outfits, 1):
            parts = [f"{lbl}: {o.get(slot)}" for slot, lbl in _OUTFIT_SLOT_LABELS.items() if o.get(slot)]
            name = o.get("name") or f"Outfit {i}"
            tag = " (primary)" if o.get("primary") else ""
            detail = "; ".join(parts) if parts else "(no details)"
            lines.append(f"  {i}. {name}{tag} — {detail}")


def render_character_context(doc: dict) -> str:
    """Flatten a character doc into readable text for `{{var.character}}`."""
    lines: list[str] = []

    def emit(label: str, value) -> None:
        if value in (None, "", [], {}):
            return
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{label}: {value}")

    emit("Name", doc.get("name"))
    emit("Summary", doc.get("summary"))
    emit("Tagline", doc.get("tagline"))
    emit("Age", doc.get("age"))
    emit("Sex", doc.get("sex"))
    emit("Occupation", doc.get("occupation"))
    _render_appearance(doc.get("appearance") or {}, lines)
    for section in ("personality", "background", "speaking_style"):
        block = doc.get(section) or {}
        for field, value in block.items():
            # voice_preset_id is plumbing; dialogue_examples gets its own block.
            if field in ("voice_preset_id", "dialogue_examples"):
                continue
            emit(f"{section}.{field}", value)
    examples = ((doc.get("speaking_style") or {}).get("dialogue_examples")) or []
    if examples:
        lines.append("Dialogue examples:")
        for i, ex in enumerate(examples, 1):
            lines.append(f"  {i}. {ex}")
    pos, neg = experiences_split(doc)
    if pos:
        lines.append("Positive experiences:")
        lines.append(pos)
    if neg:
        lines.append("Negative experiences:")
        lines.append(neg)
    return "\n".join(lines) if lines else "(no details yet)"


def experiences_split(doc: dict) -> tuple[str, str]:
    """Return `(positive_text, negative_text)` — newline-bulleted experience
    descriptions split by valence, for `{{var.experiences_positive}}` /
    `{{var.experiences_negative}}`."""
    exps = doc.get("experiences") or []
    pos = [str(e.get("description") or "") for e in exps if e.get("valence") != "negative"]
    neg = [str(e.get("description") or "") for e in exps if e.get("valence") == "negative"]
    pos_text = "\n".join(f"- {d}" for d in pos if d.strip())
    neg_text = "\n".join(f"- {d}" for d in neg if d.strip())
    return pos_text, neg_text


def _primary_outfit_phrase(appearance: dict) -> str:
    """Assemble the avatar-facing outfit phrase from the primary outfit (fallback:
    first outfit). Joins the visible garment slots into one readable clause."""
    outfits = appearance.get("outfits") or []
    if not outfits:
        return ""
    chosen = next((o for o in outfits if o.get("primary")), outfits[0])
    # Underwear is irrelevant to a head-and-shoulders portrait; skip it.
    parts = [str(chosen.get(slot)).strip() for slot in ("top", "bottoms", "socks_shoes", "accessories")
             if str(chosen.get(slot) or "").strip()]
    return ", ".join(parts)


def avatar_prompt_variables(doc: dict) -> dict:
    """Flatten the fields the avatar image prompt references into `{{var.*}}`.

    Values carry sensible neutral fallbacks so a sparse character still yields a
    grammatical prompt. `age` and `features_clause` are pre-assembled (suffix /
    trailing punctuation included) so an empty field leaves no dangling fragment.
    `hair`/`eyes` combine the v2 color+details fields; `primary_outfit` is built
    from the primary outfit's garment slots.
    """
    appearance = doc.get("appearance") or {}
    feats = [str(f) for f in (appearance.get("distinguishing_features") or []) if str(f).strip()]
    age = doc.get("age")
    hair = " ".join(p for p in (appearance.get("hair_color"), appearance.get("hair_details")) if p).strip()
    eyes = " ".join(p for p in (appearance.get("eye_color"), appearance.get("eye_details")) if p).strip()
    return {
        "age": f"{age}-year-old" if age else "adult",
        "sex": str(doc.get("sex") or "person"),
        "occupation": str(doc.get("occupation") or "").strip(),
        "build": str(appearance.get("build") or "average"),
        "hair": hair or "short",
        "eyes": eyes or "brown",
        "skin": str(appearance.get("skin") or "fair"),
        "primary_outfit": _primary_outfit_phrase(appearance) or "simple everyday clothing",
        # full clause incl. trailing ", " so the template reads cleanly when empty
        "features_clause": (", ".join(feats) + ", ") if feats else "",
    }
