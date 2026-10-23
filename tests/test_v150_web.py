from __future__ import annotations

import importlib
import io
import sys

from PIL import Image

from telegram_bot.codes import make_label_png
from web_admin.security import SessionCodec


def test_label_is_one_valid_png() -> None:
    raw = make_label_png({
        "sku": "SKU-001",
        "name": "Wireless Mouse",
        "barcode": "4601234567890",
        "price": 2490,
        "unit": "шт.",
    })
    image = Image.open(io.BytesIO(raw))
    assert image.format == "PNG"
    assert image.width >= 800
    assert image.height >= 500


def test_session_codec_roundtrip() -> None:
    codec = SessionCodec("test-secret", 1)
    token = codec.issue()
    assert codec.valid(token)
    assert not codec.valid(token + "x")


def test_web_health_and_api_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PRODUCT_MCP_DB_PATH", str(tmp_path / "web.sqlite3"))
    monkeypatch.setenv("WEB_ADMIN_PASSWORD", "admin-test-password")
    monkeypatch.setenv("WEB_API_KEY", "api-test-key")
    monkeypatch.setenv("WEB_SESSION_SECRET", "session-test-secret")
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_PORT", "8099")

    sys.modules.pop("web_admin.app", None)
    module = importlib.import_module("web_admin.app")

    from starlette.testclient import TestClient

    with TestClient(module.app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        denied = client.get("/api/v1/dashboard")
        assert denied.status_code == 401

        ok = client.get(
            "/api/v1/dashboard?days=30",
            headers={"Authorization": "Bearer api-test-key"},
        )
        assert ok.status_code == 200
        assert ok.json()["products_total"] == 0

        login = client.post(
            "/login",
            data={"password": "admin-test-password", "next": "/"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert "productflow_session" in login.headers.get("set-cookie", "")
