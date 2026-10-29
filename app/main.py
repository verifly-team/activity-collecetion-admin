"""66th 参展申请 —— 参展申请列表（只读，独立服务）。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .audit import AuditLog
from .auth import client_ip, require_token, verify
from .config import settings
from .excel import build_workbook, excel_filename, zip_filename
from .export import iter_zip
from .limits import ConcurrencyGate, RateLimiter

logger = logging.getLogger("export.audit")
if not logger.handlers:  # 保证审计日志一定落到 stdout（docker logs 可见）
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s AUDIT %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_audit_log = AuditLog(settings.audit_path)


def _audit(event: str, request: Request | None = None, **fields: Any) -> None:
    """统一审计：写 stdout（docker logs 长期留存）+ JSONL（页面可查）。"""
    _audit_log.record(event, request, **fields)


DESCRIPTION = """
66th & 2nd 市集 —— **参展申请列表**。

- 只读访问采集服务的数据库与附件目录，不会写入任何数据
- 页面上筛选、勾选、导出清单（CSV）或打包下载（ZIP）
- 单次导出条数与体积由环境变量控制（`MAX_EXPORT_RECORDS` / `MAX_EXPORT_MB`）
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.export_token:
        logger.warning("未配置 EXPORT_TOKEN，导出接口会返回 503")
    elif len(settings.export_token) < 16:
        logger.warning(
            "EXPORT_TOKEN 只有 %d 位，建议至少 32 位随机串（openssl rand -base64 32）",
            len(settings.export_token),
        )
    yield


_DOCS = {
    "docs_url": "/docs" if settings.enable_docs else None,
    "redoc_url": "/redoc" if settings.enable_docs else None,
    "openapi_url": "/openapi.json" if settings.enable_docs else None,
}

app = FastAPI(
    title="66th 参展申请导出服务",
    version="1.4.2",
    description=DESCRIPTION,
    lifespan=lifespan,
    **_DOCS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "object-src 'none'"
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    headers = response.headers
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"  # 防止 token/URL 经 Referer 外泄
    headers["Content-Security-Policy"] = _CSP
    headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.path.startswith("/api/"):
        headers["Cache-Control"] = "no-store"
    return response


class _RedactToken(logging.Filter):
    """把访问日志里的 token=xxx 打码，避免密钥落到日志里。"""

    _PATTERN = re.compile(r"(token=)[^&\s\"]+")

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(self._PATTERN.sub(r"\1***", a) if isinstance(a, str) else a for a in args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactToken())

# ---- 导出限流 / 并发闸门 ----
_export_limiter = RateLimiter(settings.export_per_min, 60.0)
_export_gate = ConcurrencyGate(settings.max_concurrent_exports)


def guard_export(request: Request) -> None:
    """导出接口限流：每 IP 每分钟 N 次。"""
    ok, wait = _export_limiter.allow(client_ip(request))
    if not ok:
        raise HTTPException(status_code=429, detail=f"导出过于频繁，请 {wait} 秒后再试")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"ok": False, "error": {"code": code, "message": message}}
    )


@app.exception_handler(HTTPException)
async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    code = {
        401: "UNAUTHORIZED",
        404: "NOT_FOUND",
        413: "TOO_LARGE",
        429: "RATE_LIMITED",
        503: "UNAVAILABLE",
    }.get(exc.status_code, "ERROR")
    return _error(exc.status_code, code, str(exc.detail))


@app.get("/healthz", tags=["系统"], summary="健康检查")
def healthz() -> dict:
    try:
        db.ping()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="数据库不可用") from None
    return {"ok": True}


@app.post("/api/v1/auth", tags=["系统"], summary="校验 token")
def auth_check(request: Request, payload: dict[str, Any]) -> dict:
    verify(payload.get("token"), client_ip(request))
    return {
        "ok": True,
        "site_title": settings.title,
        "event_name": settings.event_name,
        "limits": {
            "max_records": settings.max_records,
            "max_mb": settings.max_bundle_mb,
            "page_size": settings.page_size,
        },
    }


@app.get("/api/v1/summary", tags=["数据"], summary="总览", dependencies=[Depends(require_token)])
def summary() -> dict:
    data = db.summary()
    data["limits"] = {
        "max_records": settings.max_records,
        "max_mb": settings.max_bundle_mb,
        "page_size": settings.page_size,
    }
    return data


@app.get("/api/v1/applications", tags=["数据"], summary="报名列表", dependencies=[Depends(require_token)])
def list_applications(
    keyword: str | None = Query(None, description="品牌 / 联系人 / 手机"),
    zone: str | None = Query(None, description="A / B / C"),
    date_from: str | None = Query(None, description="YYYY-MM-DD 或 ISO 时间"),
    date_to: str | None = Query(None, description="YYYY-MM-DD 或 ISO 时间"),
    with_files: bool | None = Query(None, description="只看有/无附件的"),
    page: int = Query(1, ge=1),
    page_size: int | None = Query(None, ge=1),
) -> dict:
    size = min(page_size or settings.page_size, settings.max_page_size)
    items, total = db.list_applications(
        keyword=keyword.strip() if keyword else None,
        zone=zone if zone in ("A", "B", "C") else None,
        date_from=date_from,
        date_to=date_to,
        with_files=with_files,
        page=page,
        page_size=size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": size,
        "pages": max(1, (total + size - 1) // size),
        "items": items,
    }


def _parse_ids(ids: str) -> list[int]:
    try:
        parsed = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="ids 参数格式不对，应为 12,13,14") from None
    parsed = list(dict.fromkeys(parsed))
    if not parsed:
        raise HTTPException(status_code=400, detail="请至少勾选一条记录")
    if len(parsed) > settings.max_records:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多导出 {settings.max_records} 条，你选了 {len(parsed)} 条",
        )
    return parsed


def _load(ids: list[int]) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    rows = db.get_applications(ids)
    if not rows:
        raise HTTPException(status_code=404, detail="没有找到对应的报名记录")
    total_size = sum(int(r.get("file_size") or 0) for r in rows)
    if total_size > settings.max_bundle_bytes:
        mb = total_size / 1024 / 1024
        raise HTTPException(
            status_code=413,
            detail=f"所选附件合计 {mb:.0f}MB，超过 {settings.max_bundle_mb}MB 上限，请减少勾选",
        )
    return rows, db.get_files_by_application([int(r["id"]) for r in rows])


@app.get(
    "/api/v1/audit",
    tags=["系统"],
    summary="审计日志（最近 N 条）",
    dependencies=[Depends(require_token)],
)
def read_audit(
    limit: int = Query(200, ge=1, le=2000),
    event: str | None = Query(None, description="按操作类型过滤，如 export_zip"),
) -> dict:
    items = _audit_log.tail(limit=limit, event=event)
    return {"ok": True, "count": len(items), "items": items}


@app.get(
    "/api/v1/applications/{application_id}/phone",
    tags=["数据"],
    summary="查看完整手机号（会记审计日志）",
    dependencies=[Depends(require_token)],
)
def reveal_phone(application_id: int, request: Request) -> dict:
    """列表接口只返回 138****8000，需要完整号码时单独调这个接口。"""
    phone = db.get_phone(application_id)
    if phone is None:
        raise HTTPException(status_code=404, detail="报名记录不存在")
    _audit("reveal_phone", request, application_id=application_id)
    return {"ok": True, "application_id": application_id, "phone": phone}


@app.get(
    "/api/v1/applications.xlsx",
    tags=["导出"],
    summary="导出 Excel（报名清单 / 代表商品 / 附件清单 三个 sheet）",
    dependencies=[Depends(require_token), Depends(guard_export)],
)
def export_excel(request: Request, ids: str = Query(..., description="逗号分隔的报名 id")) -> Response:
    rows, files_map = _load(_parse_ids(ids))
    _audit(
        "export_xlsx",
        request,
        ids=",".join(str(r["id"]) for r in rows),
        count=len(rows),
        files=sum(len(v) for v in files_map.values()),
    )
    return Response(
        content=build_workbook(rows, files_map, settings.upload_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(excel_filename())}"},
    )


@app.get(
    "/api/v1/bundle.zip",
    tags=["导出"],
    summary="打包下载 ZIP（Excel + 附件原件）",
    dependencies=[Depends(require_token), Depends(guard_export)],
)
def export_bundle(
    request: Request, ids: str = Query(..., description="逗号分隔的报名 id")
) -> StreamingResponse:
    rows, files_map = _load(_parse_ids(ids))
    lease = _export_gate.acquire()
    if lease is None:
        raise HTTPException(
            status_code=429,
            detail=f"当前已有 {settings.max_concurrent_exports} 个打包任务在进行，请稍后再试",
        )
    _audit(
        "export_zip",
        request,
        ids=",".join(str(r["id"]) for r in rows),
        count=len(rows),
        files=sum(len(v) for v in files_map.values()),
        mb=f"{sum(int(r.get('file_size') or 0) for r in rows) / 1024 / 1024:.1f}",
    )
    filename = quote(zip_filename())
    return StreamingResponse(
        _gated_zip(request, rows, files_map, lease),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Accel-Buffering": "no",
        },
    )


_STOP = object()


async def _gated_zip(request: Request, rows: list[dict], files_map: dict, lease: str) -> Any:
    """流式打包 + 断连监听。

    客户端中途关掉页面时，Starlette 不一定能及时关闭同步生成器，
    名额会一直占着。这里开一个轻量协程盯着 disconnect，
    一旦断开立刻停掉打包线程并归还名额。
    """
    stop = threading.Event()
    gen = iter_zip(rows, files_map, settings.upload_path, stop)

    async def watch() -> None:
        try:
            while True:
                if await request.is_disconnected():
                    stop.set()
                    _export_gate.release(lease)
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(watch())
    sent = 0
    aborted = False
    try:
        while True:
            chunk = await asyncio.to_thread(next, gen, _STOP)
            if chunk is _STOP:
                break
            _export_gate.touch(lease)
            sent += len(chunk)
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        aborted = True
        raise
    finally:
        task.cancel()
        stop.set()
        with contextlib.suppress(Exception):
            gen.close()
        _export_gate.release(lease)
        _audit(
            "export_zip_done",
            request,
            bytes=sent,
            mb=f"{sent / 1024 / 1024:.1f}",
            aborted=int(aborted),
        )


if settings.static_path.is_dir() and (settings.static_path / "index.html").exists():
    app.mount("/", StaticFiles(directory=settings.static_path, html=True), name="static")
else:

    @app.get("/", tags=["系统"])
    def index() -> dict:
        return {"service": "66th 参展申请导出服务", "ok": True}
