"""Tunable simulation constants for Blaboratory (env-overridable).

Mirrors the ``os.environ.get(...)`` pattern used elsewhere in the codebase
(e.g. ``app/job_queue.py``). Kept in one place so the tick cadence and memory
caps are easy to find and override per deployment.
"""

from __future__ import annotations

import os

# Simulation clock: seconds of real wall-time between ticks.
TICK_INTERVAL_SECONDS = int(os.environ.get("BLAB_TICK_INTERVAL_SECONDS", "300"))

# Mechanical memory retrieval caps (Phase 3). The vector index (deferred) will
# later replace recency-gather with relevance retrieval.
MAX_MEMORY_ITEMS = int(os.environ.get("BLAB_MAX_MEMORY_ITEMS", "30"))
MAX_MEMORY_CHARS = int(os.environ.get("BLAB_MAX_MEMORY_CHARS", "4000"))
