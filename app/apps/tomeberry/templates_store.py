"""Global starter templates (``tomeberry_template`` cruddable).

Concepts live in tale folders, but *templates* are server-wide globals (B8): a
template is a bundle of concept records that ``apply-template`` copies into a tale's
``concepts/``. Stored envelope-native (file-per-doc) under
``config/tomeberry/templates/`` so it's covered by the same gitignore + test
isolation as tales. Three builtins are seeded if absent.

Template ``data`` shape::

    { "concepts": [ {ref, parent_ref, concept_class, type, title, body, order, links} ] }

``ref``/``parent_ref`` are symbolic (resolved to real ids on apply); ``parent_ref``
of ``"root"``/null parents a structural unit to the tale's structural root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from . import store as tale_store


def _dir() -> Path:
    return tale_store.TOMEBERRY_DIR / "templates"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _su(ref, parent_ref, type_, title, order):
    return {
        "ref": ref, "parent_ref": parent_ref, "concept_class": "structural_unit",
        "type": type_, "title": title, "body": "", "order": order, "links": [],
    }


BUILTIN_TEMPLATES: list[dict] = [
    {
        "schema_version": 1, "type": "tomeberry_template", "id": "three_act",
        "name": "Three-act skeleton", "description": "Setup / Confrontation / Resolution with a scene each.",
        "tags": ["Pack", "tomeberry", "structure"],
        "data": {"concepts": [
            _su("a1", "root", "part", "Act One — Setup", 0),
            _su("a1s1", "a1", "scene", "Opening image", 0),
            _su("a2", "root", "part", "Act Two — Confrontation", 1),
            _su("a2s1", "a2", "scene", "Midpoint", 0),
            _su("a3", "root", "part", "Act Three — Resolution", 2),
            _su("a3s1", "a3", "scene", "Climax", 0),
        ]},
    },
    {
        "schema_version": 1, "type": "tomeberry_template", "id": "heros_journey",
        "name": "Hero's journey beat sheet", "description": "Twelve classic beats as structural units.",
        "tags": ["Pack", "tomeberry", "structure"],
        "data": {"concepts": [
            _su(f"b{i}", "root", "beat", title, i)
            for i, title in enumerate([
                "Ordinary World", "Call to Adventure", "Refusal of the Call",
                "Meeting the Mentor", "Crossing the Threshold", "Tests, Allies, Enemies",
                "Approach to the Inmost Cave", "The Ordeal", "Reward", "The Road Back",
                "Resurrection", "Return with the Elixir",
            ])
        ]},
    },
    {
        "schema_version": 1, "type": "tomeberry_template", "id": "character_sheet",
        "name": "Character sheet", "description": "A story-entity template with prompts to fill in.",
        "tags": ["Pack", "tomeberry", "entity"],
        "data": {"concepts": [
            {
                "ref": "char", "parent_ref": None, "concept_class": "story_entity",
                "type": "character", "title": "New character", "order": 0, "links": [],
                "body": (
                    "Role:\nWant (external goal):\nNeed (internal lesson):\n"
                    "Wound / backstory:\nVoice & mannerisms:\nArc:\n"
                ),
            },
        ]},
    },
]


def seed_builtins() -> None:
    """Write the builtin templates if absent (seed-if-absent; never clobbers edits)."""
    d = _dir()
    for tpl in BUILTIN_TEMPLATES:
        path = d / f"{tpl['id']}.json"
        if not path.exists():
            _atomic_write(path, tpl)


def list_templates() -> list[dict]:
    seed_builtins()
    d = _dir()
    out: list[dict] = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def get_template(template_id: str) -> Optional[dict]:
    seed_builtins()
    f = _dir() / f"{template_id}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def upsert_envelope(env: dict) -> tuple[str, str]:
    eid = env.get("id") or "template"
    _atomic_write(_dir() / f"{eid}.json", env)
    return (eid, "upserted")


def delete_template(template_id: str) -> bool:
    f = _dir() / f"{template_id}.json"
    if f.exists():
        f.unlink()
        return True
    return False
