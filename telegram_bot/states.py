from aiogram.fsm.state import State, StatesGroup


class AddProductState(StatesGroup):
    waiting_payload = State()


class EditProductState(StatesGroup):
    waiting_payload = State()


class MovementState(StatesGroup):
    waiting_payload = State()


class ImportCatalogState(StatesGroup):
    waiting_file = State()
    waiting_confirm = State()


class ProductCodeState(StatesGroup):
    waiting_sku = State()
