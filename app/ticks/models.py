from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class TickSchedule(BaseModel):
    cron: str
    timezone: str = "UTC"
    kind: Literal["interval", "cron"] = "interval"
    interval_unit: Optional[Literal["minute", "hour", "day", "week"]] = None
    interval_count: Optional[int] = None
    interval_anchor: Optional[str] = None  # "HH:MM" for day/week anchors


class Tick(BaseModel):
    id: str
    name: str
    sequence_id: str
    schedule: TickSchedule
    enabled: bool = True
    created_at: str
    updated_at: str
    last_fire_at: Optional[str] = None
    last_job_id: Optional[str] = None
    last_skip_reason: Optional[str] = None
    next_fire_at: Optional[str] = None
