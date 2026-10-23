from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from telegram_bot.config import PROJECT_ROOT, load_settings


def main() -> None:
    settings = load_settings()
    backup_dir = settings.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(backup_dir, 0o700)
    except OSError:
        pass

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    db_target = backup_dir / f"products-{stamp}.sqlite3"

    source = sqlite3.connect(settings.database_path)
    target = sqlite3.connect(db_target)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    try:
        os.chmod(db_target, 0o600)
    except OSError:
        pass

    if os.getenv("BACKUP_INCLUDE_ENV", "false").strip().casefold() in {"1", "true", "yes", "да"}:
        env_source = PROJECT_ROOT / ".env"
        if env_source.exists():
            env_target = backup_dir / f"env-{stamp}.backup"
            shutil.copy2(env_source, env_target)
            try:
                os.chmod(env_target, 0o600)
            except OSError:
                pass

    backups = sorted(backup_dir.glob("products-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[settings.backup_keep:]:
        old.unlink(missing_ok=True)

    env_backups = sorted(backup_dir.glob("env-*.backup"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in env_backups[settings.backup_keep:]:
        old.unlink(missing_ok=True)

    print(f"Backup OK: {db_target}")


if __name__ == "__main__":
    main()
