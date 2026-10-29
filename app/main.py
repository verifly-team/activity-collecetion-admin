"""66th 参展申请 —— 参展申请列表（只读，独立服务）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .auth import client_ip, require_token, verify
from .config import settings
from .excel import build_workbook, excel_filename, zip_filename
from .export import iter_zip

DESCRIPTION = """
66th & 2nd 市集 —— **参展申请列表**。

- 只读访问采集服务的数据库与附件目录，不会写入任何数据
- 页面上筛选、勾选、导出清单（CSV）或打包下载（ZIP）
- 单次导出条数与体积由环境变量控制（`MAX_EXPORT_RECORDS` / `MAX_EXPORT_MB`）
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="66th 参展申请导出服务",
    version="1.1.0",
    description=DESCRIPTION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    "/api/v1/applications.xlsx",
    tags=["导出"],
    summary="导出 Excel（报名清单 / 代表商品 / 附件清单 三个 sheet）",
    dependencies=[Depends(require_token)],
)
def export_excel(ids: str = Query(..., description="逗号分隔的报名 id")) -> Response:
    rows, files_map = _load(_parse_ids(ids))
    return Response(
        content=build_workbook(rows, files_map, settings.upload_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(excel_filename())}"},
    )


@app.get(
    "/api/v1/bundle.zip",
    tags=["导出"],
    summary="打包下载 ZIP（Excel + 附件原件）",
    dependencies=[Depends(require_token)],
)
def export_bundle(ids: str = Query(..., description="逗号分隔的报名 id")) -> StreamingResponse:
    rows, files_map = _load(_parse_ids(ids))
    filename = quote(zip_filename())
    return StreamingResponse(
        iter_zip(rows, files_map, settings.upload_path),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "X-Accel-Buffering": "no",
        },
    )


if settings.static_path.is_dir() and (settings.static_path / "index.html").exists():
    app.mount("/", StaticFiles(directory=settings.static_path, html=True), name="static")
else:

    @app.get("/", tags=["系统"])
    def index() -> dict:
        return {"service": "66th 参展申请导出服务", "docs": "/docs"}
