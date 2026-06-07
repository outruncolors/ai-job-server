"""The OOC plugin — a parallel out-of-character channel.

A composer **⌁ OOC** mode opens a back-and-forth with the *author behind the
character*: the model answers out of character (discussing the character/scene in
the third person to help steer the roleplay), never as the character. The user
keeps replying in OOC mode; sending a normal message ends the session, which
collapses into a bordered "OUT OF CHARACTER" panel that can be re-expanded.

OOC messages are stored inline in the transcript as ``ooc`` items (a session is a
maximal run of consecutive ones). In-character turns never see them; OOC
generation sees the in-character window plus the full OOC history. The frontend
(``ooc.js`` / ``ooc.css``) supplies the composer mode and the inner-bubble
rendering; the collapsible-run grouping lives in the core renderer (like
narration). This package wires the ``send`` action and the lean OOC pipeline.
"""

from . import plugin  # noqa: F401 — registers the plugin when the package is imported
