"""Rate limiting.

* check_run_quota: per-user run-creation limit, counted in MongoDB (works across instances).
* SlidingWindowLimiter: tiny in-memory limiter used for auth endpoints (per-process).
"""
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


async def check_run_quota(db, user_id, limit: int, window_s: int = 3600) -> None:
    since = datetime.now(timezone.utc) - timedelta(seconds=window_s)
    count = await db.runs.count_documents({"user_id": str(user_id), "created_at": {"$gte": since}})
    if count >= limit:
        raise HTTPException(
            429,
            f"Run limit reached ({limit} per hour). Try again later.",
            headers={"Retry-After": str(window_s)},
        )


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: int, clock=time.monotonic):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = self.clock()
        q = self._hits[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "Too many attempts, slow down.", headers={"Retry-After": str(self.window_s)})
        q.append(now)
