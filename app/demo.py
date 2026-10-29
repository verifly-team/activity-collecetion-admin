"""一键 DEMO：造一批假数据 + 起服务，用来预览界面。

python -m app.demo            # 造数据并启动，浏览器打开 http://127.0.0.1:8001/?token=demo
python -m app.demo --reset    # 清掉旧数据重造
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEMO_DIR = Path("demo")
DB_PATH = DEMO_DIR / "demo.db"
UPLOAD_DIR = DEMO_DIR / "uploads"
TOKEN = "demo"

SCHEMA = """
CREATE TABLE IF NOT EXISTS application (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL, brand_name TEXT NOT NULL, contact_name TEXT NOT NULL,
  phone TEXT NOT NULL, wechat TEXT, email TEXT, city TEXT, entity_type TEXT,
  is_first_time INTEGER NOT NULL DEFAULT 0, categories TEXT NOT NULL, zones TEXT NOT NULL,
  expected_qty INTEGER, price_min INTEGER, price_max INTEGER,
  pct_secondhand INTEGER, pct_new_stock INTEGER, pct_sample INTEGER, pct_replica INTEGER,
  items_json TEXT NOT NULL DEFAULT '[]', consent_at TEXT, privacy_version TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS file (
  id TEXT PRIMARY KEY, application_id INTEGER, kind TEXT, original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL, mime TEXT, size INTEGER NOT NULL DEFAULT 0,
  sha256 TEXT, created_at TEXT NOT NULL
);
"""

BRANDS = [
    ("拾光中古", "陈小姐", "深圳", ["bag", "apparel"], ["A", "C"]),
    ("旧物研究所", "李先生", "广州", ["watch", "jewelry"], ["A"]),
    ("Cicada Archive", "余小姐", "上海", ["apparel"], ["A"]),
    ("南头古着", "黄先生", "深圳", ["apparel", "shoe"], ["B"]),
    ("Vintage Lab", "周小姐", "深圳", ["bag"], ["C"]),
    ("旧时衣橱", "吴小姐", "东莞", ["apparel"], ["B", "C"]),
    ("三号仓库", "郑先生", "深圳", ["shoe", "other"], ["B"]),
    ("黑胶与旧书", "冯先生", "广州", ["other"], ["B"]),
    ("Luna Vintage", "林小姐", "厦门", ["jewelry", "watch"], ["A"]),
    ("老王家杂货", "王先生", "深圳", ["other"], ["C"]),
    ("W.W.W Studio", "何小姐", "深圳", ["apparel"], ["A"]),
    ("梨泰院小店", "金小姐", "深圳", ["bag", "jewelry"], ["C"]),
]

ITEMS = [
    ("Hermès Birkin 30 金棕", "2015 年 / Birkin"),
    ("Levi's 70505 大 E 夹克", "70 年代 / Big E"),
    ("Rolex Submariner 116610LN", "2018 年 / 全套"),
    ("Chanel Classic Flap 中号", "90 年代"),
    ("Comme des Garçons 1998 秋冬", "1998 / AD1998"),
    ("Nike Dunk Low 未穿", "2021 / 库存"),
]


def _mb(n: float) -> int:
    return int(n * 1024 * 1024)


def seed(reset: bool) -> None:
    if reset and DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    if DB_PATH.exists():
        print(f"数据库已存在，跳过造数（想重造加 --reset）：{DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    base = datetime.now(UTC) - timedelta(days=2)

    for idx, (brand, contact, city, cats, zones) in enumerate(BRANDS, start=1):
        created = base + timedelta(hours=idx * 3, minutes=random.randint(0, 59))
        created_iso = created.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        item = random.choice(ITEMS)
        conn.execute(
            "INSERT INTO application (id, created_at, brand_name, contact_name, phone, wechat,"
            " email, city, entity_type, is_first_time, categories, zones, expected_qty,"
            " price_min, price_max, pct_secondhand, pct_new_stock, pct_sample, pct_replica,"
            " items_json, consent_at, privacy_version, source)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                idx,
                created_iso,
                brand,
                contact,
                f"138{random.randint(10000000, 99999999)}",
                f"wx_{idx}",
                None if idx % 3 else f"shop{idx}@example.com",
                city,
                random.choice(["company", "individual", "personal"]),
                0 if idx % 2 else 1,
                json.dumps(cats),
                json.dumps(zones),
                random.randint(40, 260),
                random.choice([200, 500, 800]),
                random.choice([8000, 20000, 35000]),
                random.choice([40, 60, 70]),
                random.choice([10, 20, 30]),
                random.choice([0, 10]),
                0,
                json.dumps(
                    [
                        {
                            "name": item[0],
                            "era_series": item[1],
                            "condition_source": "二手 / 附来源说明",
                            "price": random.randint(3000, 60000),
                        }
                    ],
                    ensure_ascii=False,
                ),
                created_iso,
                "v1.0",
                random.choice(["h5", "h5", "qrcode"]),
            ),
        )

        # 0~3 个附件，大小 2~9MB（稀疏文件，秒建）
        app_dir = UPLOAD_DIR / str(idx)
        app_dir.mkdir(exist_ok=True)
        for n in range(random.choice([0, 1, 1, 2, 2, 3])):
            size = _mb(round(random.uniform(2, 9), 1))
            fid = f"{idx}{n:02d}" + "0" * 28
            name = f"{brand}_{n + 1}.zip"
            path = app_dir / f"{fid}.zip"
            with path.open("wb") as fh:
                fh.truncate(size)
            conn.execute(
                "INSERT INTO file (id, application_id, kind, original_name, stored_path,"
                " mime, size, sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (fid, idx, "photos", name, f"{idx}/{fid}.zip", "application/zip", size, "", created_iso),
            )

    conn.commit()
    conn.close()
    print(f"已生成 {len(BRANDS)} 条报名 → {DB_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出后台 DEMO")
    parser.add_argument("--reset", action="store_true", help="清掉旧数据重新生成")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    seed(args.reset)

    os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.resolve()}"
    os.environ["UPLOAD_DIR"] = str(UPLOAD_DIR.resolve())
    os.environ["EXPORT_TOKEN"] = TOKEN

    import uvicorn

    print(f"\n  打开浏览器： http://127.0.0.1:{args.port}/?token={TOKEN}\n")
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
