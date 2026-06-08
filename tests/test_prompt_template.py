"""The unified prompt resolver (``app.prompt_template.render``).

Covers the three namespaces, legacy ``%%`` reading, the inert-vs-rescan rule,
the ``final`` literal-fallback, cycle/depth safety, and substitution tracking.
Maps are passed explicitly (no store I/O) except the lazy-load test.
"""

from __future__ import annotations

import random

from app import wildcards as wildcard_store
from app.prompt_template import render


def _wc(name, entries):
    return {"name": name, "data": {"entries": entries}}


def _wc_map(*envs):
    return {(e["name"] or "").lower(): e for e in envs}


def _ctx(slug, name, content, *, description="", tags=()):
    return {
        "id": slug, "name": name, "description": description,
        "tags": list(tags), "data": {"content": content},
    }


def _ctx_map(*envs):
    m = {}
    for e in envs:
        if e.get("name"):
            m.setdefault(e["name"].lower(), e)
    for e in envs:
        if e.get("id"):
            m[e["id"]] = e
    return m


# --- chain tokens (unchanged behavior) --------------------------------------

def test_chain_tokens_resolve_as_before():
    out = render(
        "{{input}}|{{previous}}|{{context}}|{{step_index}}|{{step_name}}|{{2_output}}",
        input="IN", previous="PREV", context="CTX", step_index=3, step_name="S",
        step_outputs={2: ["o2"]},
    ).text
    assert out == "IN|PREV|CTX|3|S|o2"


def test_extra_token_resolves_and_unknown_brace_empties_when_final():
    assert render("{{memory}} {{bogus}}", extra={"memory": "M"}).text == "M "


def test_unknown_brace_left_intact_when_not_final():
    assert render("{{bogus}}", final=False).text == "{{bogus}}"


# --- wildcards (new spelling + legacy) --------------------------------------

def test_wc_namespace_and_legacy_percent_resolve_the_same():
    wcs = _wc_map(_wc("Mood", [{"text": "grumpy"}]))
    assert render("a {{wc.Mood}} b", wildcards=wcs).text == "a grumpy b"
    assert render("a %%Mood%% b", wildcards=wcs).text == "a grumpy b"


def test_wc_is_case_insensitive_and_unknown_is_literal():
    wcs = _wc_map(_wc("Greeting", [{"text": "hey"}]))
    assert render("{{wc.greeting}}", wildcards=wcs).text == "hey"
    assert render("{{wc.nope}}", wildcards=wcs).text == "{{wc.nope}}"
    assert render("%%nope%%", wildcards=wcs).text == "%%nope%%"


def test_wc_weight_dominates():
    wcs = _wc_map(_wc("Pick", [{"text": "rare", "weight": 1}, {"text": "common", "weight": 1000}]))
    rng = random.Random(1234)
    picks = [render("{{wc.Pick}}", wildcards=wcs, rng=rng).text for _ in range(200)]
    assert picks.count("common") > 180


def test_mixed_wc_and_legacy_nesting():
    wcs = _wc_map(
        _wc("Inner", [{"text": "world"}]),
        _wc("Outer", [{"text": "hello %%Inner%%"}]),          # legacy ref inside new
        _wc("Outer2", [{"text": "hi {{wc.Inner}}"}]),          # new ref inside legacy-callable
    )
    assert render("{{wc.Outer}}", wildcards=wcs).text == "hello world"
    assert render("%%Outer2%%", wildcards=wcs).text == "hi world"


def test_wc_cycle_left_literal():
    wcs = _wc_map(_wc("A", [{"text": "a then %%B%%"}]), _wc("B", [{"text": "b then %%A%%"}]))
    out = render("%%A%%", wildcards=wcs).text
    assert out.startswith("a then b then")
    assert "%%A%%" in out


# --- variables --------------------------------------------------------------

def test_var_in_scope_uses_value():
    assert render("{{var.tone}}", variables={"tone": "wry"}).text == "wry"


def test_var_missing_falls_back_to_literal_when_final():
    assert render("{{var.foo}}", variables={}).text == "foo"


def test_var_missing_left_intact_when_not_final():
    assert render("{{var.foo}}", variables={}, final=False).text == "{{var.foo}}"


# --- context ----------------------------------------------------------------

def test_ctx_by_slug_and_by_name():
    ctxs = _ctx_map(_ctx("my-lore", "My Lore", "the realm of X"))
    assert render("{{ctx.my-lore}}", context_items=ctxs).text == "the realm of X"
    assert render("{{ctx.My Lore}}", context_items=ctxs).text == "the realm of X"


def test_ctx_missing_literal_when_final_intact_otherwise():
    assert render("{{ctx.nope}}", context_items={}).text == "nope"
    assert render("{{ctx.nope}}", context_items={}, final=False).text == "{{ctx.nope}}"


def test_ctx_content_is_rescanned():
    ctxs = _ctx_map(_ctx("lore", "Lore", "realm of %%Mood%% and {{var.who}}"))
    wcs = _wc_map(_wc("Mood", [{"text": "doom"}]))
    out = render("{{ctx.lore}}", context_items=ctxs, wildcards=wcs, variables={"who": "us"}).text
    assert out == "realm of doom and us"


# --- the inert-vs-rescan rule (anti-injection) ------------------------------

def test_wildcard_expansion_is_rescanned_for_var():
    wcs = _wc_map(_wc("Greet", [{"text": "hi {{var.name}}"}]))
    assert render("{{wc.Greet}}", wildcards=wcs, variables={"name": "bob"}).text == "hi bob"


def test_runtime_data_is_inert():
    wcs = _wc_map(_wc("Mood", [{"text": "doom"}]))
    # previous / input / var-value containing tokens must NOT expand
    assert render("{{previous}}", previous="evil %%Mood%%", wildcards=wcs).text == "evil %%Mood%%"
    assert render("{{var.x}}", variables={"x": "%%Mood%%"}, wildcards=wcs).text == "%%Mood%%"
    assert render("{{memory}}", extra={"memory": "{{wc.Mood}}"}, wildcards=wcs).text == "{{wc.Mood}}"


# --- tracking ---------------------------------------------------------------

def test_track_records_substitutions_in_order():
    wcs = _wc_map(_wc("Mood", [{"text": "doom"}]))
    res = render("{{var.a}} {{wc.Mood}}", variables={"a": "X"}, wildcards=wcs, track=True)
    assert res.text == "X doom"
    assert [(s.token, s.value) for s in res.substitutions] == [
        ("{{var.a}}", "X"), ("{{wc.Mood}}", "doom"),
    ]


# --- lazy store load --------------------------------------------------------

def test_lazy_loads_wildcard_store(tmp_path, monkeypatch):
    monkeypatch.setattr(wildcard_store, "_DIR", tmp_path / "wildcards")
    monkeypatch.setattr(wildcard_store, "_INDEX_PATH", tmp_path / "wildcards" / "index.json")
    wildcard_store.create_wildcard("Mood", [{"text": "sunny"}])
    assert render("today is {{wc.Mood}}").text == "today is sunny"
    assert render("today is %%Mood%%").text == "today is sunny"
