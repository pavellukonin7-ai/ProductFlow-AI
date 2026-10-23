# ProductFlow AI v1.7.0 — обновление с v1.6.0

Обновление выполняется штатным `deploy/update_server.sh`. Скрипт останавливает Web/Telegram, создаёт safety backup `.env` и `data`, копирует код, прогоняет миграцию через health-check, полный pytest, systemd и Web smoke-test.

```bash
bash /root/productflow-v1.7.0-stage/product-mcp/deploy/update_server.sh /opt/productflow-ai
```

После обновления:

```bash
cd /opt/productflow-ai
source .venv/bin/activate
python -m scripts.healthcheck
python -m scripts.smoke_test_mcp
python -m pytest -ra
systemctl is-active productflow-ai.service
systemctl is-active productflow-web.service
curl -fsS http://127.0.0.1:8090/api/v1/health
```

Ожидается `MCP=39 tools` и полный успешный pytest.

Миграция добавляет таблицу `customers`, а в sales order — `customer_id`, `reserved_at`, `processing_at`, `reserved_quantity`. Старые заказы и остатки сохраняются.
