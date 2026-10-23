# ProductFlow AI v1.4.0 — обновление VPS

Версия добавляет мультисклад, QR/Code128, аудит и rate limit. Существующая база мигрируется автоматически: текущий общий остаток помещается на склад `MAIN`.

## Загрузка

```powershell
scp "$HOME\Downloads\ProductFlow_AI_product-mcp_v1.4.0.zip" root@YOUR_SERVER_IP:/root/
```

## Распаковка

```bash
rm -rf /root/productflow-v1.4.0-stage
mkdir -p /root/productflow-v1.4.0-stage
python3 -m zipfile -e \
  /root/ProductFlow_AI_product-mcp_v1.4.0.zip \
  /root/productflow-v1.4.0-stage
```

## Обновление

```bash
bash \
  /root/productflow-v1.4.0-stage/product-mcp/deploy/update_server.sh \
  /opt/productflow-ai
```

Скрипт останавливает сервис, сохраняет `.env` и `data`, устанавливает зависимости, запускает миграцию/health-check/pytest и снова включает systemd.

## Проверка

```bash
cd /opt/productflow-ai
source .venv/bin/activate
python -m scripts.healthcheck
python -m pytest -ra
systemctl status productflow-ai --no-pager -l
```

## Первые команды

```text
/warehouses
/warehouse SPB | Склад Санкт-Петербург | Санкт-Петербург
/transfer SKU-001 3 MAIN SPB | Перемещение | MOVE-001
/distribution SKU-001
/label SKU-001
/audit 20
```
