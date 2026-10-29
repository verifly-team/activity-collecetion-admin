"""导出：Excel 工作簿 + 流式 ZIP（Excel + 商家原附件）。"""

from __future__ import annotations

import io
import queue
import re
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .excel import build_workbook, excel_filename, zip_folder_name


def _safe(name: str, fallback: str = "未命名") -> str:
    """去掉路径分隔符与非法字符，保留中文。"""
    name = (name or "").strip() or fallback
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    return name[:60]


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
    stop: threading.Event | None = None,
) -> Iterator[bytes]:
    """边读磁盘边吐 zip 流，内存不随包体增长。"""
    folder = zip_folder_name()
    stop = stop or threading.Event()
    q: queue.Queue = queue.Queue(maxsize=16)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with zipfile.ZipFile(_QueueWriter(q), "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
                # ① 汇总表（3 个 sheet：报名清单 / 代表商品 / 附件清单）
                zf.writestr(
                    f"{folder}/{excel_filename()}",
                    build_workbook(rows, files_map, upload_path),
                )

                # ② 每家一个文件夹，只放商家自己上传的原文件
                missing: list[str] = []
                for row in rows:
                    if stop.is_set():
                        return
                    app_id = int(row["id"])
                    sub = f"{folder}/{app_id:03d}_{_safe(row.get('brand_name', ''))}"
                    used: set[str] = set()
                    for f in files_map.get(app_id, []):
                        src = upload_path / f["stored_path"]
                        if not src.exists():
                            missing.append(f"[{app_id}] {row.get('brand_name')} → {f['original_name']}")
                            continue
                        name = _safe(f["original_name"], "附件")
                        if name in used:  # 重名加序号
                            stem, _, ext = name.rpartition(".")
                            name = f"{stem or name}_{len(used)}.{ext}" if ext else f"{name}_{len(used)}"
                        used.add(name)
                        with src.open("rb") as s, zf.open(f"{sub}/附件/{name}", "w") as d:
                            while not stop.is_set():
                                buf = s.read(1024 * 512)
                                if not buf:
                                    break
                                d.write(buf)

                # ③ 有记录没文件的，单独留个说明，不静默跳过
                if missing:
                    zf.writestr(
                        f"{folder}/_缺失附件清单.txt",
                        "以下附件在数据库有记录，但磁盘上找不到：\n\n" + "\n".join(missing),
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
