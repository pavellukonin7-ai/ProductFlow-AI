from __future__ import annotations

import json
from typing import Any

from mcp_server.database import Database
from mcp_server.repository import utc_now


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self.db = database

    def record(
        self,
        *,
        actor_user_id: str,
        actor_role: str,
        action: str,
        entity_type: str = "",
        entity_id: str = "",
        details: dict[str, Any] | None = None,
        success: bool = True,
    ) -> dict[str, Any]:
        now = utc_now()
        payload = json.dumps(details or {}, ensure_ascii=False, default=str, sort_keys=True)
        with self.db.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_log(actor_user_id, actor_role, action, entity_type, entity_id,
                                      details_json, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(actor_user_id or ""), str(actor_role or ""), action.strip(),
                    entity_type.strip(), entity_id.strip(), payload, int(success), now,
                ),
            )
            audit_id = int(cursor.lastrowid)
        return {
            "id": audit_id,
            "actor_user_id": str(actor_user_id or ""),
            "actor_role": str(actor_role or ""),
            "action": action.strip(),
            "entity_type": entity_type.strip(),
            "entity_id": entity_id.strip(),
            "details": details or {},
            "success": bool(success),
            "created_at": now,
        }

    def list(
        self,
        *,
        actor_user_id: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if actor_user_id:
            clauses.append("actor_user_id = ?")
            params.append(str(actor_user_id))
        if action:
            clauses.append("CASEFOLD(action) LIKE CASEFOLD(?)")
            params.append(f"%{action.strip()}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self.db.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        result = []
        for row in rows:
            try:
                details = json.loads(str(row["details_json"] or "{}"))
            except json.JSONDecodeError:
                details = {"raw": str(row["details_json"])}
            result.append({
                "id": int(row["id"]),
                "actor_user_id": str(row["actor_user_id"]),
                "actor_role": str(row["actor_role"]),
                "action": str(row["action"]),
                "entity_type": str(row["entity_type"]),
                "entity_id": str(row["entity_id"]),
                "details": details,
                "success": bool(row["success"]),
                "created_at": str(row["created_at"]),
            })
        return result
