# product-mcp

Прикладной MCP-сервис для управления каталогом товаров и складскими остатками. Проект состоит из независимого MCP-сервера на SQLite и Telegram-бота, который обращается к серверу через MCP stdio-клиент.

## Возможности

- создание, получение, поиск и изменение карточек товаров;
- увеличение, уменьшение и установка точного остатка;
- запрет отрицательных остатков;
- обязательная причина каждого движения;
- отчёт по дефицитным товарам;
- сводка склада и стоимость остатков;
- история движений;
- обычные Telegram-команды без LLM;
- запросы на русском языке через OpenAI Responses API;
- SOCKS5-прокси для Telegram на Windows;
- ограничение доступа по Telegram user ID;
- MCP resource и MCP prompt для подключения из Cursor.

## Структура

```text
product-mcp/
├── mcp_server/
│   ├── database.py       # SQLite и схема
│   ├── models.py         # выходные модели
│   ├── repository.py     # бизнес-логика
│   ├── tools.py          # MCP tools, resource, prompt
│   └── server.py         # запуск MCP stdio-сервера
├── telegram_bot/
│   ├── agent.py          # OpenAI + вызовы MCP tools
│   ├── config.py         # переменные окружения
│   ├── handlers.py       # Telegram-команды
│   ├── main.py           # polling и SOCKS5 proxy
│   ├── mcp_client.py     # MCP stdio-клиент
│   ├── prompts.py        # системный промпт
│   └── service.py        # форматирование ответов
├── scripts/
│   ├── smoke_test_mcp.py
│   └── check_telegram.py
├── tests/
├── .cursor/mcp.json
├── .env.example
├── requirements.txt
├── run_bot.ps1
└── test.ps1
```

## Запуск на Windows PowerShell

```powershell
cd C:\путь\к\product-mcp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

В `.env` обязательно заполните:

```env
BOT_TOKEN=ваш_токен_из_BotFather
BOT_PROXY=socks5://127.0.0.1:10808
```

Для сообщений обычным языком добавьте `OPENAI_API_KEY`. Без него команды `/summary`, `/products`, `/product`, `/low`, `/history`, `/add`, `/stock` всё равно работают.

Запуск:

```powershell
python -m telegram_bot.main
```

Или одной командой:

```powershell
.\run_bot.ps1
```

## Команды бота

```text
/summary
/products
/products мышь
/product LP-MSE-002
/low
/history
/history LP-MSE-002
/add SKU-1 | Новый товар | Категория | 1990.00 | 10 | 2
/stock SKU-1 -3 Продажа по заказу 1045
```

## Проверка

Автоматические тесты:

```powershell
python -m pytest -ra
```

Проверка реального MCP-процесса:

```powershell
python scripts\smoke_test_mcp.py
```

Проверка Telegram через ваш SOCKS5-прокси:

```powershell
python scripts\check_telegram.py
```

Полная последовательность:

```powershell
.\test.ps1
```

## Cursor MCP

Файл `.cursor/mcp.json` уже включён. Откройте корень проекта в Cursor. Если команда `python` не видна Cursor, замените её абсолютным путём к:

```text
C:\путь\к\product-mcp\.venv\Scripts\python.exe
```

## База

SQLite создаётся автоматически в `data/products.sqlite3`. Цены хранятся целым числом в копейках, чтобы избежать ошибок арифметики с `float`.

