from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True)
class WebSettings:
    database_path: Path
    host: str
    port: int
    admin_password: str
    api_key: str
    session_secret: str
    session_hours: int
    cookie_secure: bool


def load_web_settings() -> WebSettings:
    settings = WebSettings(
        database_path=Path(
            os.getenv("PRODUCT_MCP_DB_PATH", str(PROJECT_ROOT / "data" / "products.sqlite3"))
        ).expanduser().resolve(),
        host=os.getenv("WEB_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=max(1, min(65535, int(os.getenv("WEB_PORT", "8090")))),
        admin_password=os.getenv("WEB_ADMIN_PASSWORD", "").strip(),
        api_key=os.getenv("WEB_API_KEY", "").strip(),
        session_secret=os.getenv("WEB_SESSION_SECRET", "").strip(),
        session_hours=max(1, min(168, int(os.getenv("WEB_SESSION_HOURS", "12")))),
        cookie_secure=_env_bool("WEB_COOKIE_SECURE", False),
    )
    missing = [
        name
        for name, value in {
            "WEB_ADMIN_PASSWORD": settings.admin_password,
            "WEB_API_KEY": settings.api_key,
            "WEB_SESSION_SECRET": settings.session_secret,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Не заданы настройки Web Admin: " + ", ".join(missing))
    return settings
