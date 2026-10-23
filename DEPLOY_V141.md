# ProductFlow AI v1.4.1 — корректирующее обновление

Исправляет два обнаруженных при серверном обновлении дефекта v1.4.0:

1. дублированное обязательное поле rate limit в Settings;
2. зависимость Code128 PNG от ReportLab renderPM/Cairo.

Обновление выполняется тем же `deploy/update_server.sh`; `.env` и `data/` сохраняются.
