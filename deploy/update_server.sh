#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-/opt/productflow-ai}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SAFETY_BACKUP="/root/productflow-ai-before-v1.7.0-${STAMP}"

if [[ ! -f "$TARGET_DIR/.env" ]]; then
  echo "Не найден $TARGET_DIR/.env — обновление остановлено" >&2
  exit 1
fi
if [[ ! -x "$TARGET_DIR/.venv/bin/python" ]]; then
  echo "Не найдено виртуальное окружение $TARGET_DIR/.venv" >&2
  exit 1
fi

echo "=== Остановка бота ==="
systemctl stop productflow-web.service || true
systemctl stop productflow-ai.service || true

echo "=== Safety backup: $SAFETY_BACKUP ==="
mkdir -p "$SAFETY_BACKUP"
cp -a "$TARGET_DIR/.env" "$SAFETY_BACKUP/.env"
if [[ -d "$TARGET_DIR/data" ]]; then
  cp -a "$TARGET_DIR/data" "$SAFETY_BACKUP/data"
fi
chmod -R go-rwx "$SAFETY_BACKUP"

echo "=== Копирование v1.7.0 ==="
cp -a "$SOURCE_DIR"/. "$TARGET_DIR"/
chmod 600 "$TARGET_DIR/.env"

echo "=== Web Admin credentials ==="
TARGET_DIR_ENV="$TARGET_DIR" "$TARGET_DIR/.venv/bin/python" - <<'PYCREDS'
from pathlib import Path
import os
import secrets

root = Path(os.environ["TARGET_DIR_ENV"])
path = root / ".env"
lines = path.read_text(encoding="utf-8").splitlines()
existing = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        existing[k.strip()] = v.strip()

updates = {}
if not existing.get("WEB_ADMIN_PASSWORD"):
    updates["WEB_ADMIN_PASSWORD"] = secrets.token_urlsafe(18)
if not existing.get("WEB_API_KEY"):
    updates["WEB_API_KEY"] = secrets.token_urlsafe(32)
if not existing.get("WEB_SESSION_SECRET"):
    updates["WEB_SESSION_SECRET"] = secrets.token_urlsafe(48)
for k, v in {
    "WEB_HOST": "127.0.0.1",
    "WEB_PORT": "8090",
    "WEB_SESSION_HOURS": "12",
    "WEB_COOKIE_SECURE": "false",
}.items():
    if not existing.get(k):
        updates[k] = v

if updates:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n# ProductFlow Web Admin v1.7.0\n")
        for k, v in updates.items():
            f.write(f"{k}={v}\n")

password = updates.get("WEB_ADMIN_PASSWORD") or existing.get("WEB_ADMIN_PASSWORD", "")
api_key = updates.get("WEB_API_KEY") or existing.get("WEB_API_KEY", "")
cred = Path("/root/productflow-web-credentials.txt")
cred.write_text(
    "ProductFlow AI Web Admin v1.6.0\n"
    "Local URL: http://127.0.0.1:8090\n"
    f"WEB_ADMIN_PASSWORD={password}\n"
    f"WEB_API_KEY={api_key}\n",
    encoding="utf-8",
)
os.chmod(cred, 0o600)
print("Web credentials saved to /root/productflow-web-credentials.txt (mode 600)")
PYCREDS
chmod 600 "$TARGET_DIR/.env"

echo "=== Зависимости ==="
cd "$TARGET_DIR"
"$TARGET_DIR/.venv/bin/python" -m pip install -r requirements.txt

echo "=== Миграция и health-check ==="
"$TARGET_DIR/.venv/bin/python" -m scripts.healthcheck

echo "=== Тесты ==="
"$TARGET_DIR/.venv/bin/python" -m pytest -ra

echo "=== Systemd units ==="
bash deploy/install_systemd.sh

echo "=== Web smoke-test ==="
sleep 2
"$TARGET_DIR/.venv/bin/python" -m scripts.smoke_test_web

echo "=== Готово ==="
systemctl status productflow-ai.service --no-pager -l
systemctl status productflow-web.service --no-pager -l
