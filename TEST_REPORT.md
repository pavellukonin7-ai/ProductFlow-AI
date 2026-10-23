# ProductFlow AI v1.3.0 — test report

Перед упаковкой выполнено:

- `python -m compileall` для `mcp_server`, `telegram_bot`, `scripts`, `tests` — успешно.
- 25 локальных тестов — успешно.
- 1 MCP contract test локально пропущен, потому что в изолированном сборочном окружении отсутствует пакет `mcp`; на целевом VPS `mcp==2.0.0` уже установлен, а `deploy/update_server.sh` запускает полный `pytest -ra` перед повторным включением сервиса.

Проверено тестами:

- совместимость старой схемы v1.1.0;
- миграция v1.2.0 → v1.3.0 без потери существующего товара;
- добавление новых таблиц поставщиков, закупок и заказов;
- закупка → приёмка → увеличение остатка и обновление закупочной цены;
- заказ клиента не меняет остаток до завершения;
- завершение заказа списывает склад и фиксирует выручку/себестоимость;
- атомарность продажи при нехватке одной из позиций;
- ручные `sale` / `return` учитываются в новой аналитике;
- расчёт выручки, себестоимости, валовой прибыли и маржи;
- business dashboard;
- роли и защита AI write-tools;
- Excel/XLSX функциональность v1.2.0;
- форматирование Telegram ответов.

На сервере после обновления выполнить:

```bash
cd /opt/productflow-ai
source .venv/bin/activate
python -m scripts.healthcheck
python -m scripts.smoke_test_mcp
python -m scripts.smoke_test_business
python -m pytest -ra
systemctl status productflow-ai --no-pager -l
```

Ожидается полный проход MCP contract test в серверном `.venv` и активный systemd service.
