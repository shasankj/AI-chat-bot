"""Tiny in-memory sliding-window rate limiter.

Why it matters here: every chat turn costs real money (3 LLM calls) and an unauthenticated login
endpoint invites brute force. LIMITATION: per-process memory. With several server processes you'd move
this to Redis so the counts are shared.
"""
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> int:
        """Record a hit. Returns 0 if allowed, else the seconds until a slot frees up."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= window_seconds:      # forget hits older than the window
            hits.popleft()
        if len(hits) >= limit:
            return max(1, int(window_seconds - (now - hits[0])) + 1)
        hits.append(now)
        if len(self._hits) > 10_000:                         # keep memory bounded under abuse
            for k in [k for k, v in self._hits.items() if not v][:5_000]:
                del self._hits[k]
        return 0
