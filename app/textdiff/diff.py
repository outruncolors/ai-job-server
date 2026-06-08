"""Diff primitives over ``difflib`` — word-granular for prose-friendly inline spans.

- ``make_proposal(before, after, mode)`` → a content-addressed :class:`Proposal`
  carrying word-level hunks (for hunk-level accept), a unified line diff (for
  inspection), and a ``before_hash`` (for drift detection).
- ``apply_proposal(current, proposal, accept_hunks=None)`` → the resulting text,
  raising :class:`ConflictError` when ``current`` has drifted from the proposal's
  ``before`` (unless forced).
- ``render_inline(proposal)`` → ``[Segment]`` (equal / insert / delete) the
  Content Pane styles green/red.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel

# Split into words and runs of whitespace so spacing survives a round-trip.
_TOKEN_RE = re.compile(r"\S+|\s+")


class ConflictError(RuntimeError):
    """Raised when the live text has drifted from the proposal's ``before``."""


class Hunk(BaseModel):
    op: Literal["equal", "insert", "delete", "replace"]
    before: str = ""
    after: str = ""


class Segment(BaseModel):
    kind: Literal["equal", "insert", "delete"]
    text: str


class Proposal(BaseModel):
    id: str
    mode: str = "replace"
    before: str
    after: str
    before_hash: str
    hunks: list[Hunk]
    unified: str
    created_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text or "")


def _content_id(before: str, after: str, mode: str) -> str:
    blob = f"{mode}\x00{before}\x00{after}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _build_hunks(before: str, after: str) -> list[Hunk]:
    a, b = _tokens(before), _tokens(after)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    hunks: list[Hunk] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        hunks.append(
            Hunk(
                op=op,
                before="".join(a[i1:i2]),
                after="".join(b[j1:j2]),
            )
        )
    return hunks


def make_proposal(before: str, after: str, mode: str = "replace") -> Proposal:
    before = before or ""
    after = after or ""
    unified = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
    )
    return Proposal(
        id=_content_id(before, after, mode),
        mode=mode,
        before=before,
        after=after,
        before_hash=_hash(before),
        hunks=_build_hunks(before, after),
        unified=unified,
        created_at=_now_iso(),
    )


def apply_proposal(
    current: str,
    proposal: Proposal,
    accept_hunks: Optional[list[int]] = None,
    *,
    force: bool = False,
) -> str:
    """Apply ``proposal`` to ``current``.

    Full accept (``accept_hunks=None``) returns the proposal's ``after``.
    Hunk-level accept rebuilds the text taking the ``after`` side only for accepted
    change hunks (by index into ``proposal.hunks``) and the ``before`` side
    otherwise. Raises :class:`ConflictError` if ``current`` no longer matches the
    proposal's ``before`` (override with ``force=True``).
    """
    current = current or ""
    if not force and _hash(current) != proposal.before_hash and current != proposal.before:
        raise ConflictError(
            "text changed since this proposal was made — re-diff against current text"
        )
    if accept_hunks is None:
        return proposal.after
    accepted = set(accept_hunks)
    out: list[str] = []
    for idx, h in enumerate(proposal.hunks):
        if h.op == "equal":
            out.append(h.before)
        elif idx in accepted:
            out.append(h.after)
        else:
            out.append(h.before)
    return "".join(out)


def render_inline(proposal: Proposal) -> list[Segment]:
    segs: list[Segment] = []
    for h in proposal.hunks:
        if h.op == "equal":
            if h.before:
                segs.append(Segment(kind="equal", text=h.before))
        elif h.op == "insert":
            if h.after:
                segs.append(Segment(kind="insert", text=h.after))
        elif h.op == "delete":
            if h.before:
                segs.append(Segment(kind="delete", text=h.before))
        else:  # replace → show deletion then insertion
            if h.before:
                segs.append(Segment(kind="delete", text=h.before))
            if h.after:
                segs.append(Segment(kind="insert", text=h.after))
    return segs
