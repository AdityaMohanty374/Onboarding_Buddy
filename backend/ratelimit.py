"""
Minimal per-IP sliding-window rate limiter, plus a developer-key bypass.

Deliberately not using Redis/slowapi/etc — this is a single-process app, and
an in-memory dict is enough. If this ever runs with multiple worker
processes, each process gets its own counters (limits become "per worker,"
not global) — fine for a portfolio/demo deployment, worth revisiting if this
ever needs to survive multi-worker or multi-instance scaling.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from config import settings

# ip -> deque of request timestamps (seconds) within the current window
_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Render (and most PaaS) sit behind a proxy, so the real client IP shows
    # up in X-Forwarded-For, not request.client.host (which would just be
    # the proxy's IP for every request).
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_developer(request: Request) -> bool:
    key = request.headers.get("x-dev-key", "")
    return bool(settings.DEV_API_KEY) and key == settings.DEV_API_KEY


def enforce(request: Request, limit_per_min: int, bucket: str):
    """
    Raise 429 if this client has exceeded `limit_per_min` requests to this
    endpoint (`bucket`) in the last 60 seconds. No-op entirely for requests
    carrying a valid developer key.
    """
    if is_developer(request):
        return

    ip = _client_ip(request)
    key = f"{bucket}:{ip}"
    now = time.monotonic()
    window_start = now - 60

    q = _hits[key]
    while q and q[0] < window_start:
        q.popleft()

    if len(q) >= limit_per_min:
        retry_after = int(60 - (now - q[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit reached ({limit_per_min}/min) for this endpoint. "
                f"Try again in about {retry_after}s, or use a developer key "
                f"for unrestricted access."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    q.append(now)
