"""Tomeberry prompt library — a Shared Base + 10 mode prompts (Prompt Pal).

The system/developer block for a request is
``get_text("tomeberry","base", vars) + get_text("tomeberry","mode."+mode, vars)``.
Compose resolves ``{{var.*}}`` at assembly time; the chain's ``render(final=True)``
finishes the job at execution. ``author_instruction`` sits near the **end** of the
mode prompt (Gemma responds best to the operative instruction last).

The variable *values* are self-labeling (see ``generator.build_mode_variables``): an
empty section renders to ``""`` so the prompt never carries placeholder noise.

``MODE_SPECS`` is the canonical per-mode contract (B4): output_format / change_policy
/ what it proposes / which MCP tools it may use. The generator reads it to wire each
turn; ``OUTPUT_FORMAT_TEXT`` / ``CHANGE_POLICY_TEXT`` turn the keys into directive
text injected as ``{{var.output_format}}`` / ``{{var.change_policy}}``.
"""

from __future__ import annotations

from ...prompt_pal.registry import register

PROMPT_VERSION = 1

# ---- the 14-variable contract → per-mode spec ------------------------------

MODE_SPECS: dict[str, dict] = {
    "discover": {"group": "Create", "output_format": "ideas", "change_policy": "suggest_only", "proposes": "chat", "mcp_tools": []},
    "organize": {"group": "Shape", "output_format": "structure_ops", "change_policy": "propose_structure_ops", "proposes": "structure_ops", "mcp_tools": []},
    "draft": {"group": "Create", "output_format": "prose", "change_policy": "propose_replace_or_insert", "proposes": "manuscript_diff", "mcp_tools": ["fs__read_file", "fs__list_directory"]},
    "revise": {"group": "Shape", "output_format": "revised_text", "change_policy": "propose_replace", "proposes": "manuscript_diff", "mcp_tools": []},
    "edit": {"group": "Check", "output_format": "revised_text", "change_policy": "propose_replace", "proposes": "manuscript_diff", "mcp_tools": []},
    "diagnose": {"group": "Check", "output_format": "critique", "change_policy": "explain_only", "proposes": "chat", "mcp_tools": []},
    "develop": {"group": "Create", "output_format": "entity_record", "change_policy": "create_or_update_concept", "proposes": "concept_upsert", "mcp_tools": ["fs__read_file", "fs__list_directory"]},
    "track": {"group": "Check", "output_format": "labeled_extraction", "change_policy": "extract_to_concepts", "proposes": "concept_creates", "mcp_tools": ["fs__read_file"]},
    "plan": {"group": "Shape", "output_format": "outline", "change_policy": "propose_structure_ops", "proposes": "structure_ops", "mcp_tools": ["fs__write_file"]},
    "publish": {"group": "Finish", "output_format": "prose", "change_policy": "propose_replace", "proposes": "manuscript_diff", "mcp_tools": ["fs__write_file"]},
}

# output_format keys whose model output is JSON (parsed via chain.structured).
JSON_OUTPUT_FORMATS = {"entity_record", "labeled_extraction", "structure_ops"}

OUTPUT_FORMAT_TEXT: dict[str, str] = {
    "prose": "OUTPUT: Return ONLY the prose itself — no headings, labels, quotes, or commentary.",
    "ideas": "OUTPUT: Return a short, scannable list of distinct ideas or options. No prose padding.",
    "critique": "OUTPUT: Return a focused critique — concrete observations, not a rewrite.",
    "revised_text": 'OUTPUT: Return strict JSON: {"revised_text": "<full revised text>", "summary": "<one-line note>"}.',
    "entity_record": 'OUTPUT: Return strict JSON for one concept: {"concept_class": "...", "type": "...", "title": "...", "body": "...", "links": [{"rel":"...","target_id":"..."}]}.',
    "labeled_extraction": 'OUTPUT: Return strict JSON: {"concepts": [{"concept_class": "...", "type": "...", "title": "...", "body": "..."}]}. Extract only what the text states.',
    "structure_ops": 'OUTPUT: Return strict JSON: {"ops": [{"op": "add|move|link", "type": "...", "title": "...", "parent_id": "...", "rel": "...", "target_id": "..."}]}.',
    "outline": "OUTPUT: Return a clear, hierarchical outline (use indentation or numbering).",
}

CHANGE_POLICY_TEXT: dict[str, str] = {
    "suggest_only": "POLICY: Suggest only. Do not rewrite the manuscript; offer options for the author to choose.",
    "explain_only": "POLICY: Explain only. Diagnose and advise; never rewrite the text yourself.",
    "propose_replace": "POLICY: Propose a replacement of the in-scope text. The author accepts or rejects it.",
    "propose_replace_or_insert": "POLICY: Propose new or replacement prose for the current unit. The author accepts or rejects it.",
    "propose_structure_ops": "POLICY: Propose structural operations (add/move/link). The author applies them.",
    "create_or_update_concept": "POLICY: Propose creating or updating one concept record. The author accepts it.",
    "extract_to_concepts": "POLICY: Extract facts already present in the text into concept records. Do not invent.",
}


# ---- prompt text -----------------------------------------------------------

BASE = """\
You are Tomeberry, a meticulous AI co-author working on the tale titled "{{var.tale_title}}".
You collaborate with a human author inside a two-pane writing studio. Be concrete, concise,
and faithful to the author's intent and the tale's established canon. Never contradict
established facts. Do not add meta-commentary, apologies, or instructions to the user.

{{var.premise}}
{{var.project_context}}
{{var.current_structural_unit}}
{{var.conversation_context}}

You are operating in {{var.mode}} mode (active pane: {{var.active_pane}}).
{{var.change_policy}}
{{var.output_format}}
"""

MODE_PROMPTS: dict[str, str] = {
    "discover": """\
DISCOVER — help the author find ideas. Brainstorm premises, what-ifs, characters,
settings, twists, or directions that fit the tale so far. Offer a handful of distinct,
specific options the author can pick from. Stay generative, not prescriptive.

{{var.request_context}}
{{var.saved_prompt}}

AUTHOR REQUEST:
{{var.author_instruction}}
""",
    "organize": """\
ORGANIZE — shape the tale's structure. Propose how to arrange parts/chapters/scenes
or how concepts relate. Return structural operations the author can apply.

{{var.request_context}}
{{var.saved_prompt}}

AUTHOR REQUEST:
{{var.author_instruction}}
""",
    "draft": """\
DRAFT — write new prose for the current unit. Continue or realize it in the tale's
voice, vivid and publishable. Use any provided file tools to read referenced material
in the workspace before writing. Replace the selection if one is given, otherwise write
the unit's body.

{{var.current_text}}
{{var.selected_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
    "revise": """\
REVISE — improve the substance of the in-scope text: pacing, clarity, tension, logic,
characterization. Keep the author's voice. Return the revised text plus a one-line note
on what you changed and why.

{{var.selected_text}}
{{var.current_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
    "edit": """\
EDIT — line-edit the in-scope text for expression only: grammar, word choice, rhythm,
typos. Do NOT change substance, plot, or meaning. Return the edited text plus a one-line
summary.

{{var.selected_text}}
{{var.current_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
    "diagnose": """\
DIAGNOSE — read the in-scope text critically and explain what is or isn't working:
plot holes, weak motivation, inconsistencies, pacing, unclear prose. Be specific and
actionable. Do not rewrite — diagnose only.

{{var.selected_text}}
{{var.current_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR REQUEST:
{{var.author_instruction}}
""",
    "develop": """\
DEVELOP — flesh out a story entity or narrative construct (character, place, arc, etc.)
into a structured concept record. Read referenced workspace files if useful. Stay
consistent with established canon.

{{var.selected_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
    "track": """\
TRACK — extract concrete facts the text already states (who/what/where, relationships,
established details) into concept records. Favor extraction over invention; record only
what is on the page.

{{var.selected_text}}
{{var.current_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
    "plan": """\
PLAN — produce a plan or outline for what to write next: beats, tasks, or a chapter
breakdown. You may write the plan to a workspace file if asked. Keep it actionable.

{{var.current_structural_unit}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
    "publish": """\
PUBLISH — prepare the in-scope text for an external audience: a clean, final pass, or
an export artifact (blurb, synopsis, formatted chapter). You may write the artifact to a
workspace file if asked. Aim for polish.

{{var.selected_text}}
{{var.current_text}}
{{var.request_context}}
{{var.saved_prompt}}

AUTHOR INSTRUCTION:
{{var.author_instruction}}
""",
}


def register_all() -> None:
    """Register the base + 10 mode prompts with Prompt Pal (idempotent)."""
    register(
        "tomeberry",
        "base",
        title="Shared base prompt",
        prompt=BASE,
        tags=("tomeberry", "base"),
        description="Co-author role + tale context shared by every Tomeberry mode.",
    )
    for mode, text in MODE_PROMPTS.items():
        spec = MODE_SPECS[mode]
        register(
            "tomeberry",
            f"mode.{mode}",
            title=f"Mode — {mode.capitalize()} ({spec['group']})",
            prompt=text,
            tags=("tomeberry", "mode", spec["group"].lower()),
            description=f"{mode.capitalize()} mode: {spec['output_format']} / {spec['change_policy']}.",
        )


def build_pack() -> dict:
    """Build a Pack doc shipping the base + mode prompts as prompt_pal envelopes."""
    from ...cruddables.envelope import now_iso, slugify

    items = []
    entries = [("base", "Shared base prompt", BASE)] + [
        (f"mode.{m}", f"Mode — {m.capitalize()}", t) for m, t in MODE_PROMPTS.items()
    ]
    for key, title, text in entries:
        items.append(
            {
                "schema_version": 1,
                "type": "prompt_pal",
                "id": slugify(f"tomeberry_{key}"),
                "name": title,
                "description": f"Tomeberry {key} prompt.",
                "tags": ["Pack", "tomeberry"],
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "data": {"app": "tomeberry", "key": key, "prompt": text, "variables": {}, "guard": None},
            }
        )
    return {
        "id": "tomeberry_modes",
        "name": "Tomeberry mode prompts",
        "description": "The Shared Base + 10 mode prompts that drive Tomeberry's co-author.",
        "tags": ["Pack", "tomeberry", "prompt"],
        "items": items,
    }


# Register at import so seed_registered() (lifespan) writes them to the store.
register_all()
