from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SessionCodec:
    secret: str
    hours: int = 12

    def issue(self) -> str:
        expires = int(time.time()) + self.hours * 3600
        payload = f"admin:{expires}"
        sig = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}:{sig}"

    def valid(self, value: str | None) -> bool:
        if not value:
            return False
        try:
            role, raw_exp, sig = value.rsplit(":", 2)
            expires = int(raw_exp)
        except (ValueError, TypeError):
            return False
        if role != "admin" or expires < int(time.time()):
            return False
        payload = f"{role}:{expires}"
        expected = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)


def bearer_from_headers(headers: Mapping[str, str]) -> str:
    raw = headers.get("authorization", "")
    if not raw.lower().startswith("bearer "):
        return ""
    return raw[7:].strip()


def safe_client_name(value: str | None) -> str:
    raw = (value or "rest-api").strip()[:80]
    return "".join(ch for ch in raw if ch.isalnum() or ch in "._:-") or "rest-api"
