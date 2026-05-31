"""Prattletale — an iMessage-style roleplay chat app.

A text-first conversation between a human **user** and a Hoodat character (the
*counterpart*). The model replies in the cadence of a real texting burst: an
ordered stack of short, typed bubbles. Each conversation is a self-contained
folder on disk (``config/prattletale/conversations/<id>/``) so it is portable
and debuggable.

Prattletale depends on Hoodat for all non-user characters; Hoodat has no
dependency on Prattletale.

See ``docs/apps/prattletale/design.md`` for the canonical design.
"""
