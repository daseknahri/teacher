from __future__ import annotations

from collections import deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException


_LOCK = Lock()
_HITS: dict[str, deque[float]] = {}


def _key(scope: str, user_id: int | None, resource_id: int | None) -> str:
    return f"{scope}:{user_id or 'anon'}:{resource_id or 'all'}"


def reset_rate_limits() -> None:
    with _LOCK:
        _HITS.clear()


def enforce_rate_limit(
    *,
    scope: str,
    user_id: int | None,
    limit: int,
    window_seconds: int,
    resource_id: int | None = None,
) -> None:
    if limit <= 0:
        return
    now = monotonic()
    bucket_key = _key(scope, user_id, resource_id)
    with _LOCK:
        bucket = _HITS.setdefault(bucket_key, deque())
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {scope}. Try again later.",
            )
        bucket.append(now)
