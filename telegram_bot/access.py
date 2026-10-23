from __future__ import annotations

from dataclasses import dataclass


ROLE_LEVELS = {"viewer": 1, "manager": 2, "admin": 3}


@dataclass(frozen=True)
class AccessPolicy:
    admin_user_ids: tuple[int, ...] = ()
    manager_user_ids: tuple[int, ...] = ()
    viewer_user_ids: tuple[int, ...] = ()
    legacy_allowed_user_ids: tuple[int, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(
            self.admin_user_ids
            or self.manager_user_ids
            or self.viewer_user_ids
            or self.legacy_allowed_user_ids
        )

    def role_for(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        if user_id in self.admin_user_ids:
            return "admin"
        if user_id in self.manager_user_ids:
            return "manager"
        if user_id in self.viewer_user_ids:
            return "viewer"
        if self.admin_user_ids or self.manager_user_ids or self.viewer_user_ids:
            return None
        if self.legacy_allowed_user_ids:
            return "admin" if user_id in self.legacy_allowed_user_ids else None
        # Backwards-compatible open mode: when no IDs are configured, everyone is admin.
        return "admin"

    def can(self, user_id: int | None, minimum_role: str = "viewer") -> bool:
        role = self.role_for(user_id)
        return role is not None and ROLE_LEVELS[role] >= ROLE_LEVELS[minimum_role]

    def allowed_ai_write_tools(self, user_id: int | None) -> set[str]:
        role = self.role_for(user_id)
        if role == "admin":
            return {
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
        if role == "manager":
            return {
                "adjust_stock", "stock_operation", "set_stock",
                "receive_purchase_order", "complete_sales_order",
                "reserve_sales_order", "release_sales_reservation", "start_sales_processing", "ship_sales_order",
                "transfer_between_warehouses",
            }
        return set()
