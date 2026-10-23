from pathlib import Path

import pytest

from mcp_server.database import Database
from mcp_server.repository import ProductRepository


def repo(tmp_path: Path) -> ProductRepository:
    return ProductRepository(Database(tmp_path / "test.sqlite3"))


def test_create_search_and_summary(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    item = repository.create_product(
        sku="abc-1", name="Кабель", category="Аксессуары", price=999.9,
        initial_stock=5, min_stock=2,
    )
    assert item.sku == "ABC-1"
    assert item.price == 999.9
    assert repository.search_products(query="каб")[0].sku == "ABC-1"
    summary = repository.inventory_summary()
    assert summary.products_total == 1
    assert summary.units_in_stock == 5
    assert summary.inventory_value == 4999.5


def test_stock_movements_and_low_stock(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.create_product(
        sku="M-1", name="Мышь", category="Периферия", price=1000,
        initial_stock=5, min_stock=3,
    )
    updated = repository.adjust_stock(sku="M-1", delta=-3, reason="Продажа")
    assert updated.stock == 2
    assert repository.low_stock_report()[0].sku == "M-1"
    history = repository.movement_history(sku="M-1")
    assert history[0].delta == -3
    assert history[0].quantity_after == 2


def test_negative_stock_is_rejected(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.create_product(
        sku="X-1", name="Хаб", category="Аксессуары", price=100,
        initial_stock=1, min_stock=0,
    )
    with pytest.raises(ValueError, match="Недостаточно товара"):
        repository.adjust_stock(sku="X-1", delta=-2, reason="Продажа")


def test_duplicate_sku_is_rejected(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    kwargs = dict(sku="D-1", name="Товар", category="Тест", price=10)
    repository.create_product(**kwargs)
    with pytest.raises(ValueError, match="уже существует"):
        repository.create_product(**kwargs)


def test_update_and_archive_product(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.create_product(
        sku="E-1", name="Старое имя", category="Тест", price=100,
        initial_stock=2, min_stock=1,
    )
    updated = repository.update_product(
        sku="E-1", name="Новое имя", price=150.5, min_stock=3,
    )
    assert updated.name == "Новое имя"
    assert updated.price == 150.5
    assert updated.min_stock == 3
    archived = repository.update_product(sku="E-1", is_active=False)
    assert archived.is_active is False
    assert repository.search_products(query="E-1") == []
    assert repository.search_products(query="E-1", active_only=False)[0].sku == "E-1"
