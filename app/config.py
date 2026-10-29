"""环境变量配置 —— 全部可改，不用改代码。"""

from __future__ import annotations

import os
from pathlib import Path


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


class Settings:
    def __init__(self) -> None:
        # ---- 数据源（只读）----
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///../server/data/app.db")
        self.upload_dir = os.getenv("UPLOAD_DIR", "../server/data/uploads")

        # ---- 鉴权 ----
        self.export_token = os.getenv("EXPORT_TOKEN", "")
        self.login_max_attempts = int(os.getenv("LOGIN_MAX_ATTEMPTS", "10"))

        # ---- 导出限制（可按需调）----
        self.max_records = int(os.getenv("MAX_EXPORT_RECORDS", "10"))
        self.max_bundle_mb = int(os.getenv("MAX_EXPORT_MB", "300"))
        self.page_size = int(os.getenv("PAGE_SIZE", "20"))
        self.max_page_size = int(os.getenv("MAX_PAGE_SIZE", "100"))

        # ---- 展示 ----
        self.title = os.getenv("SITE_TITLE", "66th 参展申请 · 导出后台")
        self.event_name = os.getenv("EVENT_NAME", "66th & 2nd Vintage Fashion Show & Market")
        self.allow_origins = _env_list("ALLOWED_ORIGINS", "*") or ["*"]
        self.static_dir = os.getenv("STATIC_DIR", "static")

    @property
    def max_bundle_bytes(self) -> int:
        return self.max_bundle_mb * 1024 * 1024

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)

    @property
    def static_path(self) -> Path:
        return Path(self.static_dir)


settings = Settings()
