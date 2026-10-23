# ProductFlow AI v1.5.0 — Web Admin + REST API

## Что добавлено

- отдельный `productflow-web.service`;
- Web Admin Dashboard;
- каталог товаров с поиском;
- склады и межскладские перемещения из браузера;
- закупки, продажи и поставщики;
- расширенный Web-журнал аудита;
- единая товарная этикетка QR + Code128;
- REST API v1 для интеграций;
- Bearer API key;
- Web login с подписанной HttpOnly cookie;
- API/Web write-аудит;
- безопасный bind `127.0.0.1:8090` по умолчанию.

## Обновление

```bash
bash /root/productflow-v1.5.0-stage/product-mcp/deploy/update_server.sh /opt/productflow-ai
```

Updater не меняет существующие товары и бизнес-данные. Перед копированием создаётся safety backup `.env` и `data/`.

Если Web-секреты отсутствуют, updater генерирует их и сохраняет в:

```text
/root/productflow-web-credentials.txt
```

Файл имеет права `600`.

## Доступ к Web Admin с Windows

Порт наружу открывать не нужно. Запустите SSH tunnel:

```powershell
ssh -L 8090:127.0.0.1:8090 root@SERVER_IP
```

Пока SSH-сессия открыта, в браузере:

```text
http://127.0.0.1:8090
```

Пароль:

```bash
cat /root/productflow-web-credentials.txt
```

## REST API

API использует:

```http
Authorization: Bearer <WEB_API_KEY>
X-ProductFlow-Client: crm-name
```

Пример:

```bash
KEY="$(grep '^WEB_API_KEY=' /root/productflow-web-credentials.txt | cut -d= -f2-)"
curl -sS \
  -H "Authorization: Bearer $KEY" \
  -H "X-ProductFlow-Client: local-test" \
  http://127.0.0.1:8090/api/v1/dashboard?days=30
```

## Безопасность

Не меняйте `WEB_HOST=127.0.0.1` на `0.0.0.0`, пока перед сервисом не настроен HTTPS reverse proxy и сетевые ограничения.
