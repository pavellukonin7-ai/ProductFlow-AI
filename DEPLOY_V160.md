# ProductFlow AI v1.6.0 — обновление VPS

Обновление выполняется поверх работающей v1.5.0 и сохраняет `.env`, SQLite `data/` и Web credentials.

```bash
rm -rf /root/productflow-v1.6.0-stage
mkdir -p /root/productflow-v1.6.0-stage
python3 -m zipfile -e /root/ProductFlow_AI_product-mcp_v1.6.0.zip /root/productflow-v1.6.0-stage
bash /root/productflow-v1.6.0-stage/product-mcp/deploy/update_server.sh /opt/productflow-ai
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
curl -fsS http://127.0.0.1:8090/api/v1/health | python3 -m json.tool
```

Web остаётся localhost-only. Для Windows используйте SSH tunnel:

```powershell
ssh -L 8090:127.0.0.1:8090 root@SERVER_IP
```

Затем откройте `http://127.0.0.1:8090`.
