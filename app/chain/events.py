from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

log = logging.getLogger(__name__)

MAX_HISTORY = 5000
MAX_SUBSCRIBERS = 8

_SENTINEL: Any = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChainEvent:
    """One event emitted on the per-job stream.

    Payload is a free-form dict; `seq` is monotonic within a job so SSE clients
    can dedupe across reconnects.
    """
    type: str
    seq: int
    ts: str
    payload: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"type": self.type, "seq": self.seq, "ts": self.ts, **self.payload}


class EventBus:
    """In-memory per-job event bus.

    The executor and step runners `emit(...)` events; the SSE route subscribes
    and forwards them to the client. `subscribe()` first yields a snapshot of
    `_history`, then awaits live events; this lets a client connecting mid-job
    catch up without missing anything that already happened.

    Backed by a list + per-subscriber asyncio.Queue. Unbounded queues are fine
    here: the chain executor has a hard 2000-run budget, so the upper bound on
    events is finite (a few thousand at most).
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._history: list[ChainEvent] = []
        self._subscribers: list[asyncio.Queue] = []
        self._seq = 0
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def emit(self, event_type: str, **payload: Any) -> ChainEvent:
        if self._closed:
            log.debug("EventBus(%s): emit %r on closed bus, dropping", self.job_id, event_type)
            return ChainEvent(type=event_type, seq=-1, ts=_now_iso(), payload=payload)
        self._seq += 1
        evt = ChainEvent(type=event_type, seq=self._seq, ts=_now_iso(), payload=payload)
        if len(self._history) >= MAX_HISTORY:
            log.error(
                "EventBus(%s): history exceeded %d events; dropping oldest",
                self.job_id, MAX_HISTORY,
            )
            self._history.pop(0)
        self._history.append(evt)
        for q in self._subscribers:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                log.warning("EventBus(%s): subscriber queue full, dropping event", self.job_id)
        return evt

    def history(self) -> list[ChainEvent]:
        return list(self._history)

    async def subscribe(self) -> AsyncIterator[ChainEvent]:
        """Yield each historical event (snapshot), then live events until close.

        Capped at MAX_SUBSCRIBERS concurrent subscribers per job. If the cap is
        hit, the new caller gets only the snapshot and then exits.

        Crucially the subscriber's queue is registered *before* the snapshot
        is copied — both happen atomically inside the single event loop
        (no await in between) so any concurrent ``emit()`` either lands in
        the snapshot (and not the queue) or in the queue (and not the
        snapshot). The caller dedups by ``seq``.
        """
        if len(self._subscribers) >= MAX_SUBSCRIBERS:
            log.warning(
                "EventBus(%s): subscriber cap %d reached; new subscriber gets snapshot only",
                self.job_id, MAX_SUBSCRIBERS,
            )
            for evt in list(self._history):
                yield evt
            return
        q: asyncio.Queue = asyncio.Queue()
        # Atomic in cooperative-asyncio: no await between snapshot and append.
        snapshot = list(self._history)
        snapshot_seqs = {e.seq for e in snapshot}
        self._subscribers.append(q)
        try:
            for evt in snapshot:
                yield evt
            if self._closed:
                return
            while True:
                evt = await q.get()
                if evt is _SENTINEL:
                    return
                # Dedup: anything already delivered via snapshot would have
                # been emitted before append, so it can't be in `q` — but
                # be defensive.
                if evt.seq in snapshot_seqs:
                    continue
                yield evt
        finally:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for q in self._subscribers:
            try:
                q.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                pass
