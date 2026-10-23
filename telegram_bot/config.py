from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "да"}


def _csv_ints(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    bot_token: str
    bot_proxy: str | None
    openai_api_key: str | None
    openai_base_url: str | None
    openai_model: str
    openai_proxy: str | None
    database_path: Path
    allowed_user_ids: tuple[int, ...]
    admin_user_ids: tuple[int, ...]
    manager_user_ids: tuple[int, ...]
    viewer_user_ids: tuple[int, ...]
    backup_dir: Path
    backup_keep: int
    notifications_enabled: bool
    notification_user_ids: tuple[int, ...]
    notification_interval_seconds: int
    daily_report_hour_utc: int
    security_rate_limit_per_minute: int


def load_settings() -> Settings:
    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        bot_proxy=os.getenv("BOT_PROXY", "").strip() or None,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip() or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.5").strip(),
        openai_proxy=os.getenv("OPENAI_PROXY", "").strip() or None,
        database_path=Path(
            os.getenv("PRODUCT_MCP_DB_PATH", str(PROJECT_ROOT / "data" / "products.sqlite3"))
        ).expanduser().resolve(),
        allowed_user_ids=_csv_ints(os.getenv("ALLOWED_USER_IDS")),
        admin_user_ids=_csv_ints(os.getenv("ADMIN_USER_IDS")),
        manager_user_ids=_csv_ints(os.getenv("MANAGER_USER_IDS")),
        viewer_user_ids=_csv_ints(os.getenv("VIEWER_USER_IDS")),
        backup_dir=Path(
            os.getenv("BACKUP_DIR", str(PROJECT_ROOT / "backups"))
        ).expanduser().resolve(),
        backup_keep=max(1, int(os.getenv("BACKUP_KEEP", "14"))),
        notifications_enabled=_env_bool(os.getenv("NOTIFICATIONS_ENABLED"), True),
        notification_user_ids=_csv_ints(os.getenv("NOTIFICATION_USER_IDS")),
        notification_interval_seconds=max(60, int(os.getenv("NOTIFICATION_INTERVAL_SECONDS", "300"))),
        daily_report_hour_utc=max(0, min(23, int(os.getenv("DAILY_REPORT_HOUR_UTC", "6")))),
        security_rate_limit_per_minute=max(10, int(os.getenv("SECURITY_RATE_LIMIT_PER_MINUTE", "60"))),
    )
