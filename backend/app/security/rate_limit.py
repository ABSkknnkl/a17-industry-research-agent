"""Process-local sliding-window limiter for the competition deployment."""

import math
import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
    ) -> int | None:
        """Consume one allowance, or return the minimum Retry-After seconds."""

        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                return max(1, math.ceil(requests[0] + window_seconds - now))
            requests.append(now)
        return None

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()


api_rate_limiter = SlidingWindowRateLimiter()
