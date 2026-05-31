"""Prattletale HTTP surface (prefix ``/v1/apps/prattletale``).

SP1 stub — an empty router so the ``main.py`` import resolves. The real
conversation/turn/retry endpoints land in SP4.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1/apps/prattletale", tags=["prattletale"])
