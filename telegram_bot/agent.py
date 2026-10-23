from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from openai import AsyncOpenAI

from telegram_bot.prompts import SYSTEM_PROMPT


class AgentMCPClient(Protocol):
    async def list_openai_tools(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


WRITE_TOOLS = {
    "create_product",
    "update_product",
    "adjust_stock",
    "stock_operation",
    "set_stock",
    "import_products",
    "seed_demo_data",
    "create_supplier",
    "create_purchase_order",
    "receive_purchase_order",
    "create_sales_order",
    "complete_sales_order",
    "create_customer",
    "reserve_sales_order",
    "release_sales_reservation",
    "start_sales_processing",
    "ship_sales_order",
    "create_warehouse",
    "transfer_between_warehouses",
}

INTERNAL_TOOLS = {"record_audit_event", "list_audit_events"}


@dataclass
class PendingWrite:
    tool_name: str
    arguments: dict[str, Any]
    tool_call_id: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    allowed_write_tools: set[str]
    actor_user_id: str = ""
    actor_role: str = "viewer"


class InventoryAgent:
    """Chat Completions AI-agent over MCP with explicit confirmation for writes."""

    def __init__(
        self,
        *,
        mcp: AgentMCPClient,
        api_key: str,
        model: str,
        base_url: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self.mcp = mcp
        self.model = model
        self._http_client = httpx.AsyncClient(proxy=proxy, timeout=90.0) if proxy else None
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if self._http_client:
            kwargs["http_client"] = self._http_client
        self.client = AsyncOpenAI(**kwargs)
        self._history: dict[int, list[dict[str, Any]]] = {}
        self._pending: dict[int, PendingWrite] = {}
        self._last_confirmed: dict[int, dict[str, Any]] = {}

    async def close(self) -> None:
        await self.client.close()
        if self._http_client:
            await self._http_client.aclose()

    def has_pending_confirmation(self, chat_id: int) -> bool:
        return chat_id in self._pending

    def pending_confirmation_text(self, chat_id: int) -> str | None:
        pending = self._pending.get(chat_id)
        if pending is None:
            return None
        return self._confirmation_text(pending.tool_name, pending.arguments)

    def pop_last_confirmed(self, chat_id: int) -> dict[str, Any] | None:
        return self._last_confirmed.pop(chat_id, None)

    async def cancel_pending(self, chat_id: int) -> str:
        if self._pending.pop(chat_id, None) is None:
            return "Нет операции, ожидающей подтверждения."
        history = list(self._history.get(chat_id, []))
        history.append({"role": "assistant", "content": "Операция отменена пользователем."})
        self._history[chat_id] = history[-40:]
        return "Операция отменена. Данные не изменены."

    async def confirm_pending(self, chat_id: int) -> str:
        pending = self._pending.pop(chat_id, None)
        if pending is None:
            return "Нет операции, ожидающей подтверждения."

        low_stock_warning = ""
        success = True
        arguments = dict(pending.arguments)
        if pending.tool_name == "transfer_between_warehouses":
            arguments["actor_user_id"] = pending.actor_user_id
        try:
            result = await self.mcp.call_tool(pending.tool_name, arguments)
            payload = json.dumps(result, ensure_ascii=False, default=str)
            if (
                isinstance(result, dict)
                and result.get("is_active", True)
                and isinstance(result.get("stock"), int)
                and isinstance(result.get("min_stock"), int)
                and result["stock"] <= result["min_stock"]
            ):
                low_stock_warning = (
                    f"\n\n⚠️ Низкий остаток: {result['stock']} шт.; "
                    f"минимум — {result['min_stock']} шт."
                )
        except Exception as exc:
            success = False
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False)

        self._last_confirmed[chat_id] = {
            "tool_name": pending.tool_name,
            "arguments": dict(arguments),
            "success": success,
        }

        messages = list(pending.messages)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": pending.tool_call_id,
                "content": payload,
            }
        )
        answer = await self._run(
            chat_id, messages, pending.tools, pending.allowed_write_tools,
            actor_user_id=pending.actor_user_id, actor_role=pending.actor_role,
        )
        if low_stock_warning and "низк" not in answer.casefold() and "дефиц" not in answer.casefold():
            answer += low_stock_warning
        return answer

    async def answer(
        self,
        chat_id: int,
        text: str,
        allowed_write_tools: set[str] | None = None,
        actor_user_id: int | str | None = None,
        actor_role: str = "viewer",
    ) -> str:
        if self.has_pending_confirmation(chat_id):
            return (
                "Сначала подтвердите или отмените предыдущую операцию. "
                "Используйте кнопки под сообщением."
            )

        allowed_write_tools = set(allowed_write_tools or set())
        raw_tools = await self.mcp.list_openai_tools()
        filtered = [
            tool for tool in raw_tools
            if tool["name"] not in INTERNAL_TOOLS
            and (tool["name"] not in WRITE_TOOLS or tool["name"] in allowed_write_tools)
        ]
        tools = self._chat_tools(filtered)
        history = list(self._history.get(chat_id, []))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": text},
        ]
        return await self._run(
            chat_id, messages, tools, allowed_write_tools,
            actor_user_id=str(actor_user_id or ""), actor_role=actor_role,
        )

    async def _run(
        self,
        chat_id: int,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        allowed_write_tools: set[str],
        actor_user_id: str = "",
        actor_role: str = "viewer",
    ) -> str:
        for _ in range(8):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            message = response.choices[0].message
            tool_calls = list(message.tool_calls or [])

            if not tool_calls:
                answer = message.content or "Готово."
                messages.append({"role": "assistant", "content": answer})
                self._history[chat_id] = messages[1:][-40:]
                return answer

            write_call = next(
                (call for call in tool_calls if call.function.name in WRITE_TOOLS),
                None,
            )
            if write_call is not None:
                if write_call.function.name not in allowed_write_tools:
                    return "У вашей роли нет прав на эту операцию."
                assistant_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [self._serialize_tool_call(write_call)],
                }
                pending_messages = [*messages, assistant_message]
                try:
                    arguments = json.loads(write_call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Модель вернула некорректные аргументы инструмента") from exc
                self._pending[chat_id] = PendingWrite(
                    tool_name=write_call.function.name,
                    arguments=arguments,
                    tool_call_id=write_call.id,
                    messages=pending_messages,
                    tools=tools,
                    allowed_write_tools=set(allowed_write_tools),
                    actor_user_id=actor_user_id,
                    actor_role=actor_role,
                )
                return self._confirmation_text(write_call.function.name, arguments)

            assistant_message = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": [self._serialize_tool_call(call) for call in tool_calls],
            }
            messages.append(assistant_message)

            for call in tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                    result = await self.mcp.call_tool(call.function.name, arguments)
                    payload = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as exc:
                    payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": payload,
                    }
                )

        raise RuntimeError("Превышен лимит последовательных вызовов инструментов")

    @staticmethod
    def _serialize_tool_call(call: Any) -> dict[str, Any]:
        return {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.function.name,
                "arguments": call.function.arguments,
            },
        }

    @staticmethod
    def _chat_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", tool["name"]),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for tool in mcp_tools
        ]

    @staticmethod
    def _confirmation_text(tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "create_product":
            return (
                "Требуется подтверждение.\n"
                f"Создать товар {args.get('sku', '—')} — {args.get('name', '—')}\n"
                f"Цена: {args.get('price', '—')} ₽; остаток: {args.get('initial_stock', 0)}; "
                f"минимум: {args.get('min_stock', 0)}"
            )
        if tool_name == "stock_operation":
            return (
                "Требуется подтверждение.\n"
                f"Операция: {args.get('operation', '—')}; SKU: {args.get('sku', '—')}; "
                f"количество: {args.get('quantity', '—')}.\n"
                f"Причина: {args.get('reason') or '—'}; документ: {args.get('document_ref') or '—'}"
            )
        if tool_name == "adjust_stock":
            delta = args.get("delta", 0)
            sign = "+" if isinstance(delta, (int, float)) and delta > 0 else ""
            return (
                "Требуется подтверждение.\n"
                f"Изменить остаток {args.get('sku', '—')} на {sign}{delta}.\n"
                f"Причина: {args.get('reason', '—')}"
            )
        if tool_name == "set_stock":
            return (
                "Требуется подтверждение.\n"
                f"Установить остаток {args.get('sku', '—')} = {args.get('quantity', '—')}.\n"
                f"Причина: {args.get('reason', '—')}"
            )
        if tool_name == "update_product":
            fields = ", ".join(
                f"{key}={value}"
                for key, value in args.items()
                if key != "sku" and value is not None
            ) or "без изменений"
            return "Требуется подтверждение.\n" f"Изменить товар {args.get('sku', '—')}: {fields}"
        if tool_name == "import_products":
            rows = args.get("rows") or []
            return f"Требуется подтверждение. Импортировать {len(rows)} строк каталога?"
        if tool_name == "create_supplier":
            return (
                "Требуется подтверждение.\n"
                f"Создать поставщика {args.get('code', '—')} — {args.get('name', '—')}?"
            )
        if tool_name == "create_purchase_order":
            items = args.get("items") or []
            return (
                "Требуется подтверждение.\n"
                f"Создать закупку {args.get('order_no', '—')} у {args.get('supplier_code', '—')} "
                f"на {len(items)} поз.?"
            )
        if tool_name == "receive_purchase_order":
            return f"Требуется подтверждение. Принять закупку {args.get('order_no', '—')} и оприходовать товар?"
        if tool_name == "create_sales_order":
            items = args.get("items") or []
            return (
                "Требуется подтверждение.\n"
                f"Создать заказ {args.get('order_no', '—')} для {args.get('customer_name') or 'клиента'} "
                f"на {len(items)} поз.?"
            )
        if tool_name == "complete_sales_order":
            return f"Требуется подтверждение. Завершить заказ {args.get('order_no', '—')} и списать товар со склада?"
        if tool_name == "create_customer":
            return f"Требуется подтверждение. Создать клиента {args.get('code', '—')} — {args.get('name', '—')}?"
        if tool_name == "reserve_sales_order":
            return f"Требуется подтверждение. Зарезервировать товар по заказу {args.get('order_no', '—')}?"
        if tool_name == "release_sales_reservation":
            return f"Требуется подтверждение. Снять резерв заказа {args.get('order_no', '—')}?"
        if tool_name == "start_sales_processing":
            return f"Требуется подтверждение. Передать заказ {args.get('order_no', '—')} в обработку?"
        if tool_name == "ship_sales_order":
            items = args.get('items') or []
            suffix = f" ({len(items)} поз.)" if items else " полностью"
            return f"Требуется подтверждение. Отгрузить заказ {args.get('order_no', '—')}{suffix}?"
        if tool_name == "create_warehouse":
            return (
                "Требуется подтверждение.\n"
                f"Создать склад {args.get('code', '—')} — {args.get('name', '—')}?"
            )
        if tool_name == "transfer_between_warehouses":
            return (
                "Требуется подтверждение.\n"
                f"Переместить {args.get('quantity', '—')} ед. {args.get('sku', '—')} "
                f"со склада {args.get('from_warehouse', '—')} на {args.get('to_warehouse', '—')}?"
            )
        if tool_name == "seed_demo_data":
            return "Требуется подтверждение. Добавить стартовые товары в пустой каталог?"
        return f"Требуется подтверждение операции {tool_name}."
