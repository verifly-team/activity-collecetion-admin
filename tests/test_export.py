import io
import os
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

BASE = "/tmp/vf_export_test"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{BASE}/app.db")
os.environ.setdefault("UPLOAD_DIR", f"{BASE}/uploads")
os.environ.setdefault("EXPORT_TOKEN", "test-token")
os.environ.setdefault("MAX_EXPORT_RECORDS", "2")
os.environ.setdefault("MAX_EXPORT_MB", "50")

from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer test-token"}


def _seed():
    os.makedirs(f"{BASE}/uploads/1", exist_ok=True)
    os.makedirs(f"{BASE}/uploads/2", exist_ok=True)
    with open(f"{BASE}/uploads/1/a.zip", "wb") as f:
        f.write(b"PK\x03\x04hello")
    conn = sqlite3.connect(f"{BASE}/app.db")
    conn.executescript(
        """
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
    )
    rows = [
        (1, "2026-12-25T06:00:00Z", "拾光中古", "陈小姐", "13800138000", '["bag"]', '["A"]'),
        (2, "2026-12-25T07:00:00Z", "旧物研究所", "李先生", "13900139000", '["watch"]', '["B"]'),
        (3, "2026-12-26T08:00:00Z", "第三家", "王小姐", "13700137000", '["shoe"]', '["C"]'),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO application (id, created_at, brand_name, contact_name, phone, wechat,"
            " categories, zones, items_json) VALUES (?,?,?,?,?,'wx',?,?,'[]')",
            r,
        )
    conn.execute(
        "INSERT INTO file (id, application_id, original_name, stored_path, size, created_at)"
        " VALUES ('f1', 1, '照片.zip', '1/a.zip', 1024, '2026-12-25T06:00:00Z')"
    )
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def client():
    os.makedirs(BASE, exist_ok=True)
    if os.path.exists(f"{BASE}/app.db"):
        os.remove(f"{BASE}/app.db")
    from app import config

    config.settings.database_url = f"sqlite:///{BASE}/app.db"
    config.settings.upload_dir = f"{BASE}/uploads"
    config.settings.export_token = "test-token"
    config.settings.max_records = 2
    config.settings.max_bundle_mb = 50
    _seed()
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_auth_required(client):
    assert client.get("/api/v1/applications").status_code == 401
    assert client.get("/api/v1/applications", headers=AUTH).status_code == 200


def test_auth_endpoint(client):
    ok = client.post("/api/v1/auth", json={"token": "test-token"})
    assert ok.status_code == 200 and ok.json()["limits"]["max_records"] == 2
    assert client.post("/api/v1/auth", json={"token": "wrong"}).status_code == 401


def test_list_filters(client):
    data = client.get("/api/v1/applications", headers=AUTH).json()
    assert data["total"] == 3
    assert data["items"][0]["id"] == 3  # 倒序

    only_a = client.get("/api/v1/applications?zone=A", headers=AUTH).json()
    assert only_a["total"] == 1

    by_date = client.get("/api/v1/applications?date_from=2026-12-26", headers=AUTH).json()
    assert by_date["total"] == 1

    kw = client.get("/api/v1/applications?keyword=拾光", headers=AUTH).json()
    assert kw["total"] == 1 and kw["items"][0]["file_count"] == 1


def test_excel_export(client):
    from io import BytesIO

    from openpyxl import load_workbook

    res = client.get("/api/v1/applications.xlsx?ids=1,2", headers=AUTH)
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["content-type"]

    wb = load_workbook(BytesIO(res.content))
    assert wb.sheetnames == ["报名清单", "代表商品", "附件清单"]

    ws = wb["报名清单"]
    assert ws["A1"].value == "报名ID"
    assert ws.max_row == 3  # 表头 + 2 条
    brands = [ws.cell(row=r, column=3).value for r in (2, 3)]
    assert "拾光中古" in brands

    ws3 = wb["附件清单"]
    assert ws3.max_row >= 2
    assert ws3["A1"].value == "报名ID"


def test_record_limit_enforced(client):
    res = client.get("/api/v1/applications.xlsx?ids=1,2,3", headers=AUTH)
    assert res.status_code == 400
    assert "最多导出 2 条" in res.json()["error"]["message"]


def test_bundle_zip(client):
    res = client.get("/api/v1/bundle.zip?ids=1", headers=AUTH)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert any("报名清单_" in n and n.endswith(".xlsx") for n in names)
    assert any(n.endswith("照片.zip") for n in names)
    assert any("001_拾光中古/附件" in n for n in names)
    # 不再生成 JSON
    assert not any(n.endswith(".json") for n in names)


def test_bundle_missing_file_listed(client):
    conn = sqlite3.connect(f"{BASE}/app.db")
    conn.execute(
        "INSERT INTO file (id, application_id, original_name, stored_path, size, created_at)"
        " VALUES ('f2', 2, '不存在.zip', '2/none.zip', 10, '2026-12-25T07:00:00Z')"
    )
    conn.commit()
    conn.close()

    res = client.get("/api/v1/bundle.zip?ids=2", headers=AUTH)
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert any("_缺失附件清单.txt" in n for n in zf.namelist())


def test_token_via_query_for_download(client):
    res = client.get("/api/v1/applications.xlsx?ids=1&token=test-token")
    assert res.status_code == 200
    assert client.get("/api/v1/applications.xlsx?ids=1&token=bad").status_code == 401


def test_phone_masked_in_list(client):
    """列表接口不应返回完整号码。"""
    data = client.get("/api/v1/applications", headers=AUTH).json()
    phones = [it["phone"] for it in data["items"]]
    assert phones, "应有数据"
    for p in phones:
        assert "****" in p, f"号码未脱敏：{p}"
    assert all("13800138000" not in p for p in phones)


def test_reveal_phone_endpoint(client):
    res = client.get("/api/v1/applications/1/phone", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["phone"] == "13800138000"
    assert body["application_id"] == 1


def test_reveal_phone_requires_token(client):
    assert client.get("/api/v1/applications/1/phone").status_code == 401
    assert client.get("/api/v1/applications/999/phone", headers=AUTH).status_code == 404


def test_export_still_has_full_phone(client):
    """导出 Excel 是给业务用的，需要完整号码。"""
    from io import BytesIO

    from openpyxl import load_workbook

    res = client.get("/api/v1/applications.xlsx?ids=1", headers=AUTH)
    wb = load_workbook(BytesIO(res.content))
    ws = wb["报名清单"]
    assert ws.cell(row=2, column=5).value == "13800138000"
