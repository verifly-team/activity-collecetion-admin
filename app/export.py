"""导出：CSV 清单 + 流式 ZIP 打包。"""

from __future__ import annotations

import csv
import io
import json
import queue
import re
import shutil
import threading
import zipfile
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import settings

CATEGORY_CN = {
    "bag": "箱包手袋",
    "watch": "腕表",
    "jewelry": "珠宝配饰",
    "apparel": "服饰",
    "shoe": "鞋履",
    "other": "其他藏品",
}
ZONE_CN = {"A": "A区", "B": "B区", "C": "C区"}
ENTITY_CN = {"company": "公司", "individual": "个体工商户", "personal": "个人"}

CSV_HEADERS = [
    "报名ID",
    "提交时间(UTC)",
    "品牌/店铺",
    "联系人",
    "手机",
    "微信",
    "邮箱",
    "城市",
    "主体类型",
    "首次参展",
    "经营品类",
    "意向区域",
    "预计带货件数",
    "价格区间",
    "商品结构",
    "代表商品",
    "附件数",
    "附件大小(MB)",
    "来源",
]


def _safe(name: str, fallback: str = "未命名") -> str:
    """去掉路径分隔符与非法字符，保留中文。"""
    name = (name or "").strip() or fallback
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    return name[:60]


def _join(values: Iterable[str], mapping: dict[str, str]) -> str:
    return "、".join(mapping.get(v, v) for v in values)


def _structure(row: dict[str, Any]) -> str:
    pcts = [
        row.get("pct_secondhand"),
        row.get("pct_new_stock"),
        row.get("pct_sample"),
        row.get("pct_replica"),
    ]
    if all(p is None for p in pcts):
        return ""
    return f"二手{pcts[0]}% 未使用{pcts[1]}% 样衣{pcts[2]}% 复刻{pcts[3]}%"


def to_row(row: dict[str, Any]) -> list[Any]:
    items = row.get("items") or []
    items_text = "；".join(
        f"{i.get('name', '')}"
        + (f"（{i['era_series']}）" if i.get("era_series") else "")
        + (f" ¥{i['price']}" if i.get("price") is not None else "")
        for i in items
    )
    price = ""
    if row.get("price_min") is not None or row.get("price_max") is not None:
        price = f"{row.get('price_min') or 0}~{row.get('price_max') or 0}"

    return [
        row.get("id"),
        row.get("created_at"),
        row.get("brand_name"),
        row.get("contact_name"),
        row.get("phone"),
        row.get("wechat") or "",
        row.get("email") or "",
        row.get("city") or "",
        ENTITY_CN.get(row.get("entity_type") or "", row.get("entity_type") or ""),
        "是" if row.get("is_first_time") else "否",
        _join(row.get("categories") or [], CATEGORY_CN),
        _join(row.get("zones") or [], ZONE_CN),
        row.get("expected_qty") or "",
        price,
        _structure(row),
        items_text,
        row.get("file_count", 0),
        round((row.get("file_size") or 0) / 1024 / 1024, 2),
        row.get("source") or "",
    ]


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    for row in rows:
        writer.writerow(to_row(row))
    # 带 BOM，Excel 直接双击不乱码
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def _json_default(obj: Any) -> Any:
    """Decimal / date 之类的兜底，避免导出中断。"""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def json_bytes(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")


class _QueueWriter(io.RawIOBase):
    """把 zipfile 的写入转成流式 chunk。"""

    def __init__(self, q: queue.Queue) -> None:
        self._q = q

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:  # type: ignore[override]
        self._q.put(bytes(data))
        return len(data)

    def flush(self) -> None:
        return


def iter_zip(
    rows: list[dict[str, Any]],
    files_map: dict[int, list[dict[str, Any]]],
    upload_path: Path,
) -> Iterator[bytes]:
    """边读磁盘边吐 zip 流，内存不随包体增长。"""
    folder = f"导出_{datetime.now().strftime('%Y%m%d_%H%M')}"
    q: queue.Queue = queue.Queue(maxsize=16)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with zipfile.ZipFile(_QueueWriter(q), "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
                zf.writestr(f"{folder}/报名清单.csv", csv_bytes(rows))
                zf.writestr(f"{folder}/报名清单.json", json_bytes(rows))

                missing: list[str] = []
                for row in rows:
                    app_id = int(row["id"])
                    sub = f"{folder}/{app_id:03d}_{_safe(row.get('brand_name', ''))}"
                    zf.writestr(
                        f"{sub}/报名信息.json",
                        json.dumps(row, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8"),
                    )
                    used: set[str] = set()
                    for f in files_map.get(app_id, []):
                        src = upload_path / f["stored_path"]
                        if not src.exists():
                            missing.append(f"[{app_id}] {f['original_name']} → {f['stored_path']}")
                            continue
                        name = _safe(f["original_name"], "附件")
                        if name in used:  # 重名加序号
                            stem, _, ext = name.rpartition(".")
                            name = f"{stem or name}_{len(used)}.{ext}" if ext else f"{name}_{len(used)}"
                        used.add(name)
                        with (
                            src.open("rb") as s,
                            zf.open(f"{sub}/附件/{name}", "w") as d,
                        ):
                            shutil.copyfileobj(s, d, 1024 * 512)

                if missing:
                    zf.writestr(
                        f"{folder}/_缺失附件清单.txt",
                        "以下附件在数据库有记录但磁盘找不到：\n\n" + "\n".join(missing),
                    )
        except BaseException as exc:  # noqa: BLE001 - 任意异常都要传出去
            errors.append(exc)
        finally:
            q.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        chunk = q.get()
        if chunk is None:
            break
        yield chunk
    thread.join(timeout=1)
    if errors:
        raise errors[0]


def build_zip_bytes(rows: list[dict[str, Any]], files_map: dict[int, list[dict[str, Any]]]) -> bytes:
    """测试与小包用：一次性拿到完整字节。"""
    return b"".join(iter_zip(rows, files_map, settings.upload_path))
