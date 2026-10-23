# ProductFlow AI v1.3.1 — корректирующее обновление

Исправляет коммерческую аналитику без изменения схемы базы.

```bash
rm -rf /root/productflow-v1.3.1-stage
mkdir -p /root/productflow-v1.3.1-stage
python3 -m zipfile -e \
  /root/ProductFlow_AI_product-mcp_v1.3.1.zip \
  /root/productflow-v1.3.1-stage

bash \
  /root/productflow-v1.3.1-stage/product-mcp/deploy/update_server.sh \
  /opt/productflow-ai
```

После обновления:

```bash
cd /opt/productflow-ai
source .venv/bin/activate
python -m pytest -ra
python -m scripts.healthcheck
```
