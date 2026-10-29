"""极简限流：滑动窗口 + 并发闸门，纯标准库。"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """每个 key（IP）在 window 秒内最多 times 次。"""

    def __init__(self, times: int, window: float = 60.0) -> None:
        self.times = times
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 还需等待的秒数)。"""
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            while dq and now - dq[0] > self.window:
                dq.popleft()
            if len(dq) >= self.times:
                wait = int(self.window - (now - dq[0])) + 1
                return False, wait
            dq.append(now)
            if len(self._hits) > 5000:  # 防止内存膨胀
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True, 0


class ConcurrencyGate:
    """同时最多 n 个重操作，超出的直接拒绝而不是排队。"""

    def __init__(self, n: int) -> None:
        self._sem = threading.BoundedSemaphore(max(1, n))

    def acquire(self) -> bool:
        return self._sem.acquire(blocking=False)

    def release(self) -> None:
        with contextlib.suppress(ValueError):
            self._sem.release()


__all__ = ["ConcurrencyGate", "RateLimiter"]
