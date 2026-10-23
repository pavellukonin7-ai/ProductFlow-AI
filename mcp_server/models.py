from __future__ import annotations

from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    id: int
    sku: str
    name: str
    category: str
    price: float = Field(ge=0)
    purchase_price: float = Field(ge=0, default=0)
    stock: int = Field(ge=0)
    min_stock: int = Field(ge=0)
    description: str
    supplier: str = ""
    barcode: str = ""
    unit: str = "шт."
    is_active: bool
    created_at: str
    updated_at: str


class MovementOut(BaseModel):
    id: int
    sku: str
    product_name: str
    delta: int
    quantity_after: int = Field(ge=0)
    movement_type: str = "adjustment"
    reason: str
    document_ref: str = ""
    comment: str = ""
    unit_price: float = 0.0
    unit_cost: float = 0.0
    created_at: str


class InventorySummaryOut(BaseModel):
    products_total: int = Field(ge=0)
    active_products: int = Field(ge=0)
    categories_total: int = Field(ge=0)
    units_in_stock: int = Field(ge=0)
    low_stock_products: int = Field(ge=0)
    inventory_value: float = Field(ge=0)
    purchase_value: float = Field(ge=0, default=0)
    potential_margin: float = 0.0
