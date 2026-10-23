# ProductFlow AI v1.3.0 — обновление существующего VPS

Текущий production-каталог: `/opt/productflow-ai`.

## 1. Загрузить ZIP

С Windows:

```powershell
scp ".\ProductFlow_AI_product-mcp_v1.3.0.zip" root@YOUR_SERVER_IP:/root/
```

## 2. Распаковать во временную папку

```bash
rm -rf /root/productflow-v1.3.0-stage
mkdir -p /root/productflow-v1.3.0-stage
python3 -m zipfile -e \
  /root/ProductFlow_AI_product-mcp_v1.3.0.zip \
  /root/productflow-v1.3.0-stage
```

## 3. Запустить безопасное обновление

```bash
bash \
  /root/productflow-v1.3.0-stage/product-mcp/deploy/update_server.sh \
  /opt/productflow-ai
```

Скрипт сам сохраняет `.env` и `data`, останавливает сервис, мигрирует SQLite, выполняет health-check и pytest, затем возвращает systemd service в работу.

## 4. Проверить

```bash
cd /opt/productflow-ai
source .venv/bin/activate

python -m scripts.healthcheck
python -m scripts.smoke_test_mcp
python -m scripts.smoke_test_business
python -m pytest -ra

systemctl status productflow-ai --no-pager -l
systemctl status productflow-backup.timer --no-pager
```

## 5. Уведомления

Новые переменные необязательны: если их нет в старом `.env`, используются безопасные defaults.

Чтобы зафиксировать их явно:

```env
NOTIFICATIONS_ENABLED=true
NOTIFICATION_USER_IDS=
NOTIFICATION_INTERVAL_SECONDS=300
DAILY_REPORT_HOUR_UTC=6
```

При пустом `NOTIFICATION_USER_IDS` сообщения получают `ADMIN_USER_IDS`.
