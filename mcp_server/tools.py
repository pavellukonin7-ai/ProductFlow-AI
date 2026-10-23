from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from mcp_server.models import InventorySummaryOut, MovementOut, ProductOut
from mcp_server.repository import ProductRepository
from mcp_server.commerce import CommerceRepository
from mcp_server.warehouse import WarehouseRepository
from mcp_server.audit import AuditRepository
from mcp_server.crm import CustomerRepository, OrderWorkflowRepository


def register_tools(mcp: MCPServer, repository: ProductRepository) -> None:
    commerce = CommerceRepository(repository.db)
    warehouses = WarehouseRepository(repository.db)
    audit = AuditRepository(repository.db)
    customers = CustomerRepository(repository.db)
    workflow = OrderWorkflowRepository(repository.db)
    @mcp.tool(title="Создать товар")
    def create_product(
        sku: str,
        name: str,
        category: str,
        price: float,
        initial_stock: int = 0,
        min_stock: int = 0,
        description: str = "",
        purchase_price: float = 0,
        supplier: str = "",
        barcode: str = "",
        unit: str = "шт.",
    ) -> ProductOut:
        """Создать товар. Цена и закупочная цена указываются в рублях."""
        return repository.create_product(
            sku=sku,
            name=name,
            category=category,
            price=price,
            initial_stock=initial_stock,
            min_stock=min_stock,
            description=description,
            purchase_price=purchase_price,
            supplier=supplier,
            barcode=barcode,
            unit=unit,
        )

    @mcp.tool(title="Получить товар")
    def get_product(sku: str) -> ProductOut:
        """Получить полную карточку товара по точному SKU."""
        return repository.get_product(sku)

    @mcp.tool(title="Найти товары")
    def search_products(
        query: str = "",
        category: str | None = None,
        in_stock_only: bool = False,
        active_only: bool = True,
        limit: int = 20,
    ) -> list[ProductOut]:
        """Искать товары по SKU, названию, описанию, поставщику или штрихкоду."""
        return repository.search_products(
            query=query,
            category=category,
            in_stock_only=in_stock_only,
            active_only=active_only,
            limit=limit,
        )

    @mcp.tool(title="Изменить карточку товара")
    def update_product(
        sku: str,
        name: str | None = None,
        category: str | None = None,
        price: float | None = None,
        purchase_price: float | None = None,
        min_stock: int | None = None,
        description: str | None = None,
        supplier: str | None = None,
        barcode: str | None = None,
        unit: str | None = None,
        is_active: bool | None = None,
    ) -> ProductOut:
        """Изменить поля карточки. Остаток меняется отдельными складскими инструментами."""
        return repository.update_product(
            sku=sku,
            name=name,
            category=category,
            price=price,
            purchase_price=purchase_price,
            min_stock=min_stock,
            description=description,
            supplier=supplier,
            barcode=barcode,
            unit=unit,
            is_active=is_active,
        )

    @mcp.tool(title="Изменить остаток")
    def adjust_stock(
        sku: str,
        delta: int,
        reason: str,
        movement_type: str = "adjustment",
        document_ref: str = "",
        comment: str = "",
    ) -> ProductOut:
        """Изменить остаток на signed delta и сохранить тип, документ и комментарий."""
        return repository.adjust_stock(
            sku=sku,
            delta=delta,
            reason=reason,
            movement_type=movement_type,
            document_ref=document_ref,
            comment=comment,
        )

    @mcp.tool(title="Складская операция")
    def stock_operation(
        sku: str,
        operation: str,
        quantity: int,
        reason: str = "",
        document_ref: str = "",
        comment: str = "",
    ) -> ProductOut:
        """Провести receipt, sale, return, writeoff или adjustment с журналированием."""
        return repository.stock_operation(
            sku=sku,
            operation=operation,
            quantity=quantity,
            reason=reason,
            document_ref=document_ref,
            comment=comment,
        )

    @mcp.tool(title="Установить остаток")
    def set_stock(
        sku: str,
        quantity: int,
        reason: str,
        document_ref: str = "",
        comment: str = "",
    ) -> ProductOut:
        """Установить точное количество товара и записать корректировку."""
        return repository.set_stock(
            sku=sku,
            quantity=quantity,
            reason=reason,
            document_ref=document_ref,
            comment=comment,
        )

    @mcp.tool(title="Отчёт по дефициту")
    def low_stock_report(limit: int = 50) -> list[ProductOut]:
        """Вернуть активные товары с остатком меньше либо равным минимуму."""
        return repository.low_stock_report(limit=limit)

    @mcp.tool(title="Сводка склада")
    def inventory_summary() -> InventorySummaryOut:
        """Вернуть товары, единицы, дефицит, розничную и закупочную стоимость остатков."""
        return repository.inventory_summary()

    @mcp.tool(title="История движений")
    def movement_history(sku: str | None = None, limit: int = 50) -> list[MovementOut]:
        """Вернуть журнал складских операций по одному SKU или по всему складу."""
        return repository.movement_history(sku=sku, limit=limit)

    @mcp.tool(title="Импортировать товары")
    def import_products(rows: list[dict[str, Any]], update_existing: bool = True) -> dict[str, Any]:
        """Массово создать или обновить товары из нормализованных строк Excel/CSV."""
        return repository.import_products(rows, update_existing=update_existing)

    @mcp.tool(title="Заполнить стартовыми данными")
    def seed_demo_data() -> dict[str, int | str]:
        """Добавить стартовые позиции, только если каталог пуст."""
        created = repository.seed_demo_data()
        return {
            "created": created,
            "message": "Стартовые позиции добавлены" if created else "Каталог уже содержит товары",
        }

    @mcp.tool(title="Создать поставщика")
    def create_supplier(
        code: str,
        name: str,
        contact_name: str = "",
        phone: str = "",
        email: str = "",
        comment: str = "",
    ) -> dict[str, Any]:
        """Создать поставщика для закупок."""
        return commerce.create_supplier(
            code=code, name=name, contact_name=contact_name, phone=phone, email=email, comment=comment
        )

    @mcp.tool(title="Список поставщиков")
    def list_suppliers(active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        """Показать поставщиков."""
        return commerce.list_suppliers(active_only=active_only, limit=limit)

    @mcp.tool(title="Создать закупку")
    def create_purchase_order(
        order_no: str,
        supplier_code: str,
        items: list[dict[str, Any]],
        comment: str = "",
    ) -> dict[str, Any]:
        """Создать заказ поставщику. items: sku, quantity, purchase_price (необязательно)."""
        return commerce.create_purchase_order(
            order_no=order_no, supplier_code=supplier_code, items=items, comment=comment
        )

    @mcp.tool(title="Список закупок")
    def list_purchase_orders(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Показать закупки. Статусы: ordered, received, cancelled."""
        return commerce.list_purchase_orders(status=status, limit=limit)

    @mcp.tool(title="Принять закупку")
    def receive_purchase_order(order_no: str) -> dict[str, Any]:
        """Принять закупку полностью и автоматически оприходовать товары на склад."""
        return commerce.receive_purchase_order(order_no)

    @mcp.tool(title="Создать заказ клиента")
    def create_sales_order(
        order_no: str,
        customer_name: str,
        items: list[dict[str, Any]],
        comment: str = "",
        customer_code: str | None = None,
    ) -> dict[str, Any]:
        """Создать заказ клиента. Можно передать customer_code; items: sku, quantity, unit_price (необязательно)."""
        return commerce.create_sales_order(
            order_no=order_no, customer_name=customer_name, items=items, comment=comment, customer_code=customer_code
        )

    @mcp.tool(title="Список заказов клиентов")
    def list_sales_orders(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Показать заказы клиентов. Статусы: new, completed, cancelled."""
        return commerce.list_sales_orders(status=status, limit=limit)

    @mcp.tool(title="Завершить заказ клиента")
    def complete_sales_order(order_no: str) -> dict[str, Any]:
        """Завершить заказ клиента и атомарно списать товары со склада."""
        return commerce.complete_sales_order(order_no)

    @mcp.tool(title="Аналитика продаж")
    def sales_analytics(days: int = 30) -> dict[str, Any]:
        """Выручка, себестоимость, валовая прибыль, маржа и топ товаров за период."""
        return commerce.sales_analytics(days=days)

    @mcp.tool(title="Бизнес-dashboard")
    def business_dashboard(days: int = 7) -> dict[str, Any]:
        """Сводка склада, закупок, заказов, продаж и прибыли за период."""
        return commerce.dashboard(days=days)

    @mcp.tool(title="Создать склад")
    def create_warehouse(code: str, name: str, location: str = "") -> dict[str, Any]:
        """Создать дополнительный склад. MAIN — основной склад и создаётся автоматически."""
        return warehouses.create_warehouse(code=code, name=name, location=location)

    @mcp.tool(title="Список складов")
    def list_warehouses(active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        """Вернуть склады и количество размещённых на них единиц товара."""
        return warehouses.list_warehouses(active_only=active_only, limit=limit)

    @mcp.tool(title="Остатки склада")
    def warehouse_stock(warehouse_code: str = "MAIN", query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """Показать остатки товаров на конкретном складе."""
        return warehouses.stock(warehouse_code=warehouse_code, query=query, limit=limit)

    @mcp.tool(title="Распределение товара по складам")
    def product_warehouse_distribution(sku: str) -> list[dict[str, Any]]:
        """Показать, как общий остаток SKU распределён по активным складам."""
        return warehouses.product_distribution(sku)

    @mcp.tool(title="Переместить товар между складами")
    def transfer_between_warehouses(
        sku: str,
        quantity: int,
        from_warehouse: str,
        to_warehouse: str,
        reason: str = "Перемещение между складами",
        document_ref: str = "",
        actor_user_id: str = "",
    ) -> dict[str, Any]:
        """Переместить товар между складами без изменения общего остатка."""
        return warehouses.transfer(
            sku=sku, quantity=quantity, from_warehouse=from_warehouse, to_warehouse=to_warehouse,
            reason=reason, document_ref=document_ref, actor_user_id=actor_user_id,
        )

    @mcp.tool(title="История перемещений между складами")
    def warehouse_movements(limit: int = 50) -> list[dict[str, Any]]:
        """Вернуть последние перемещения между складами."""
        return warehouses.movements(limit=limit)

    @mcp.tool(title="Записать событие аудита")
    def record_audit_event(
        actor_user_id: str, actor_role: str, action: str, entity_type: str = "",
        entity_id: str = "", details: dict[str, Any] | None = None, success: bool = True,
    ) -> dict[str, Any]:
        """Внутренний инструмент: записать административное действие в аудит."""
        return audit.record(
            actor_user_id=actor_user_id, actor_role=actor_role, action=action,
            entity_type=entity_type, entity_id=entity_id, details=details, success=success,
        )

    @mcp.tool(title="Журнал аудита")
    def list_audit_events(
        actor_user_id: str | None = None, action: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Показать последние административные и складские действия."""
        return audit.list(actor_user_id=actor_user_id, action=action, limit=limit)

    @mcp.tool(title="Создать клиента")
    def create_customer(
        code: str, name: str, contact_name: str = "", phone: str = "", email: str = "",
        address: str = "", comment: str = "",
    ) -> dict[str, Any]:
        """Создать клиента/контрагента для заказов."""
        return customers.create_customer(
            code=code, name=name, contact_name=contact_name, phone=phone, email=email,
            address=address, comment=comment,
        )

    @mcp.tool(title="Список клиентов")
    def list_customers(query: str = "", active_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        """Искать клиентов и показывать их оборот."""
        return customers.list_customers(query=query, active_only=active_only, limit=limit)

    @mcp.tool(title="Карточка клиента")
    def get_customer(code: str) -> dict[str, Any]:
        """Карточка клиента с количеством заказов, выручкой и валовой прибылью."""
        return customers.get_customer(code)

    @mcp.tool(title="История заказов клиента")
    def customer_order_history(code: str, limit: int = 50) -> list[dict[str, Any]]:
        """Последние заказы одного клиента."""
        return customers.customer_orders(code, limit=limit)

    @mcp.tool(title="Доступность товара")
    def product_availability(sku: str) -> dict[str, Any]:
        """Физический остаток, резерв и доступно к продаже на MAIN."""
        return workflow.availability(sku)

    @mcp.tool(title="Зарезервировать заказ")
    def reserve_sales_order(order_no: str) -> dict[str, Any]:
        """Зарезервировать все ещё не отгруженные позиции заказа на MAIN без списания физического остатка."""
        return workflow.reserve(order_no)

    @mcp.tool(title="Снять резерв заказа")
    def release_sales_reservation(order_no: str) -> dict[str, Any]:
        """Снять резерв до первой отгрузки и вернуть заказ в статус new."""
        return workflow.release(order_no)

    @mcp.tool(title="Передать заказ в обработку")
    def start_sales_processing(order_no: str) -> dict[str, Any]:
        """Перевести зарезервированный заказ в processing."""
        return workflow.start_processing(order_no)

    @mcp.tool(title="Отгрузить заказ")
    def ship_sales_order(order_no: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Частично или полностью отгрузить резерв. items: sku, quantity; без items — отгрузить весь резерв."""
        return workflow.ship(order_no, items=items)

    @mcp.resource("inventory://summary")
    def inventory_summary_resource() -> str:
        summary = repository.inventory_summary()
        return (
            f"Товаров: {summary.products_total}; активных: {summary.active_products}; "
            f"единиц: {summary.units_in_stock}; дефицитных: {summary.low_stock_products}; "
            f"розничная стоимость: {summary.inventory_value:.2f} руб.; "
            f"закупочная стоимость: {summary.purchase_value:.2f} руб."
        )

    @mcp.prompt(title="Политика складского ассистента")
    def inventory_assistant_prompt() -> str:
        return (
            "Используй MCP как единственный источник данных. Не придумывай SKU, цены и остатки. "
            "Для движения склада выбирай тип операции и сохраняй причину; если есть номер заказа, "
            "накладной или другого документа — передавай его в document_ref."
        )
