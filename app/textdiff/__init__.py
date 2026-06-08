"""App-agnostic text proposals: make / apply / render-inline a before→after diff.

A :class:`Proposal` is content-addressed (its id is a hash of before+after+mode),
so the same edit is the same proposal regardless of who produced it — any app can
reuse it. Tomeberry uses this for its Accept/Reject/Iterate loop, but nothing here
knows about Tomeberry.
"""

from .diff import (
    ConflictError,
    Hunk,
    Proposal,
    Segment,
    apply_proposal,
    make_proposal,
    render_inline,
)

__all__ = [
    "ConflictError",
    "Hunk",
    "Proposal",
    "Segment",
    "apply_proposal",
    "make_proposal",
    "render_inline",
]
