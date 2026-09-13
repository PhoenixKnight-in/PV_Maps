"""A per-client sliding window, for `POST /v1/bill-extract`.

ARCHITECTURE.md 8: "Limit bill-extraction requests by IP and size."

Honest about what this is: a single-process in-memory brake on accidental loops
and casual abuse. It is not a defence, and a multi-replica deployment needs the
limit at the ingress instead — ARCHITECTURE.md 9.2 puts the API behind one.

An instance per application rather than a module-level dict. Shared mutable
module state would mean one test's uploads counting against another's, and in
production it would mean two apps in one process sharing a budget neither
declared.
"""

from __future__ import annotations

import time
from collections import deque

__all__ = ["SlidingWindowLimiter"]

_MAX_TRACKED_CLIENTS = 4096


class SlidingWindowLimiter:
    def __init__(self, per_window: int, window_seconds: float = 60.0) -> None:
        if per_window < 1:
            raise ValueError(f"per_window must be at least 1, got {per_window}")
        self.per_window = per_window
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def check(self, client: str) -> bool:
        """True if the request may proceed, and counts it. False if it is over.

        Counting only on success: a client that is already being refused should
        not have its refusals extend its own cool-off indefinitely.
        """
        now = time.monotonic()
        hits = self._hits.setdefault(client, deque())
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.per_window:
            return False

        hits.append(now)
        self._evict_if_crowded(now)
        return True

    def _evict_if_crowded(self, now: float) -> None:
        """Bound the table. One entry per distinct client IP grows forever
        otherwise, which is a slow memory leak reachable by anyone."""
        if len(self._hits) <= _MAX_TRACKED_CLIENTS:
            return
        cutoff = now - self.window_seconds
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()
