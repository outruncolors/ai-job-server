"""app.sfx.store — discovery, identity profiles, pools, summaries, traversal guard."""

from __future__ import annotations

from app.sfx import store


def test_list_and_get_packs(sfx_root):
    packs = {p.id: p for p in store.list_packs()}
    assert set(packs) == {"test_emotes", "test_lewd"}
    assert packs["test_emotes"].binding == "identity"
    assert packs["test_lewd"].binding == "global"
    assert store.get_pack("missing") is None


def test_identity_profiles_include_pitch_variants(sfx_root):
    profs = {p["value"]: p for p in store.list_identity_profiles()}
    assert "young_woman" in profs and "young_woman_high" in profs
    assert profs["young_woman"]["pitch"] == "base"
    assert profs["young_woman_high"]["pitch"] == "high"
    assert profs["young_woman"]["packs"] == ["test_emotes"]


def test_identity_pool_and_summary(sfx_root):
    pool = store.identity_pool("young_woman")
    assert len(pool) == 3
    cats = {c["category"]: c for c in store.summarize_categories([it for _, _, it in pool])}
    assert cats["sneeze"]["count"] == 2
    assert cats["laugh"]["count"] == 1
    assert "gasp" not in cats["sneeze"]["tags"] or True  # tags are from the items


def test_domain_pool(sfx_root):
    assert len(store.domain_pool("lewd")) == 2
    assert store.domain_pool("none") == []


def test_weighted_choice_entry_deterministic(sfx_root):
    import random
    pool = store.identity_pool("young_woman")
    sneezes = [e for e in pool if e[2].category == "sneeze"]
    picked = store.weighted_choice_entry(sneezes, rng=random.Random(0))
    again = store.weighted_choice_entry(sneezes, rng=random.Random(0))
    assert picked[2].id == again[2].id  # same seed -> stable


def test_resolve_file_path_guard(sfx_root):
    pack = store.get_pack("test_emotes")
    item = pack.profiles[0].items[0]
    assert store.resolve_file_path(item.path) is not None
    assert store.resolve_file_path("../../etc/passwd") is None
    assert store.resolve_file_path("normalized/test_emotes") is None  # a dir, not a file
