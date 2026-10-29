"""只读数据层 —— 与采集服务共用同一个库，但只发 SELECT。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlparse

from .config import settings


def target() -> tuple[str, dict[str, Any]]:
    url = settings.database_url
    if "://" not in url:
        return "sqlite", {"path": url}

    parsed = urlparse(url)
    scheme = parsed.scheme.split("+")[0].lower()

    if scheme == "sqlite":
        path = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
        return "sqlite", {"path": path}

    if scheme == "mysql":
        return "mysql", {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/"),
        }

    raise ValueError(f"不支持的 DATABASE_URL：{url}")


def _adapt(sql: str) -> str:
    return sql if target()[0] == "sqlite" else sql.replace("?", "%s")


def connect() -> Any:
    dialect, conf = target()
    if dialect == "sqlite":
        conn = sqlite3.connect(conf["path"], timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    import pymysql
    import pymysql.cursors

    return pymysql.connect(
        host=conf["host"],
        port=conf["port"],
        user=conf["user"],
        password=conf["password"],
        database=conf["database"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=5,
        read_timeout=30,
    )


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def _rows(conn: Any, sql: str, args: tuple | list | None = None) -> list[dict[str, Any]]:
    if target()[0] == "sqlite":
        return [dict(r) for r in conn.execute(sql, args or ()).fetchall()]
    with conn.cursor() as cur:
        cur.execute(_adapt(sql), args)
        return list(cur.fetchall())


def ping() -> None:
    with get_conn() as conn:
        _rows(conn, "SELECT 1 AS ok")


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    for col in ("zones", "categories"):
        if isinstance(row.get(col), str):
            try:
                row[col] = json.loads(row[col])
            except json.JSONDecodeError:
                row[col] = []
    if isinstance(row.get("items_json"), str):
        try:
            row["items"] = json.loads(row["items_json"])
        except json.JSONDecodeError:
            row["items"] = []
    row.pop("items_json", None)
    # MySQL 的 SUM()/COUNT() 返回 Decimal，统一转 int，避免 JSON 序列化炸掉
    row["file_count"] = int(row.get("file_count") or 0)
    row["file_size"] = int(row.get("file_size") or 0)
    return row


_BASE_SQL = """
SELECT a.*,
       COALESCE(s.cnt, 0)  AS file_count,
       COALESCE(s.size, 0) AS file_size
FROM application a
LEFT JOIN (
    SELECT application_id, COUNT(*) AS cnt, SUM(size) AS size
    FROM file GROUP BY application_id
) s ON s.application_id = a.id
"""


def list_applications(
    keyword: str | None = None,
    zone: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    with_files: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    args: list[Any] = []

    if keyword:
        where.append("(a.brand_name LIKE ? OR a.contact_name LIKE ? OR a.phone LIKE ?)")
        args.extend([f"%{keyword}%"] * 3)
    if zone:
        where.append("a.zones LIKE ?")
        args.append(f'%"{zone}"%')
    if date_from:
        where.append("a.created_at >= ?")
        args.append(f"{date_from}T00:00:00Z" if len(date_from) == 10 else date_from)
    if date_to:
        where.append("a.created_at <= ?")
        args.append(f"{date_to}T23:59:59Z" if len(date_to) == 10 else date_to)
    if with_files is True:
        where.append("COALESCE(s.cnt, 0) > 0")
    elif with_files is False:
        where.append("COALESCE(s.cnt, 0) = 0")

    clause = ("WHERE " + " AND ".join(where)) if where else ""

    with get_conn() as conn:
        total = _rows(conn, f"SELECT COUNT(*) AS n FROM ({_BASE_SQL} {clause}) t", args)[0]["n"]
        rows = _rows(
            conn,
            f"{_BASE_SQL} {clause} ORDER BY a.id DESC LIMIT ? OFFSET ?",
            [*args, page_size, (page - 1) * page_size],
        )
    return [_decode(r) for r in rows], int(total)


def get_applications(ids: list[int]) -> list[dict[str, Any]]:
    """按 id 取（保持传入顺序以外的 id 升序）。"""
    if not ids:
        return []
    marks = ",".join(["?"] * len(ids))
    with get_conn() as conn:
        rows = _rows(conn, f"{_BASE_SQL} WHERE a.id IN ({marks}) ORDER BY a.id", list(ids))
    return [_decode(r) for r in rows]


def get_files_by_application(ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not ids:
        return {}
    marks = ",".join(["?"] * len(ids))
    with get_conn() as conn:
        rows = _rows(
            conn,
            f"SELECT * FROM file WHERE application_id IN ({marks}) ORDER BY id",
            list(ids),
        )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(int(r["application_id"]), []).append(r)
    return grouped


def summary() -> dict[str, Any]:
    with get_conn() as conn:
        total = _rows(conn, "SELECT COUNT(*) AS n FROM application")[0]["n"]
        files = _rows(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS s FROM file")[0]
    return {"applications": int(total), "files": int(files["n"]), "bytes": int(files["s"])}
