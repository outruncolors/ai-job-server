"""Registry of cruddable adapters, keyed by ``type_name``.

Adapters are added here as each domain store is migrated to the envelope format.
"""

from __future__ import annotations

from .adapters.chain_sequence import ChainSequenceAdapter
from .adapters.context_item import ContextItemAdapter
from .adapters.hoodat_character import HoodatCharacterAdapter
from .adapters.image_prompt import ImagePromptAdapter
from .adapters.prompt_pal import PromptPalAdapter
from .adapters.wildcard import WildcardAdapter
from .base import CruddableAdapter

_ADAPTERS: list[CruddableAdapter] = [
    WildcardAdapter(),
    ContextItemAdapter(),
    ImagePromptAdapter(),
    ChainSequenceAdapter(),
    PromptPalAdapter(),
    HoodatCharacterAdapter(),
]

REGISTRY: dict[str, CruddableAdapter] = {a.type_name: a for a in _ADAPTERS}


def get_adapter(type_name: str) -> CruddableAdapter | None:
    return REGISTRY.get(type_name)


def list_types() -> list[dict]:
    """`[{type,label,count}]` for the Cruddables page."""
    return [
        {"type": a.type_name, "label": a.label, "count": a.count()}
        for a in _ADAPTERS
    ]
