"""Tunable simulation constants for Blaboratory (env-overridable).

Mirrors the ``os.environ.get(...)`` pattern used elsewhere in the codebase
(e.g. ``app/job_queue.py``). Kept in one place so the tick cadence and memory
caps are easy to find and override per deployment.
"""

from __future__ import annotations

import os

# Simulation clock: seconds of real wall-time between ticks.
TICK_INTERVAL_SECONDS = int(os.environ.get("BLAB_TICK_INTERVAL_SECONDS", "300"))

# Whether the sim clock auto-starts at server boot. Off by default so the
# server never silently runs continuous LLM generation until opted in (the
# clock can still be started/stopped at runtime via the API).
SIM_AUTOSTART = os.environ.get("BLAB_SIM_AUTOSTART", "0").lower() in ("1", "true", "yes")

# Mechanical memory retrieval caps (Phase 3). The vector index (D1) layers
# relevance retrieval on top while keeping these as the cap on the merged set.
MAX_MEMORY_ITEMS = int(os.environ.get("BLAB_MAX_MEMORY_ITEMS", "30"))
MAX_MEMORY_CHARS = int(os.environ.get("BLAB_MAX_MEMORY_CHARS", "4000"))

# Hybrid retrieval (D1.4): the recency *floor* (most-recent N items kept
# verbatim, never evicted for irrelevance) and how many similar items to pull.
RECENCY_FLOOR_ITEMS = int(os.environ.get("BLAB_RECENCY_FLOOR_ITEMS", "10"))
RELEVANT_TOP_K = int(os.environ.get("BLAB_RELEVANT_TOP_K", "10"))
