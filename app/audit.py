"""审计日志：同时写 stdout（长期）和 JSONL 文件（页面可读）。"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("export.audit")

_lock = threading.Lock()
_MAX_LINES = 20000  # 文件超过这么多行就滚动，防止无限增长


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------ 写
    def record(self, event: str, request: Any = None, **fields: Any) -> None:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            "event": event,
        }
        if request is not None:
            entry["ip"] = _client_ip(request)
            entry["ua"] = (request.headers.get("user-agent") or "")[:120]
        entry.update({k: v for k, v in fields.items() if v is not None})

        # stdout：docker logs 长期留存
        flat = " ".join(f"{k}={v}" for k, v in entry.items() if k != "ua")
        logger.info("%s ua=%s", flat, entry.get("ua", ""))

        # JSONL：页面上能查
        line = json.dumps(entry, ensure_ascii=False)
        try:
            with _lock:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                self._trim()
        except OSError:
            pass  # 磁盘不可写也不影响业务

    def _trim(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > _MAX_LINES:
                self.path.write_text("".join(lines[-_MAX_LINES:]), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------ 读
    def tail(self, limit: int = 200, event: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with _lock, self.path.open("r", encoding="utf-8") as f:
                lines = f.readlines()[-5000:]
        except OSError:
            return []

        out: list[dict[str, Any]] = []
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event and item.get("event") != event:
                continue
            out.append(item)
            if len(out) >= limit:
                break
        return out


def _client_ip(request: Any) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "-"


__all__ = ["AuditLog"]
