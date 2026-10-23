# ProductFlow AI v1.5.0 — Test report

Проверено локально:

- компиляция `web_admin`, `telegram_bot`, `mcp_server`, `scripts`, `tests`;
- единая PNG-этикетка QR + Code128;
- подпись и валидация Web session;
- Web login;
- REST API auth: без Bearer ключа `401`, с ключом доступ разрешён;
- REST создание товара;
- REST создание склада;
- REST перемещение между складами;
- общий товарный остаток при transfer не меняется;
- dashboard/products/warehouses/commerce/audit/API pages открываются;
- media label возвращает `image/png`;
- 35 доступных локальных регрессионных тестов: PASSED.

В проекте 39 тестов. Полный прогон выполняется на VPS, где установлены `mcp` и `openai`.
