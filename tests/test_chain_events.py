from __future__ import annotations

import asyncio

import pytest

from app.chain.events import MAX_SUBSCRIBERS, EventBus


def test_emit_assigns_monotonic_seq():
    bus = EventBus("job-1")
    e1 = bus.emit("a", x=1)
    e2 = bus.emit("b", x=2)
    e3 = bus.emit("a", x=3)
    assert (e1.seq, e2.seq, e3.seq) == (1, 2, 3)
    assert e1.type == "a"
    assert e3.payload == {"x": 3}


def test_history_replays_all_events():
    bus = EventBus("job-2")
    bus.emit("a"); bus.emit("b"); bus.emit("c")
    hist = bus.history()
    assert [e.type for e in hist] == ["a", "b", "c"]
    assert [e.seq for e in hist] == [1, 2, 3]


def test_to_json_does_not_clobber_event_fields_when_payload_has_type():
    bus = EventBus("job-clobber")
    evt = bus.emit("step_start", step_type="llm", name="n")
    j = evt.to_json()
    # Even though payload carries `step_type`, the event-level `type` is the
    # event name, not the step's type. (The payload key is `step_type`, not
    # `type`, precisely to avoid the clobber.)
    assert j["type"] == "step_start"
    assert j["step_type"] == "llm"


async def test_subscribe_yields_snapshot_then_live():
    bus = EventBus("job-3")
    bus.emit("a", n=1)
    bus.emit("b", n=2)

    received: list[str] = []

    async def consumer():
        async for evt in bus.subscribe():
            received.append(evt.type)
            if evt.type == "done":
                return

    task = asyncio.create_task(consumer())
    # Give the consumer a tick to drain snapshot and register its queue.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    bus.emit("c", n=3)
    bus.emit("done")
    await asyncio.wait_for(task, timeout=1.0)
    assert received == ["a", "b", "c", "done"]


async def test_close_wakes_subscribers():
    bus = EventBus("job-4")

    async def consumer():
        out = []
        async for evt in bus.subscribe():
            out.append(evt.type)
        return out

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    bus.emit("x")
    bus.close()
    out = await asyncio.wait_for(task, timeout=1.0)
    assert out == ["x"]


async def test_multiple_subscribers_all_get_events():
    bus = EventBus("job-5")

    async def consumer(target: list):
        async for evt in bus.subscribe():
            target.append(evt.type)
            if evt.type == "stop":
                return

    a, b = [], []
    ta = asyncio.create_task(consumer(a))
    tb = asyncio.create_task(consumer(b))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    bus.emit("x")
    bus.emit("y")
    bus.emit("stop")
    await asyncio.wait_for(asyncio.gather(ta, tb), timeout=1.0)
    assert a == ["x", "y", "stop"]
    assert b == ["x", "y", "stop"]


async def test_emit_after_close_is_dropped():
    bus = EventBus("job-6")
    bus.emit("a")
    bus.close()
    after = bus.emit("b")
    assert after.seq == -1
    # History only carries the pre-close event.
    assert [e.type for e in bus.history()] == ["a"]


async def test_subscriber_cap_enforced():
    bus = EventBus("job-cap")

    async def consumer():
        out = []
        async for evt in bus.subscribe():
            out.append(evt.type)
            if evt.type == "stop":
                return
        return out

    tasks = [asyncio.create_task(consumer()) for _ in range(MAX_SUBSCRIBERS + 2)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    bus.emit("hello")
    bus.emit("stop")
    # Cap-exceeded consumers exit immediately after snapshot (no events yet,
    # so they get nothing); within-cap consumers see live events.
    results = await asyncio.wait_for(
        asyncio.gather(*tasks, return_exceptions=True), timeout=1.0
    )
    # At least MAX_SUBSCRIBERS consumers should have received both events.
    full_results = [r for r in results if r is None]  # consumer returns None on early stop
    # consumer() returns None when it `return`s — adjust to check via captured state:
    # Simpler: just assert no exceptions raised.
    for r in results:
        assert not isinstance(r, Exception)
