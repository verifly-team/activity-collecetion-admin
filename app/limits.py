"""极简限流：滑动窗口 + 带租约的并发闸门，纯标准库。"""

from __future__ import annotations

import threading
import time
import uuid
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
    """带租约的并发闸门。

    - 客户端中途断开时，Starlette 不一定能及时关闭生成器，
      所以每个名额都带「最后活跃时间」：超过 ttl 秒没动静就自动回收，
      避免一次误关页面把功能永久锁死。
    - 正常结束仍然靠 release() 立刻归还。
    """

    def __init__(self, n: int, ttl: float = 120.0) -> None:
        self.size = max(1, n)
        self.ttl = ttl
        self._leases: dict[str, float] = {}
        self._lock = threading.Lock()

    def _reap(self, now: float) -> None:
        for key, seen in list(self._leases.items()):
            if now - seen > self.ttl:
                self._leases.pop(key, None)

    def acquire(self) -> str | None:
        """成功返回租约 id，失败返回 None。"""
        now = time.monotonic()
        with self._lock:
            self._reap(now)
            if len(self._leases) >= self.size:
                return None
            lease = uuid.uuid4().hex[:12]
            self._leases[lease] = now
            return lease

    def touch(self, lease: str) -> None:
        """每写出一块数据就续租，活着的任务不会被误回收。"""
        with self._lock:
            if lease in self._leases:
                self._leases[lease] = time.monotonic()

    def release(self, lease: str) -> None:
        with self._lock:
            self._leases.pop(lease, None)

    @property
    def active(self) -> int:
        with self._lock:
            self._reap(time.monotonic())
            return len(self._leases)


__all__ = ["ConcurrencyGate", "RateLimiter"]
