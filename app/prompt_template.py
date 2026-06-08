"""The one prompt-templating engine, shared by every prompt-bearing surface.

A single :func:`render` resolves ``{{...}}`` tokens (and legacy ``%%name%%``) in one
pass. Three namespaces plus the chain tokens:

  - ``{{var.NAME}}``  -> caller variable ``NAME`` if in scope, else (when ``final``)
                         the literal string ``NAME``.
  - ``{{wc.NAME}}``   -> wildcard ``NAME`` (weighted-random pick, recursive, cycle-safe).
                         ``%%NAME%%`` is read as a legacy alias of the same thing.
  - ``{{ctx.NAME}}``  -> full content of the context item named/slugged ``NAME`` if it
                         exists, else (when ``final``) the literal string ``NAME``.
  - chain tokens      -> ``{{input}}`` / ``{{previous}}`` / ``{{context}}`` /
                         ``{{step_index}}`` / ``{{step_name}}`` / ``{{N_input}}`` /
                         ``{{N_output}}`` and any key in ``extra`` (e.g. ``{{memory}}``).

**Re-scan rule (anti-injection).** Everything runs through one :func:`re.Match`-driven
``re.sub`` pass; ``re.sub`` never re-scans the text it substitutes in. We exploit that:
values that come from *runtime data* (chain ``input``/``previous``/``N_output``, ``extra``
/memory, and resolved ``var.`` values) are substituted **inertly** and never re-expanded,
so model output or a user variable containing ``%%evil%%`` cannot inject tokens. Values
that come from *author-controlled libraries* (wildcards, context bodies) are recursed into,
so a wildcard may reference ``{{var.tone}}`` / ``{{ctx.lore}}`` / other wildcards.

The two-stage Prompt Pal flow lives elsewhere: :func:`app.prompt_pal.compose.compose` is
stage-1 (var-only, leaves wc/ctx/unknown intact, never literal-fills) and is always
non-final; this module's ``render(final=True)`` is the stage-2 resolver at execution.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Optional

# Brace tokenizer (exported for compose's narrow stage-1 pass).
_TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# Combined single-pass matcher: a brace token (group 1) OR a legacy %%wildcard%%
# (group 2). One pass over the original text; replacements are not re-scanned.
_COMBINED_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}|%%([^%\n]+)%%")

_MAX_DEPTH = 16
_DEFAULT_WEIGHT = 5


@dataclass(frozen=True)
class Substitution:
    token: str  # the literal "{{wc.foo}}" / "%%foo%%" / "{{var.x}}" matched
    value: str  # what it expanded to


@dataclass
class RenderResult:
    text: str
    substitutions: list[Substitution] = field(default_factory=list)


# --- data helpers -----------------------------------------------------------

def _wildcard_entries(env: Optional[dict]) -> list[dict]:
    return (env.get("data") or {}).get("entries") or [] if env else []


def _context_content(env: dict) -> str:
    return (env.get("data") or {}).get("content") or ""


def _load_wildcard_map() -> dict[str, dict]:
    from app import wildcards as _wc
    return {(it.get("name") or "").lower(): it for it in _wc.list_wildcards()}


def _load_context_map() -> dict[str, dict]:
    """Map both slug-id and lowercased name -> envelope (slug wins on collision)."""
    from app.chain import context_library as _ctx
    out: dict[str, dict] = {}
    for it in _ctx.list_items():
        name = (it.get("name") or "").lower()
        if name:
            out.setdefault(name, it)
    for it in _ctx.list_items():
        slug = it.get("id") or ""
        if slug:
            out[slug] = it
    return out


def _pick_weighted(entries: list[dict], rng) -> str:
    texts = [e.get("text") or "" for e in entries]
    weights = [w if (w := e.get("weight")) else _DEFAULT_WEIGHT for e in entries]
    if not texts:
        return ""
    total = sum(weights)
    if total <= 0:
        return rng.choice(texts)
    return rng.choices(texts, weights=weights, k=1)[0]


# --- resolver ---------------------------------------------------------------

def render(
    template: str,
    *,
    input: str = "",
    previous: str = "",
    context: str = "",
    step_index: int = 0,
    step_name: str = "",
    step_inputs: Optional[dict[int, list[str]]] = None,
    step_outputs: Optional[dict[int, list[str]]] = None,
    variables: Optional[dict[str, str]] = None,
    extra: Optional[dict[str, str]] = None,
    wildcards: Optional[dict[str, dict]] = None,
    context_items: Optional[dict[str, dict]] = None,
    final: bool = True,
    track: bool = False,
    rng=None,
) -> RenderResult:
    """Resolve ``template`` to its final text. See module docstring.

    ``wildcards`` / ``context_items`` override the lazy store load (tests, batch use).
    ``final`` controls var/ctx literal-fallback (literal when True, token left intact when
    False). ``track`` collects the per-token substitutions. ``rng`` is injectable for
    deterministic tests.
    """
    step_inputs = step_inputs or {}
    step_outputs = step_outputs or {}
    variables = variables or {}
    extra = extra or {}
    rng = rng or random
    subs: list[Substitution] = []

    _wc_map = wildcards
    _ctx_map = context_items

    def wc_map() -> dict[str, dict]:
        nonlocal _wc_map
        if _wc_map is None:
            _wc_map = _load_wildcard_map()
        return _wc_map

    def ctx_map() -> dict[str, dict]:
        nonlocal _ctx_map
        if _ctx_map is None:
            _ctx_map = _load_context_map()
        return _ctx_map

    def _track(token: str, value: str) -> str:
        if track:
            subs.append(Substitution(token, value))
        return value

    def _last(values: list[str]) -> str:
        return values[-1] if values else ""

    def _chain_token(token: str) -> tuple[bool, str]:
        """Resolve an inert chain/extra token. Returns (matched, value)."""
        if token == "input":
            return True, input
        if token == "previous":
            return True, previous
        if token == "context":
            return True, context
        if token == "step_index":
            return True, str(step_index)
        if token == "step_name":
            return True, step_name
        if token in extra:
            return True, extra[token]
        m = re.fullmatch(r"(\d+)_(input|output)", token)
        if m:
            n = int(m.group(1))
            store = step_inputs if m.group(2) == "input" else step_outputs
            return True, _last(store.get(n, []))
        return False, ""

    def _resolve(text: str, wc_visiting: frozenset, ctx_visiting: frozenset, depth: int) -> str:
        if not text or depth >= _MAX_DEPTH:
            return text
        if "{{" not in text and "%%" not in text:
            return text

        def repl(m: "re.Match[str]") -> str:
            whole = m.group(0)
            legacy = m.group(2)
            if legacy is not None:
                return _expand_wc(legacy, whole, wc_visiting, ctx_visiting, depth)
            token = m.group(1)
            if token.startswith("wc."):
                return _expand_wc(token[3:], whole, wc_visiting, ctx_visiting, depth)
            if token.startswith("var."):
                return _expand_var(token[4:], whole)
            if token.startswith("ctx."):
                return _expand_ctx(token[4:], whole, wc_visiting, ctx_visiting, depth)
            matched, value = _chain_token(token)
            if matched:
                return _track(whole, value)  # inert runtime data
            return _track(whole, "") if final else whole  # unknown brace token

        return _COMBINED_RE.sub(repl, text)

    def _expand_wc(name: str, whole: str, wc_visiting, ctx_visiting, depth: int) -> str:
        key = name.strip().lower()
        entries = _wildcard_entries(wc_map().get(key))
        if not entries or key in wc_visiting:
            return whole  # unknown or cyclic -> leave the token literal
        picked = _pick_weighted(entries, rng)
        value = _resolve(picked, wc_visiting | {key}, ctx_visiting, depth + 1)
        return _track(whole, value)

    def _expand_var(name: str, whole: str) -> str:
        key = name.strip()
        if key in variables:
            v = variables[key]
            return _track(whole, "" if v is None else str(v))  # inert
        if final:
            return _track(whole, key)  # literal fallback
        return whole  # leave intact for a later stage

    def _expand_ctx(name: str, whole: str, wc_visiting, ctx_visiting, depth: int) -> str:
        key = name.strip()
        env = ctx_map().get(key) or ctx_map().get(key.lower())
        if env is None:
            if final:
                return _track(whole, key)
            return whole
        slug = env.get("id") or key
        if slug in ctx_visiting:
            return whole  # cyclic ctx reference -> literal
        value = _resolve(_context_content(env), wc_visiting, ctx_visiting | {slug}, depth + 1)
        return _track(whole, value)

    text = _resolve(template, frozenset(), frozenset(), 0)
    return RenderResult(text=text, substitutions=subs)


def render_template(
    template: str,
    *,
    input: str = "",
    previous: str = "",
    context: str = "",
    step_index: int = 0,
    step_name: str = "",
    step_inputs: Optional[dict[int, list[str]]] = None,
    step_outputs: Optional[dict[int, list[str]]] = None,
    variables: Optional[dict[str, str]] = None,
    extra: Optional[dict[str, str]] = None,
) -> str:
    """Back-compat string wrapper: ``render(..., final=True).text``."""
    return render(
        template,
        input=input,
        previous=previous,
        context=context,
        step_index=step_index,
        step_name=step_name,
        step_inputs=step_inputs,
        step_outputs=step_outputs,
        variables=variables,
        extra=extra,
        final=True,
        track=False,
    ).text
