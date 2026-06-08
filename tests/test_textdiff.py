"""Phase 1 — textdiff make/apply/render + drift + store + routes."""

from __future__ import annotations

import pytest

from app.textdiff import (
    ConflictError,
    apply_proposal,
    make_proposal,
    render_inline,
)
from app.textdiff import store


def test_make_proposal_is_content_addressed():
    p1 = make_proposal("the cat sat", "the dog sat")
    p2 = make_proposal("the cat sat", "the dog sat")
    p3 = make_proposal("the cat sat", "the cat ran")
    assert p1.id == p2.id
    assert p1.id != p3.id
    assert p1.before == "the cat sat"
    assert p1.after == "the dog sat"


def test_full_accept_returns_after():
    p = make_proposal("hello world", "hello brave world")
    assert apply_proposal("hello world", p) == "hello brave world"


def test_apply_detects_drift():
    p = make_proposal("original text", "edited text")
    with pytest.raises(ConflictError):
        apply_proposal("something totally different now", p)


def test_apply_force_overrides_drift():
    p = make_proposal("original text", "edited text")
    # force returns the proposal's after regardless of current
    assert apply_proposal("drifted", p, force=True) == "edited text"


def test_hunk_level_accept():
    before = "alpha beta gamma"
    after = "ALPHA beta GAMMA"
    p = make_proposal(before, after)
    change_idxs = [i for i, h in enumerate(p.hunks) if h.op != "equal"]
    assert len(change_idxs) >= 2
    # accept only the first change hunk → only that word changes
    out = apply_proposal(before, p, accept_hunks=[change_idxs[0]])
    assert out != before and out != after
    assert "ALPHA" in out
    assert "GAMMA" not in out  # second change not accepted
    # accept all change hunks → equals full after
    assert apply_proposal(before, p, accept_hunks=change_idxs) == after


def test_render_inline_segments():
    p = make_proposal("the cat sat", "the dog sat")
    segs = render_inline(p)
    kinds = [s.kind for s in segs]
    assert "insert" in kinds
    assert "delete" in kinds
    # reconstructing equal+delete must give back 'before'
    rebuilt = "".join(s.text for s in segs if s.kind in ("equal", "delete"))
    assert rebuilt == "the cat sat"
    rebuilt_after = "".join(s.text for s in segs if s.kind in ("equal", "insert"))
    assert rebuilt_after == "the dog sat"


def test_insert_only_and_delete_only():
    ins = make_proposal("a c", "a b c")
    assert apply_proposal("a c", ins) == "a b c"
    dele = make_proposal("a b c", "a c")
    assert apply_proposal("a b c", dele) == "a c"


def test_store_roundtrip():
    p = make_proposal("x", "y")
    store.save_proposal("tomeberry", "tale_1/scene_2", p)
    got = store.get_proposal("tomeberry", "tale_1/scene_2", p.id)
    assert got is not None and got.after == "y"
    assert any(q.id == p.id for q in store.list_proposals("tomeberry", "tale_1/scene_2"))
    assert store.delete_proposal("tomeberry", "tale_1/scene_2", p.id) is True
    assert store.get_proposal("tomeberry", "tale_1/scene_2", p.id) is None


def test_routes(client):
    r = client.post("/v1/textdiff/make", json={"before": "one two", "after": "one three"})
    assert r.status_code == 200
    body = r.json()
    pid = body["proposal"]["id"]
    assert any(s["kind"] == "insert" for s in body["segments"]) or any(
        s["kind"] == "delete" for s in body["segments"]
    )
    # persisted
    r2 = client.post(
        "/v1/textdiff/make",
        json={"before": "one two", "after": "one three", "app": "t", "scope_key": "s"},
    )
    pid2 = r2.json()["proposal"]["id"]
    r3 = client.post(
        f"/v1/textdiff/t/s/{pid2}/apply", json={"current": "one two"}
    )
    assert r3.status_code == 200
    assert r3.json()["result"] == "one three"
    # drift → 409
    r4 = client.post(f"/v1/textdiff/t/s/{pid2}/apply", json={"current": "way off"})
    assert r4.status_code == 409
    assert pid  # silence lint
