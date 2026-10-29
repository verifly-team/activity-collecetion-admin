"""鉴权：单 token，支持 Header 与查询参数两种传法。"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import Header, HTTPException, Query, Request

from .config import settings

_failed: dict[str, list[float]] = defaultdict(list)
_blocked_until: dict[str, float] = {}


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def _check_blocked(ip: str) -> None:
    until = _blocked_until.get(ip, 0)
    if until > time.time():
        raise HTTPException(status_code=429, detail="尝试次数过多，请 5 分钟后再试")


def register_failure(ip: str) -> None:
    now = time.time()
    hits = [t for t in _failed[ip] if now - t < 300]
    hits.append(now)
    _failed[ip] = hits
    if len(hits) >= settings.login_max_attempts:
        _blocked_until[ip] = now + 300
        _failed.pop(ip, None)


def register_success(ip: str) -> None:
    _failed.pop(ip, None)
    _blocked_until.pop(ip, None)


def _expected() -> str:
    if not settings.export_token:
        raise HTTPException(status_code=503, detail="服务未配置 EXPORT_TOKEN，已禁用导出")
    return settings.export_token


def verify(supplied: str | None, ip: str) -> None:
    token = _expected()
    _check_blocked(ip)
    # 按字节比较：hmac.compare_digest 传 str 只支持 ASCII，
    # 一旦 token 里有中文/emoji 会抛 TypeError 变成 500。
    # 编码成 UTF-8 后再比，既支持任意字符又保持常数时间。
    ok = bool(supplied) and hmac.compare_digest((supplied or "").encode("utf-8"), token.encode("utf-8"))
    if not ok:
        register_failure(ip)
        raise HTTPException(status_code=401, detail="Token 不正确")
    register_success(ip)


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None, description="下载链接用：?token=xxx"),
) -> None:
    """页面用 Authorization: Bearer，下载链接用 ?token=。"""
    supplied = None
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    elif token:
        supplied = token.strip()
    verify(supplied, client_ip(request))
