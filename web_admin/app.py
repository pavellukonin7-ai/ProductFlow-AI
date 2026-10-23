from __future__ import annotations

import html
import json
import logging
from typing import Any
from urllib.parse import quote

from starlette.applications import Starlette
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp_server.audit import AuditRepository
from mcp_server.crm import CustomerRepository, OrderWorkflowRepository
from mcp_server.commerce import CommerceRepository
from mcp_server.database import Database
from mcp_server.repository import ProductRepository
from mcp_server.warehouse import WarehouseRepository
from telegram_bot.codes import make_barcode_png, make_label_png, make_qr_png
from web_admin.config import WebSettings, load_web_settings
from web_admin.security import SessionCodec, bearer_from_headers, safe_client_name

logger = logging.getLogger(__name__)
settings: WebSettings = load_web_settings()
db = Database(settings.database_path)
products = ProductRepository(db)
commerce = CommerceRepository(db)
warehouses = WarehouseRepository(db)
audit = AuditRepository(db)
customers = CustomerRepository(db)
workflow = OrderWorkflowRepository(db)
sessions = SessionCodec(settings.session_secret, settings.session_hours)

COOKIE_NAME = "productflow_session"

CSS = """
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2f;--muted:#8ea0c6;--text:#edf2ff;--line:#263250;--accent:#67e8f9;--ok:#34d399;--bad:#fb7185;--warn:#fbbf24}
*{box-sizing:border-box}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;background:linear-gradient(180deg,#080c17,#0b1020 35%);color:var(--text)}
a{color:inherit;text-decoration:none}.layout{min-height:100vh;display:grid;grid-template-columns:230px 1fr}.side{padding:26px 18px;border-right:1px solid var(--line);background:#0b1122;position:sticky;top:0;height:100vh}.brand{font-weight:800;font-size:20px;letter-spacing:.2px;margin-bottom:28px}.brand span{color:var(--accent)}.nav a{display:block;padding:11px 12px;border-radius:10px;color:#bdc9e5;margin:4px 0}.nav a:hover{background:#18233f;color:white}.main{padding:30px;max-width:1500px;width:100%;margin:auto}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card,.panel{background:rgba(18,26,47,.94);border:1px solid var(--line);border-radius:16px;box-shadow:0 16px 40px rgba(0,0,0,.16)}.card{padding:18px}.metric{font-size:27px;font-weight:800;margin-top:7px}.panel{padding:18px;margin-top:18px}.panel h2{font-size:17px;margin:0 0 14px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #222d49;font-size:14px}th{color:#9eb0d4;font-weight:600}.pill{padding:3px 8px;border-radius:999px;background:#1e2a47;font-size:12px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
input,select,textarea,button{border:1px solid #324162;background:#0e162a;color:white;border-radius:9px;padding:10px 11px;font:inherit}textarea{min-height:96px;resize:vertical}label{display:grid;gap:6px;color:#b9c6e3;font-size:13px}.formgrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.formgrid .wide{grid-column:1/-1}.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.actions form{margin:0}.danger{background:#5b1d2a;border-color:#8b3042}.secondary{background:#1c2945;border-color:#344667}.linkbtn{display:inline-block;border:1px solid #324162;background:#1c2945;border-radius:8px;padding:7px 10px;font-weight:700}button{background:#164e63;border-color:#20738b;cursor:pointer;font-weight:700}button:hover{background:#155e75}.forms{display:flex;gap:9px;flex-wrap:wrap}.flash{padding:11px 13px;background:#173a35;border:1px solid #285b52;border-radius:10px;margin-bottom:16px}.flash.error{background:#3b1821;border-color:#6b2837}.login{min-height:100vh;display:grid;place-items:center}.loginbox{width:min(420px,92vw);padding:28px}.loginbox input{width:100%;margin:14px 0}.loginbox button{width:100%}.right{text-align:right}.nowrap{white-space:nowrap}.code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}.bar{height:8px;background:#1d2945;border-radius:99px;overflow:hidden}.bar span{display:block;height:100%;background:linear-gradient(90deg,#22d3ee,#60a5fa)}
@media(max-width:950px){.formgrid{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}.side{height:auto;position:static;border-right:0;border-bottom:1px solid var(--line)}.nav{display:flex;gap:4px;flex-wrap:wrap}.cards{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.main{padding:20px}}@media(max-width:560px){.formgrid{grid-template-columns:1fr}.cards{grid-template-columns:1fr}.main{padding:14px}.top{align-items:flex-start;flex-direction:column}table{display:block;overflow:auto}}
"""


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def money(value: float | int) -> str:
    return f"{float(value):,.2f} ₽".replace(",", " ")


def web_ok(request: Request) -> bool:
    return sessions.valid(request.cookies.get(COOKIE_NAME))


def api_ok(request: Request) -> bool:
    token = bearer_from_headers(request.headers)
    return bool(token) and hmac_compare(token, settings.api_key)


def hmac_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


def login_redirect(request: Request) -> Response | None:
    if web_ok(request):
        return None
    target = quote(str(request.url.path))
    return RedirectResponse(f"/login?next={target}", status_code=303)


def api_unauthorized() -> JSONResponse:
    return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})


def layout(title: str, body: str, *, flash: str = "", error: bool = False) -> HTMLResponse:
    flash_html = f'<div class="flash{" error" if error else ""}">{esc(flash)}</div>' if flash else ""
    return HTMLResponse(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · ProductFlow</title><style>{CSS}</style></head><body><div class="layout"><aside class="side"><div class="brand">ProductFlow <span>AI</span></div><nav class="nav"><a href="/">Dashboard</a><a href="/products">Товары</a><a href="/warehouses">Склады</a><a href="/customers">Клиенты</a><a href="/commerce">Закупки и продажи</a><a href="/audit">Аудит</a><a href="/api-info">REST API</a><a href="/logout">Выйти</a></nav></aside><main class="main"><div class="top"><div><h1 style="margin:0;font-size:25px">{esc(title)}</h1><div class="muted">ProductFlow AI · единая база Telegram, Web и API</div></div><span class="pill">localhost protected</span></div>{flash_html}{body}</main></div></body></html>""")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{v if isinstance(v, Safe) else esc(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f"<div style='overflow:auto'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


class Safe(str):
    pass


def product_dict(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else dict(model)


def request_client(request: Request) -> str:
    return safe_client_name(request.headers.get("x-productflow-client"))


def parse_item_lines(raw: str, *, price_key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2 or len(parts) > 3:
            raise ValueError(f"Строка {line_no}: формат SKU | количество | цена")
        sku = parts[0].upper()
        if not sku:
            raise ValueError(f"Строка {line_no}: SKU обязателен")
        try:
            quantity = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"Строка {line_no}: количество должно быть целым числом") from exc
        item: dict[str, Any] = {"sku": sku, "quantity": quantity}
        if len(parts) == 3 and parts[2] != "":
            item[price_key] = parts[2].replace(",", ".")
        items.append(item)
    if not items:
        raise ValueError("Добавьте хотя бы одну позицию")
    return items


def purchase_items_text(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"{x['sku']} | {x['quantity']} | {x['purchase_price']}" for x in items)


def sales_items_text(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"{x['sku']} | {x['quantity']} | {x['unit_price']}" for x in items)


def parse_ship_lines(raw: str) -> list[dict[str, Any]] | None:
    raw = raw.strip()
    if not raw:
        return None
    items: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) != 2:
            raise ValueError(f"Строка {line_no}: формат SKU | количество")
        qty = int(parts[1])
        if qty <= 0:
            raise ValueError(f"Строка {line_no}: количество должно быть больше нуля")
        items.append({"sku": parts[0].upper(), "quantity": qty})
    return items or None


def record_api(request: Request, action: str, *, success: bool, details: dict[str, Any] | None = None, entity_id: str = "") -> None:
    try:
        audit.record(actor_user_id=request_client(request), actor_role="api", action=action, entity_type="rest", entity_id=entity_id, details=details or {}, success=success)
    except Exception:
        logger.exception("REST audit write failed")


async def login_get(request: Request) -> Response:
    if web_ok(request):
        return RedirectResponse("/", status_code=303)
    error = request.query_params.get("error") == "1"
    return HTMLResponse(f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ProductFlow Login</title><style>{CSS}</style></head><body><div class="login"><div class="panel loginbox"><div class="brand">ProductFlow <span>AI</span></div><h2>Web Admin</h2><div class="muted">Доступ к складской системе</div>{'<div class="flash error">Неверный пароль</div>' if error else ''}<form method="post" action="/login"><input type="password" name="password" placeholder="Пароль администратора" autofocus required><input type="hidden" name="next" value="{esc(request.query_params.get('next','/'))}"><button type="submit">Войти</button></form></div></div></body></html>""")


async def login_post(request: Request) -> Response:
    form: FormData = await request.form()
    password = str(form.get("password") or "")
    target = str(form.get("next") or "/")
    if not hmac_compare(password, settings.admin_password):
        return RedirectResponse(f"/login?error=1&next={quote(target)}", status_code=303)
    response = RedirectResponse(target if target.startswith("/") else "/", status_code=303)
    response.set_cookie(COOKIE_NAME, sessions.issue(), max_age=settings.session_hours * 3600, httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")
    return response


async def logout(request: Request) -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


async def dashboard_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    days = max(1, min(3650, int(request.query_params.get("days", "30"))))
    data = commerce.dashboard(days=days)
    a = commerce.sales_analytics(days=days)
    cards = f"""<div class="cards"><div class="card"><div class="muted">Товаров</div><div class="metric">{data['products_total']}</div></div><div class="card"><div class="muted">Единиц на складе</div><div class="metric">{data['units_in_stock']}</div></div><div class="card"><div class="muted">Выручка · {days} дн.</div><div class="metric">{money(a['revenue'])}</div></div><div class="card"><div class="muted">Валовая прибыль</div><div class="metric ok">{money(a['gross_profit'])}</div></div></div>"""
    top = a.get("top_products", [])
    max_rev = max([float(x['revenue']) for x in top] or [1.0])
    top_rows = [[Safe(f"<span class='code'>{esc(x['sku'])}</span>"), x['name'], x['units'], money(x['revenue']), Safe(f"<div class='bar'><span style='width:{max(2,float(x['revenue'])/max_rev*100):.1f}%'></span></div>")] for x in top]
    low = products.low_stock_report(limit=10)
    low_rows = [[Safe(f"<span class='code'>{esc(x.sku)}</span>"), x.name, x.stock, x.min_stock] for x in low]
    body = cards + f"""<div class="grid2"><section class="panel"><h2>Бизнес</h2><div>Маржа: <b>{a['gross_margin_percent']:.2f}%</b></div><div>Завершённых заказов: <b>{a['orders_count']}</b></div><div>Продано: <b>{a['units_net']} ед.</b></div><div>Себестоимость: <b>{money(a['cost'])}</b></div></section><section class="panel"><h2>Склад</h2><div>Розничная стоимость: <b>{money(data['inventory_retail_value'])}</b></div><div>Закупочная стоимость: <b>{money(data['inventory_cost_value'])}</b></div><div>Дефицитных: <b class="{'bad' if data['low_stock_products'] else 'ok'}">{data['low_stock_products']}</b></div><div>Активных поставщиков: <b>{data['active_suppliers']}</b></div></section></div><section class="panel"><h2>Топ товаров по выручке</h2>{table(['SKU','Товар','Ед.','Выручка',''], top_rows) if top_rows else '<div class="muted">Продаж за период нет.</div>'}</section><section class="panel"><h2>Дефицит</h2>{table(['SKU','Товар','Остаток','Минимум'], low_rows) if low_rows else '<div class="ok">Дефицитных позиций нет.</div>'}</section>"""
    return layout("Dashboard", body)


async def products_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    q = request.query_params.get("q", "")
    rows = products.search_products(query=q, active_only=False, limit=200)
    data = []
    for x in rows:
        status = Safe("<span class='ok'>активен</span>" if x.is_active else "<span class='muted'>архив</span>")
        actions = Safe(f"<a class='linkbtn' href='/products/{quote(x.sku)}'>Открыть</a> <a class='linkbtn' href='/media/label/{quote(x.sku)}'>Этикетка</a>")
        data.append([Safe(f"<span class='code'>{esc(x.sku)}</span>"), x.name, x.category, money(x.price), money(x.purchase_price), x.stock, x.min_stock, status, actions])
    flash = request.query_params.get("ok", "")
    err = request.query_params.get("error", "")
    create = """<section class='panel' style='margin-top:0'><h2>Создать товар</h2><form method='post' action='/actions/product/create' class='formgrid'>
    <label>SKU<input name='sku' placeholder='NEW-001' required></label><label>Название<input name='name' required></label><label>Категория<input name='category' value='Без категории'></label>
    <label>Цена продажи<input name='price' type='number' min='0' step='0.01' value='0' required></label><label>Закупочная цена<input name='purchase_price' type='number' min='0' step='0.01' value='0'></label><label>Начальный остаток<input name='initial_stock' type='number' min='0' value='0'></label>
    <label>Минимальный остаток<input name='min_stock' type='number' min='0' value='0'></label><label>Единица<input name='unit' value='шт.'></label><label>Штрихкод<input name='barcode'></label>
    <label>Поставщик<input name='supplier'></label><label class='wide'>Описание<textarea name='description'></textarea></label><div class='wide'><button>Создать товар</button></div></form></section>"""
    body = create + f"""<section class='panel'><form class='forms' method='get'><input name='q' value='{esc(q)}' placeholder='SKU, название, штрихкод'><button>Поиск</button></form></section><section class='panel'><h2>Каталог · {len(rows)}</h2>{table(['SKU','Название','Категория','Цена','Закупка','Остаток','Мин.','Статус','Действия'], data)}</section>"""
    return layout("Товары", body, flash=flash or err, error=bool(err))


async def product_detail_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    sku = request.path_params['sku']
    try:
        x = products.get_product(sku)
        distribution = warehouses.product_distribution(sku)
    except Exception as exc:
        return layout("Товар", f"<section class='panel'><div class='bad'>{esc(exc)}</div></section>", error=True)
    dist_rows = [[d['warehouse_code'], d['warehouse_name'], d['quantity']] for d in distribution]
    checked = 'checked' if x.is_active else ''
    body = f"""<section class='panel' style='margin-top:0'><div class='actions'><a class='linkbtn' href='/products'>← Каталог</a><a class='linkbtn' href='/media/label/{quote(x.sku)}'>Этикетка</a><a class='linkbtn' href='/media/qr/{quote(x.sku)}'>QR</a><a class='linkbtn' href='/media/barcode/{quote(x.sku)}'>Code128</a></div></section>
    <section class='panel'><h2>{esc(x.name)} · <span class='code'>{esc(x.sku)}</span></h2><form method='post' action='/actions/product/{quote(x.sku)}/update' class='formgrid'>
    <label>Название<input name='name' value='{esc(x.name)}' required></label><label>Категория<input name='category' value='{esc(x.category)}'></label><label>Единица<input name='unit' value='{esc(x.unit)}'></label>
    <label>Цена продажи<input name='price' type='number' min='0' step='0.01' value='{x.price}'></label><label>Закупочная цена<input name='purchase_price' type='number' min='0' step='0.01' value='{x.purchase_price}'></label><label>Минимальный остаток<input name='min_stock' type='number' min='0' value='{x.min_stock}'></label>
    <label>Поставщик<input name='supplier' value='{esc(x.supplier)}'></label><label>Штрихкод<input name='barcode' value='{esc(x.barcode)}'></label><label style='align-content:end'><span>Статус</span><span><input style='width:auto' type='checkbox' name='is_active' value='1' {checked}> активен</span></label>
    <label class='wide'>Описание<textarea name='description'>{esc(x.description)}</textarea></label><div class='wide'><button>Сохранить изменения</button></div></form></section>
    <div class='grid2'><section class='panel'><h2>Остаток</h2><div class='metric'>{x.stock} {esc(x.unit)}</div><div class='muted'>Минимум: {x.min_stock}</div>{table(['Склад','Название','Кол-во'],dist_rows)}</section>
    <section class='panel'><h2>Складская операция</h2><form method='post' action='/actions/stock' class='formgrid'><input type='hidden' name='sku' value='{esc(x.sku)}'><label>Операция<select name='operation'><option value='receipt'>Приход</option><option value='sale'>Продажа</option><option value='return'>Возврат</option><option value='writeoff'>Списание</option><option value='adjustment'>Корректировка</option></select></label><label>Количество<input name='quantity' type='number' required></label><label>Документ<input name='document_ref'></label><label class='wide'>Причина<input name='reason' value='Web Admin'></label><label class='wide'>Комментарий<input name='comment'></label><div class='wide'><button>Провести операцию</button></div></form></section></div>"""
    return layout(f"Товар {x.sku}", body, flash=request.query_params.get('ok','') or request.query_params.get('error',''), error=bool(request.query_params.get('error')))


async def product_create_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    payload = {k: str(form.get(k) or '') for k in ['sku','name','category','price','purchase_price','initial_stock','min_stock','description','supplier','barcode','unit']}
    try:
        item = products.create_product(sku=payload['sku'], name=payload['name'], category=payload['category'], price=payload['price'] or 0, purchase_price=payload['purchase_price'] or 0, initial_stock=int(payload['initial_stock'] or 0), min_stock=int(payload['min_stock'] or 0), description=payload['description'], supplier=payload['supplier'], barcode=payload['barcode'], unit=payload['unit'] or 'шт.')
        audit.record(actor_user_id='web-admin', actor_role='admin', action='product.create', entity_type='web', entity_id=item.sku, details=payload)
        return RedirectResponse('/products?ok=' + quote(f'Товар {item.sku} создан'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='product.create', entity_type='web', entity_id=payload['sku'], details={'error':str(exc)}, success=False)
        return RedirectResponse('/products?error=' + quote(str(exc)), status_code=303)


async def product_update_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    sku = request.path_params['sku']
    form = await request.form()
    try:
        item = products.update_product(sku=sku, name=str(form.get('name') or ''), category=str(form.get('category') or ''), price=str(form.get('price') or '0'), purchase_price=str(form.get('purchase_price') or '0'), min_stock=int(form.get('min_stock') or 0), description=str(form.get('description') or ''), supplier=str(form.get('supplier') or ''), barcode=str(form.get('barcode') or ''), unit=str(form.get('unit') or 'шт.'), is_active=form.get('is_active') == '1')
        audit.record(actor_user_id='web-admin', actor_role='admin', action='product.update', entity_type='web', entity_id=sku, details={'name':item.name,'is_active':item.is_active})
        return RedirectResponse(f'/products/{quote(sku)}?ok=' + quote('Товар обновлён'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='product.update', entity_type='web', entity_id=sku, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/products/{quote(sku)}?error=' + quote(str(exc)), status_code=303)


async def stock_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    sku = str(form.get('sku') or '')
    try:
        item = products.stock_operation(sku=sku, operation=str(form.get('operation') or ''), quantity=int(form.get('quantity') or 0), reason=str(form.get('reason') or 'Web Admin'), document_ref=str(form.get('document_ref') or ''), comment=str(form.get('comment') or ''))
        audit.record(actor_user_id='web-admin', actor_role='admin', action='stock.operation', entity_type='web', entity_id=sku, details={'operation':str(form.get('operation') or ''),'quantity':int(form.get('quantity') or 0)})
        return RedirectResponse(f'/products/{quote(sku)}?ok=' + quote(f'Остаток: {item.stock}'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='stock.operation', entity_type='web', entity_id=sku, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/products/{quote(sku)}?error=' + quote(str(exc)), status_code=303)


async def warehouses_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    whs = warehouses.list_warehouses(active_only=False, limit=100)
    wh_rows = [[Safe(f"<span class='code'>{esc(w['code'])}</span>"), w['name'], w['location'] or '—', w['units'], w['products_with_stock']] for w in whs]
    recent = warehouses.movements(limit=30)
    mv_rows = [[x['created_at'], Safe(f"<span class='code'>{esc(x['sku'])}</span>"), f"{x.get('from_code') or '—'} → {x.get('to_code') or '—'}", x['quantity'], x.get('document_ref') or '—'] for x in recent]
    flash = request.query_params.get("ok", "")
    err = request.query_params.get("error", "")
    forms = """<div class="grid2"><section class="panel" style="margin-top:0"><h2>Создать склад</h2><form method="post" action="/actions/warehouse" class="forms"><input name="code" placeholder="CODE" required><input name="name" placeholder="Название" required><input name="location" placeholder="Локация"><button>Создать</button></form></section><section class="panel" style="margin-top:0"><h2>Перемещение</h2><form method="post" action="/actions/transfer" class="forms"><input name="sku" placeholder="SKU" required><input name="quantity" type="number" min="1" placeholder="Кол-во" required><input name="from_warehouse" placeholder="FROM" value="MAIN" required><input name="to_warehouse" placeholder="TO" required><input name="document_ref" placeholder="Документ"><button>Переместить</button></form></section></div>"""
    body = forms + f"<section class='panel'><h2>Склады</h2>{table(['Код','Название','Локация','Единиц','Позиций'],wh_rows)}</section><section class='panel'><h2>Последние перемещения</h2>{table(['Время','SKU','Маршрут','Кол-во','Документ'],mv_rows)}</section>"
    return layout("Склады", body, flash=flash or err, error=bool(err))


async def warehouse_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    try:
        item = warehouses.create_warehouse(code=str(form.get('code') or ''), name=str(form.get('name') or ''), location=str(form.get('location') or ''))
        audit.record(actor_user_id="web-admin", actor_role="admin", action="warehouse.create", entity_type="web", entity_id=item['code'], details={"name": item['name']})
        return RedirectResponse("/warehouses?ok=" + quote(f"Склад {item['code']} создан"), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id="web-admin", actor_role="admin", action="warehouse.create", entity_type="web", details={"error": str(exc)}, success=False)
        return RedirectResponse("/warehouses?error=" + quote(str(exc)), status_code=303)


async def transfer_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    payload = {k: str(form.get(k) or '') for k in ['sku','from_warehouse','to_warehouse','document_ref']}
    try:
        result = warehouses.transfer(sku=payload['sku'], quantity=int(form.get('quantity') or 0), from_warehouse=payload['from_warehouse'], to_warehouse=payload['to_warehouse'], reason="Web Admin", document_ref=payload['document_ref'], actor_user_id="web-admin")
        audit.record(actor_user_id="web-admin", actor_role="admin", action="warehouse.transfer", entity_type="web", entity_id=result['sku'], details=result)
        return RedirectResponse("/warehouses?ok=" + quote("Перемещение выполнено"), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id="web-admin", actor_role="admin", action="warehouse.transfer", entity_type="web", entity_id=payload['sku'], details={**payload,"error":str(exc)}, success=False)
        return RedirectResponse("/warehouses?error=" + quote(str(exc)), status_code=303)


async def customers_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    q = request.query_params.get("q", "")
    rows = customers.list_customers(query=q, active_only=False, limit=200)
    table_rows = [
        [Safe(f"<a class='code' href='/customers/{quote(x['code'])}'>{esc(x['code'])}</a>"), x['name'],
         x['contact_name'] or '—', x['phone'] or '—', x['orders_count'], money(x['revenue']),
         Safe("<span class='ok'>активен</span>" if x['is_active'] else "<span class='muted'>архив</span>")]
        for x in rows
    ]
    form = """<section class='panel' style='margin-top:0'><h2>Новый клиент / контрагент</h2><form method='post' action='/actions/customer/create' class='formgrid'>
    <label>Код<input name='code' placeholder='CLIENT-001' required></label><label>Название<input name='name' required></label><label>Контакт<input name='contact_name'></label>
    <label>Телефон<input name='phone'></label><label>Email<input name='email' type='email'></label><label>Адрес<input name='address'></label>
    <label class='wide'>Комментарий<input name='comment'></label><div class='wide'><button>Создать клиента</button></div></form></section>"""
    body = form + f"<section class='panel'><form class='forms' method='get'><input name='q' value='{esc(q)}' placeholder='Код, название, телефон, email'><button>Поиск</button></form></section><section class='panel'><h2>Клиенты · {len(rows)}</h2>{table(['Код','Название','Контакт','Телефон','Заказов','Выручка','Статус'],table_rows)}</section>"
    return layout('Клиенты', body, flash=request.query_params.get('ok','') or request.query_params.get('error',''), error=bool(request.query_params.get('error')))


async def customer_detail_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    code = request.path_params['code']
    try:
        x = customers.get_customer(code)
        orders = customers.customer_orders(code, limit=100)
    except Exception as exc:
        return layout('Клиент', f"<section class='panel'><div class='bad'>{esc(exc)}</div></section>", error=True)
    checked = 'checked' if x['is_active'] else ''
    order_rows = [[Safe(f"<a class='code' href='/sales/{quote(o['order_no'])}'>{esc(o['order_no'])}</a>"), o['status'], money(o['revenue']), money(o['gross_profit']), o['created_at']] for o in orders]
    body = f"""<section class='panel' style='margin-top:0'><div class='actions'><a class='linkbtn' href='/customers'>← Клиенты</a></div></section>
    <section class='panel'><h2>{esc(x['name'])} · <span class='code'>{esc(x['code'])}</span></h2><form method='post' action='/actions/customer/{quote(x['code'])}/update' class='formgrid'>
    <label>Название<input name='name' value='{esc(x['name'])}' required></label><label>Контакт<input name='contact_name' value='{esc(x['contact_name'])}'></label><label>Телефон<input name='phone' value='{esc(x['phone'])}'></label>
    <label>Email<input name='email' type='email' value='{esc(x['email'])}'></label><label>Адрес<input name='address' value='{esc(x['address'])}'></label><label style='align-content:end'><span>Статус</span><span><input style='width:auto' type='checkbox' name='is_active' value='1' {checked}> активен</span></label>
    <label class='wide'>Комментарий<input name='comment' value='{esc(x['comment'])}'></label><div class='wide'><button>Сохранить клиента</button></div></form></section>
    <div class='grid2'><section class='panel'><h2>История клиента</h2><div>Заказов: <b>{x['orders_count']}</b></div><div>Завершено: <b>{x['completed_orders']}</b></div><div>Выручка: <b>{money(x['revenue'])}</b></div><div>Валовая прибыль: <b class='ok'>{money(x['gross_profit'])}</b></div></section>
    <section class='panel'><h2>Контакты</h2><div>{esc(x['contact_name'] or '—')}</div><div>{esc(x['phone'] or '—')}</div><div>{esc(x['email'] or '—')}</div><div>{esc(x['address'] or '—')}</div></section></div>
    <section class='panel'><h2>Заказы</h2>{table(['Номер','Статус','Выручка','Валовая прибыль','Создан'],order_rows) if order_rows else '<div class="muted">Заказов пока нет.</div>'}</section>"""
    return layout(f"Клиент {x['code']}", body, flash=request.query_params.get('ok','') or request.query_params.get('error',''), error=bool(request.query_params.get('error')))


async def customer_create_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    try:
        item = customers.create_customer(code=str(form.get('code') or ''), name=str(form.get('name') or ''), contact_name=str(form.get('contact_name') or ''), phone=str(form.get('phone') or ''), email=str(form.get('email') or ''), address=str(form.get('address') or ''), comment=str(form.get('comment') or ''))
        audit.record(actor_user_id='web-admin', actor_role='admin', action='customer.create', entity_type='web', entity_id=item['code'], details={'name':item['name']})
        return RedirectResponse(f"/customers/{quote(item['code'])}?ok=" + quote('Клиент создан'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='customer.create', entity_type='web', details={'error':str(exc)}, success=False)
        return RedirectResponse('/customers?error=' + quote(str(exc)), status_code=303)


async def customer_update_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    code = request.path_params['code']
    form = await request.form()
    try:
        item = customers.update_customer(code=code, name=str(form.get('name') or ''), contact_name=str(form.get('contact_name') or ''), phone=str(form.get('phone') or ''), email=str(form.get('email') or ''), address=str(form.get('address') or ''), comment=str(form.get('comment') or ''), is_active=form.get('is_active') == '1')
        audit.record(actor_user_id='web-admin', actor_role='admin', action='customer.update', entity_type='web', entity_id=code, details={'name':item['name'],'is_active':item['is_active']})
        return RedirectResponse(f'/customers/{quote(code)}?ok=' + quote('Клиент обновлён'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='customer.update', entity_type='web', entity_id=code, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/customers/{quote(code)}?error=' + quote(str(exc)), status_code=303)


async def commerce_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    po = commerce.list_purchase_orders(limit=100)
    so = commerce.list_sales_orders(limit=100)
    su = commerce.list_suppliers(active_only=False, limit=100)
    po_rows = [[Safe(f"<a class='code' href='/purchases/{quote(x['order_no'])}'>{esc(x['order_no'])}</a>"), x['supplier_name'], x['status'], x['item_count'], money(x['total']), x['created_at']] for x in po]
    so_rows = [[Safe(f"<a class='code' href='/sales/{quote(x['order_no'])}'>{esc(x['order_no'])}</a>"), x['customer_name'] or '—', x['status'], x['item_count'], money(x['revenue']), money(x['gross_profit'])] for x in so]
    su_rows = [[Safe(f"<a class='code' href='/suppliers/{quote(x['code'])}'>{esc(x['code'])}</a>"), x['name'], x['contact_name'] or '—', x['phone'] or '—', x['email'] or '—', Safe("<span class='ok'>активен</span>" if x['is_active'] else "<span class='muted'>архив</span>")] for x in su]
    flash = request.query_params.get('ok','')
    err = request.query_params.get('error','')
    supplier_form = """<section class='panel' style='margin-top:0'><h2>Новый поставщик</h2><form method='post' action='/actions/supplier/create' class='formgrid'><label>Код<input name='code' placeholder='SUP-002' required></label><label>Название<input name='name' required></label><label>Контакт<input name='contact_name'></label><label>Телефон<input name='phone'></label><label>Email<input name='email' type='email'></label><label>Комментарий<input name='comment'></label><div class='wide'><button>Создать поставщика</button></div></form></section>"""
    purchase_form = """<section class='panel'><h2>Новая закупка</h2><form method='post' action='/actions/purchase/create' class='formgrid'><label>Номер<input name='order_no' placeholder='PO-1002' required></label><label>Код поставщика<input name='supplier_code' placeholder='SUP-001' required></label><label>Комментарий<input name='comment'></label><label class='wide'>Позиции · по одной строке: SKU | количество | закупочная цена<textarea name='items' placeholder='SKU-001 | 10 | 1700\nKEY-001 | 5 | 4200' required></textarea></label><div class='wide'><button>Создать закупку</button></div></form></section>"""
    sale_form = """<section class='panel'><h2>Новый заказ клиента</h2><form method='post' action='/actions/sale/create' class='formgrid'><label>Номер<input name='order_no' placeholder='SO-1002' required></label><label>Код клиента<input name='customer_code' placeholder='CLIENT-001'></label><label>Название клиента (если без кода)<input name='customer_name'></label><label>Комментарий<input name='comment'></label><label class='wide'>Позиции · SKU | количество | цена продажи (цену можно оставить пустой)<textarea name='items' placeholder='SKU-001 | 2 | 2490\nKEY-001 | 1 |' required></textarea></label><div class='wide'><button>Создать заказ</button></div></form></section>"""
    body = supplier_form + purchase_form + sale_form + f"<section class='panel'><h2>Поставщики</h2>{table(['Код','Название','Контакт','Телефон','Email','Статус'],su_rows)}</section><section class='panel'><h2>Закупки</h2>{table(['Номер','Поставщик','Статус','Поз.','Сумма','Создан'],po_rows)}</section><section class='panel'><h2>Продажи</h2>{table(['Номер','Клиент','Статус','Поз.','Выручка','Валовая прибыль'],so_rows)}</section>"
    return layout("Закупки и продажи", body, flash=flash or err, error=bool(err))


async def supplier_detail_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    code = request.path_params['code']
    try:
        x = commerce.get_supplier(code)
    except Exception as exc:
        return layout('Поставщик', f"<section class='panel'><div class='bad'>{esc(exc)}</div></section>", error=True)
    checked = 'checked' if x['is_active'] else ''
    body = f"""<section class='panel' style='margin-top:0'><div class='actions'><a class='linkbtn' href='/commerce'>← Закупки и продажи</a></div></section><section class='panel'><h2>{esc(x['name'])} · <span class='code'>{esc(x['code'])}</span></h2><form method='post' action='/actions/supplier/{quote(x['code'])}/update' class='formgrid'><label>Название<input name='name' value='{esc(x['name'])}' required></label><label>Контакт<input name='contact_name' value='{esc(x['contact_name'])}'></label><label>Телефон<input name='phone' value='{esc(x['phone'])}'></label><label>Email<input name='email' type='email' value='{esc(x['email'])}'></label><label>Комментарий<input name='comment' value='{esc(x['comment'])}'></label><label style='align-content:end'><span>Статус</span><span><input style='width:auto' type='checkbox' name='is_active' value='1' {checked}> активен</span></label><div class='wide'><button>Сохранить поставщика</button></div></form></section>"""
    return layout(f"Поставщик {x['code']}", body, flash=request.query_params.get('ok','') or request.query_params.get('error',''), error=bool(request.query_params.get('error')))


async def purchase_detail_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        x = commerce.get_purchase_order(no)
    except Exception as exc:
        return layout('Закупка', f"<section class='panel'><div class='bad'>{esc(exc)}</div></section>", error=True)
    editable = x['status'] == 'ordered'
    readonly = '' if editable else 'disabled'
    rows = [[i['sku'], i['name'], i['quantity'], i['received_quantity'], money(i['purchase_price'])] for i in x['items']]
    actions = ""
    if x['status'] == 'ordered':
        actions = f"""<div class='actions'><form method='post' action='/actions/purchase/{quote(x['order_no'])}/receive'><button>Принять закупку</button></form><form method='post' action='/actions/purchase/{quote(x['order_no'])}/cancel'><button class='danger'>Отменить закупку</button></form></div>"""
    body = f"""<section class='panel' style='margin-top:0'><div class='actions'><a class='linkbtn' href='/commerce'>← Закупки и продажи</a><span class='pill'>Статус: {esc(x['status'])}</span></div></section><section class='panel'><h2>Закупка <span class='code'>{esc(x['order_no'])}</span> · {money(x['total'])}</h2><form method='post' action='/actions/purchase/{quote(x['order_no'])}/update' class='formgrid'><label>Поставщик<input name='supplier_code' value='{esc(x['supplier_code'])}' {readonly} required></label><label class='wide'>Комментарий<input name='comment' value='{esc(x['comment'])}' {readonly}></label><label class='wide'>Позиции · SKU | количество | закупочная цена<textarea name='items' {readonly} required>{esc(purchase_items_text(x['items']))}</textarea></label>{"<div class='wide'><button>Сохранить изменения</button></div>" if editable else "<div class='wide muted'>Документ проведён или отменён — редактирование заблокировано.</div>"}</form>{actions}</section><section class='panel'><h2>Позиции</h2>{table(['SKU','Товар','Заказано','Принято','Цена'],rows)}</section>"""
    return layout(f"Закупка {x['order_no']}", body, flash=request.query_params.get('ok','') or request.query_params.get('error',''), error=bool(request.query_params.get('error')))


async def sale_detail_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        x = commerce.get_sales_order(no)
    except Exception as exc:
        return layout('Заказ', f"<section class='panel'><div class='bad'>{esc(exc)}</div></section>", error=True)
    editable = x['status'] == 'new'
    readonly = '' if editable else 'disabled'
    rows = [[i['sku'], i['name'], i['quantity'], i.get('reserved_quantity',0), i['fulfilled_quantity'], money(i['unit_price']), money(i['unit_cost'])] for i in x['items']]
    actions: list[str] = []
    if x['status'] == 'new':
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/reserve'><button>Зарезервировать</button></form>")
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/complete'><button class='secondary'>Завершить без отдельного резерва</button></form>")
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/cancel'><button class='danger'>Отменить заказ</button></form>")
    elif x['status'] == 'reserved':
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/processing'><button>В обработку</button></form>")
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/ship'><button>Отгрузить весь резерв</button></form>")
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/release'><button class='secondary'>Снять резерв</button></form>")
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/cancel'><button class='danger'>Отменить заказ</button></form>")
    elif x['status'] == 'processing':
        actions.append(f"<form method='post' action='/actions/sale/{quote(x['order_no'])}/ship'><button>Отгрузить весь остаток резерва</button></form>")
    actions_html = f"<div class='actions'>{''.join(actions)}</div>" if actions else ''
    partial = ''
    if x['status'] in {'reserved','processing'}:
        partial = f"""<section class='panel'><h2>Частичная отгрузка</h2><form method='post' action='/actions/sale/{quote(x['order_no'])}/ship' class='formgrid'><label class='wide'>Позиции · SKU | количество<textarea name='items' placeholder='SKU-001 | 1'></textarea></label><div class='wide'><button>Отгрузить указанные позиции</button></div></form><div class='muted'>Пустой список означает отгрузить весь текущий резерв.</div></section>"""
    customer_code = x.get('customer_code') or ''
    body = f"""<section class='panel' style='margin-top:0'><div class='actions'><a class='linkbtn' href='/commerce'>← Закупки и продажи</a><span class='pill'>Статус: {esc(x['status'])}</span></div></section>
    <section class='panel'><h2>Заказ <span class='code'>{esc(x['order_no'])}</span> · {money(x['revenue'])}</h2><form method='post' action='/actions/sale/{quote(x['order_no'])}/update' class='formgrid'>
    <label>Код клиента<input name='customer_code' value='{esc(customer_code)}' {readonly}></label><label>Название клиента<input name='customer_name' value='{esc(x['customer_name'])}' {readonly}></label>
    <label class='wide'>Комментарий<input name='comment' value='{esc(x['comment'])}' {readonly}></label><label class='wide'>Позиции · SKU | количество | цена продажи<textarea name='items' {readonly} required>{esc(sales_items_text(x['items']))}</textarea></label>
    {"<div class='wide'><button>Сохранить изменения</button></div>" if editable else "<div class='wide muted'>После резерва редактирование состава заказа блокируется.</div>"}</form>{actions_html}</section>
    <section class='panel'><h2>Финансы</h2><div>Выручка: <b>{money(x['revenue'])}</b></div><div>Себестоимость: <b>{money(x['cost'])}</b></div><div>Валовая прибыль: <b class='ok'>{money(x['gross_profit'])}</b></div></section>
    <section class='panel'><h2>Позиции</h2>{table(['SKU','Товар','Заказано','Резерв','Отгружено','Цена','Себестоимость'],rows)}</section>{partial}"""
    return layout(f"Заказ {x['order_no']}", body, flash=request.query_params.get('ok','') or request.query_params.get('error',''), error=bool(request.query_params.get('error')))


async def supplier_create_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    try:
        item = commerce.create_supplier(code=str(form.get('code') or ''), name=str(form.get('name') or ''), contact_name=str(form.get('contact_name') or ''), phone=str(form.get('phone') or ''), email=str(form.get('email') or ''), comment=str(form.get('comment') or ''))
        audit.record(actor_user_id='web-admin', actor_role='admin', action='supplier.create', entity_type='web', entity_id=item['code'], details={'name':item['name']})
        return RedirectResponse('/commerce?ok=' + quote(f"Поставщик {item['code']} создан"), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='supplier.create', entity_type='web', details={'error':str(exc)}, success=False)
        return RedirectResponse('/commerce?error=' + quote(str(exc)), status_code=303)


async def supplier_update_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    code = request.path_params['code']
    form = await request.form()
    try:
        item = commerce.update_supplier(code=code, name=str(form.get('name') or ''), contact_name=str(form.get('contact_name') or ''), phone=str(form.get('phone') or ''), email=str(form.get('email') or ''), comment=str(form.get('comment') or ''), is_active=form.get('is_active') == '1')
        audit.record(actor_user_id='web-admin', actor_role='admin', action='supplier.update', entity_type='web', entity_id=code, details={'name':item['name'],'is_active':item['is_active']})
        return RedirectResponse(f'/suppliers/{quote(code)}?ok=' + quote('Поставщик обновлён'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='supplier.update', entity_type='web', entity_id=code, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/suppliers/{quote(code)}?error=' + quote(str(exc)), status_code=303)


async def purchase_create_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    try:
        item = commerce.create_purchase_order(order_no=str(form.get('order_no') or ''), supplier_code=str(form.get('supplier_code') or ''), items=parse_item_lines(str(form.get('items') or ''), price_key='purchase_price'), comment=str(form.get('comment') or ''))
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.create', entity_type='web', entity_id=item['order_no'], details={'supplier_code':item['supplier_code'],'total':item['total']})
        return RedirectResponse(f"/purchases/{quote(item['order_no'])}?ok=" + quote('Закупка создана'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.create', entity_type='web', details={'error':str(exc)}, success=False)
        return RedirectResponse('/commerce?error=' + quote(str(exc)), status_code=303)


async def purchase_update_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    form = await request.form()
    try:
        item = commerce.update_purchase_order(order_no=no, supplier_code=str(form.get('supplier_code') or ''), items=parse_item_lines(str(form.get('items') or ''), price_key='purchase_price'), comment=str(form.get('comment') or ''))
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.update', entity_type='web', entity_id=no, details={'total':item['total']})
        return RedirectResponse(f'/purchases/{quote(no)}?ok=' + quote('Закупка обновлена'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.update', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/purchases/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def purchase_receive_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        item = commerce.receive_purchase_order(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.receive', entity_type='web', entity_id=no, details={'total':item['total']})
        return RedirectResponse(f'/purchases/{quote(no)}?ok=' + quote('Закупка принята'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.receive', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/purchases/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def purchase_cancel_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        commerce.cancel_purchase_order(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.cancel', entity_type='web', entity_id=no)
        return RedirectResponse(f'/purchases/{quote(no)}?ok=' + quote('Закупка отменена'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='purchase.cancel', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/purchases/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_create_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    form = await request.form()
    try:
        item = commerce.create_sales_order(order_no=str(form.get('order_no') or ''), customer_name=str(form.get('customer_name') or ''), items=parse_item_lines(str(form.get('items') or ''), price_key='unit_price'), comment=str(form.get('comment') or ''), customer_code=str(form.get('customer_code') or '') or None)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.create', entity_type='web', entity_id=item['order_no'], details={'revenue':item['revenue']})
        return RedirectResponse(f"/sales/{quote(item['order_no'])}?ok=" + quote('Заказ создан'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.create', entity_type='web', details={'error':str(exc)}, success=False)
        return RedirectResponse('/commerce?error=' + quote(str(exc)), status_code=303)


async def sale_update_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    form = await request.form()
    try:
        item = commerce.update_sales_order(order_no=no, customer_name=str(form.get('customer_name') or ''), items=parse_item_lines(str(form.get('items') or ''), price_key='unit_price'), comment=str(form.get('comment') or ''), customer_code=str(form.get('customer_code') or '') or None)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.update', entity_type='web', entity_id=no, details={'revenue':item['revenue']})
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Заказ обновлён'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.update', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_reserve_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        item = workflow.reserve(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.reserve', entity_type='web', entity_id=no, details={'status':item['status']})
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Товар зарезервирован'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.reserve', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_release_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        workflow.release(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.release_reserve', entity_type='web', entity_id=no)
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Резерв снят'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.release_reserve', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_processing_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        workflow.start_processing(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.processing', entity_type='web', entity_id=no)
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Заказ передан в обработку'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.processing', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_ship_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    form = await request.form()
    try:
        items = parse_ship_lines(str(form.get('items') or ''))
        item = workflow.ship(no, items=items)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.ship', entity_type='web', entity_id=no, details={'items':items or 'all','status':item['status']})
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Отгрузка проведена'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.ship', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_complete_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        item = commerce.complete_sales_order(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.complete', entity_type='web', entity_id=no, details={'revenue':item['revenue'],'gross_profit':item['gross_profit']})
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Продажа завершена'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.complete', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def sale_cancel_action(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    no = request.path_params['order_no']
    try:
        commerce.cancel_sales_order(no)
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.cancel', entity_type='web', entity_id=no)
        return RedirectResponse(f'/sales/{quote(no)}?ok=' + quote('Заказ отменён'), status_code=303)
    except Exception as exc:
        audit.record(actor_user_id='web-admin', actor_role='admin', action='sale.cancel', entity_type='web', entity_id=no, details={'error':str(exc)}, success=False)
        return RedirectResponse(f'/sales/{quote(no)}?error=' + quote(str(exc)), status_code=303)


async def audit_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    rows = audit.list(limit=100)
    data=[]
    for x in rows:
        details=json.dumps(x.get('details') or {},ensure_ascii=False)
        data.append([x['created_at'], Safe("<span class='ok'>OK</span>" if x['success'] else "<span class='bad'>FAIL</span>"), x['actor_user_id'] or 'system', x['actor_role'] or '—', Safe(f"<span class='code'>{esc(x['action'])}</span>"), details[:180]])
    return layout("Аудит", f"<section class='panel' style='margin-top:0'>{table(['Время','Статус','Кто','Роль','Действие','Детали'],data)}</section>")


async def api_info_page(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    body = """<section class='panel' style='margin-top:0'><h2>REST API v1</h2><p>Все API-запросы, кроме health, требуют заголовок <span class='code'>Authorization: Bearer &lt;WEB_API_KEY&gt;</span>.</p><p>Для аудита интеграции можно передать <span class='code'>X-ProductFlow-Client: crm</span>.</p><table><tbody><tr><td>GET</td><td class='code'>/api/v1/dashboard?days=30</td></tr><tr><td>GET/POST</td><td class='code'>/api/v1/products</td></tr><tr><td>GET/PATCH</td><td class='code'>/api/v1/products/{sku}</td></tr><tr><td>POST</td><td class='code'>/api/v1/stock/operation</td></tr><tr><td>GET/POST</td><td class='code'>/api/v1/warehouses</td></tr><tr><td>POST</td><td class='code'>/api/v1/transfers</td></tr><tr><td>GET</td><td class='code'>/api/v1/availability/{sku}</td></tr><tr><td>GET/POST</td><td class='code'>/api/v1/customers</td></tr><tr><td>GET/PATCH</td><td class='code'>/api/v1/customers/{code}</td></tr><tr><td>GET</td><td class='code'>/api/v1/customers/{code}/orders</td></tr><tr><td>GET/POST</td><td class='code'>/api/v1/suppliers</td></tr><tr><td>GET/PATCH</td><td class='code'>/api/v1/suppliers/{code}</td></tr><tr><td>GET/POST</td><td class='code'>/api/v1/purchases</td></tr><tr><td>GET/PATCH</td><td class='code'>/api/v1/purchases/{order_no}</td></tr><tr><td>POST</td><td class='code'>/api/v1/purchases/{order_no}/receive</td></tr><tr><td>POST</td><td class='code'>/api/v1/purchases/{order_no}/cancel</td></tr><tr><td>GET/POST</td><td class='code'>/api/v1/sales</td></tr><tr><td>GET/PATCH</td><td class='code'>/api/v1/sales/{order_no}</td></tr><tr><td>POST</td><td class='code'>/api/v1/sales/{order_no}/reserve</td></tr><tr><td>POST</td><td class='code'>/api/v1/sales/{order_no}/release</td></tr><tr><td>POST</td><td class='code'>/api/v1/sales/{order_no}/processing</td></tr><tr><td>POST</td><td class='code'>/api/v1/sales/{order_no}/ship</td></tr><tr><td>POST</td><td class='code'>/api/v1/sales/{order_no}/complete</td></tr><tr><td>POST</td><td class='code'>/api/v1/sales/{order_no}/cancel</td></tr><tr><td>GET</td><td class='code'>/api/v1/audit</td></tr></tbody></table></section>"""
    return layout("REST API", body)


async def media_code(request: Request) -> Response:
    denied = login_redirect(request)
    if denied: return denied
    sku = request.path_params['sku']
    kind = request.path_params['kind']
    try:
        item = product_dict(products.get_product(sku))
        maker = {'qr': make_qr_png, 'barcode': make_barcode_png, 'label': make_label_png}.get(kind)
        if maker is None: return Response(status_code=404)
        return Response(maker(item), media_type='image/png', headers={'Content-Disposition':f'inline; filename="{item["sku"]}-{kind}.png"'})
    except Exception as exc:
        return HTMLResponse(esc(exc), status_code=404)


async def api_health(request: Request) -> Response:
    return JSONResponse({"status":"ok","service":"productflow-web","database":str(settings.database_path.name)})


def api_guard(request: Request) -> Response | None:
    return None if api_ok(request) else api_unauthorized()


async def json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise ValueError("Body должен быть JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body должен быть объектом")
    return data


def api_success(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def api_error(exc: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status)


async def api_dashboard(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:return api_success(commerce.dashboard(days=int(request.query_params.get('days','30'))))
    except Exception as exc:return api_error(exc)


async def api_products(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    if request.method=='GET':
        rows=products.search_products(query=request.query_params.get('q',''),active_only=request.query_params.get('active','1')!='0',limit=int(request.query_params.get('limit','100')))
        return api_success([product_dict(x) for x in rows])
    try:
        d=await json_body(request)
        item=products.create_product(sku=str(d.get('sku','')),name=str(d.get('name','')),category=str(d.get('category','Без категории')),price=d.get('price',0),initial_stock=int(d.get('initial_stock',0)),min_stock=int(d.get('min_stock',0)),description=str(d.get('description','')),purchase_price=d.get('purchase_price',0),supplier=str(d.get('supplier','')),barcode=str(d.get('barcode','')),unit=str(d.get('unit','шт.')))
        out=product_dict(item);record_api(request,'product.create',success=True,details=d,entity_id=out['sku']);return api_success(out,201)
    except Exception as exc:record_api(request,'product.create',success=False,details={'error':str(exc)});return api_error(exc)


async def api_product_detail(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    sku=request.path_params['sku']
    if request.method=='GET':
        try:return api_success(product_dict(products.get_product(sku)))
        except Exception as exc:return api_error(exc,404)
    try:
        d=await json_body(request)
        allowed={'name','category','price','purchase_price','min_stock','description','supplier','barcode','unit','is_active'}
        kwargs={k:v for k,v in d.items() if k in allowed}
        item=products.update_product(sku=sku,**kwargs);out=product_dict(item);record_api(request,'product.update',success=True,details=d,entity_id=sku);return api_success(out)
    except Exception as exc:record_api(request,'product.update',success=False,details={'error':str(exc)},entity_id=sku);return api_error(exc)


async def api_stock_operation(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:
        d=await json_body(request)
        item=products.stock_operation(sku=str(d.get('sku','')),operation=str(d.get('operation','')),quantity=int(d.get('quantity',0)),reason=str(d.get('reason','')),document_ref=str(d.get('document_ref','')),comment=str(d.get('comment','')))
        out=product_dict(item);record_api(request,'stock.operation',success=True,details=d,entity_id=out['sku']);return api_success(out)
    except Exception as exc:record_api(request,'stock.operation',success=False,details={'error':str(exc)});return api_error(exc)


async def api_warehouses(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    if request.method=='GET':return api_success(warehouses.list_warehouses(active_only=request.query_params.get('active','1')!='0',limit=int(request.query_params.get('limit','100'))))
    try:
        d=await json_body(request);item=warehouses.create_warehouse(code=str(d.get('code','')),name=str(d.get('name','')),location=str(d.get('location','')));record_api(request,'warehouse.create',success=True,details=d,entity_id=item['code']);return api_success(item,201)
    except Exception as exc:record_api(request,'warehouse.create',success=False,details={'error':str(exc)});return api_error(exc)


async def api_warehouse_stock(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:return api_success(warehouses.stock(warehouse_code=request.path_params['code'],query=request.query_params.get('q',''),limit=int(request.query_params.get('limit','200'))))
    except Exception as exc:return api_error(exc,404)


async def api_distribution(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:return api_success(warehouses.product_distribution(request.path_params['sku']))
    except Exception as exc:return api_error(exc,404)


async def api_transfer(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:
        d=await json_body(request);result=warehouses.transfer(sku=str(d.get('sku','')),quantity=int(d.get('quantity',0)),from_warehouse=str(d.get('from_warehouse','')),to_warehouse=str(d.get('to_warehouse','')),reason=str(d.get('reason','API transfer')),document_ref=str(d.get('document_ref','')),actor_user_id=request_client(request));record_api(request,'warehouse.transfer',success=True,details=d,entity_id=result['sku']);return api_success(result)
    except Exception as exc:record_api(request,'warehouse.transfer',success=False,details={'error':str(exc)});return api_error(exc)


async def api_customers(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    if request.method=='GET':
        return api_success(customers.list_customers(query=request.query_params.get('q',''),active_only=request.query_params.get('active','1')!='0',limit=int(request.query_params.get('limit','100'))))
    try:
        d=await json_body(request)
        item=customers.create_customer(code=str(d.get('code','')),name=str(d.get('name','')),contact_name=str(d.get('contact_name','')),phone=str(d.get('phone','')),email=str(d.get('email','')),address=str(d.get('address','')),comment=str(d.get('comment','')))
        record_api(request,'customer.create',success=True,details=d,entity_id=item['code']);return api_success(item,201)
    except Exception as exc:record_api(request,'customer.create',success=False,details={'error':str(exc)});return api_error(exc)


async def api_customer_detail(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    code=request.path_params['code']
    if request.method=='GET':
        try:return api_success(customers.get_customer(code))
        except Exception as exc:return api_error(exc,404)
    try:
        d=await json_body(request)
        allowed={'name','contact_name','phone','email','address','comment','is_active'}
        item=customers.update_customer(code=code,**{k:v for k,v in d.items() if k in allowed})
        record_api(request,'customer.update',success=True,details=d,entity_id=code);return api_success(item)
    except Exception as exc:record_api(request,'customer.update',success=False,details={'error':str(exc)},entity_id=code);return api_error(exc)


async def api_customer_orders(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:return api_success(customers.customer_orders(request.path_params['code'],limit=int(request.query_params.get('limit','100'))))
    except Exception as exc:return api_error(exc,404)


async def api_availability(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    try:return api_success(workflow.availability(request.path_params['sku']))
    except Exception as exc:return api_error(exc,404)


async def api_sale_reserve(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=workflow.reserve(no);record_api(request,'sale.reserve',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.reserve',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_sale_release(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=workflow.release(no);record_api(request,'sale.release_reserve',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.release_reserve',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_sale_processing(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=workflow.start_processing(no);record_api(request,'sale.processing',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.processing',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_sale_ship(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        d=await json_body(request)
        items=d.get('items')
        item=workflow.ship(no,items=list(items) if items is not None else None)
        record_api(request,'sale.ship',success=True,details=d,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.ship',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_suppliers(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    if request.method=='GET':return api_success(commerce.list_suppliers(active_only=request.query_params.get('active','1')!='0',limit=int(request.query_params.get('limit','100'))))
    try:
        d=await json_body(request);item=commerce.create_supplier(code=str(d.get('code','')),name=str(d.get('name','')),contact_name=str(d.get('contact_name','')),phone=str(d.get('phone','')),email=str(d.get('email','')),comment=str(d.get('comment','')));record_api(request,'supplier.create',success=True,details=d,entity_id=item['code']);return api_success(item,201)
    except Exception as exc:record_api(request,'supplier.create',success=False,details={'error':str(exc)});return api_error(exc)


async def api_supplier_detail(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    code=request.path_params['code']
    if request.method=='GET':
        try:return api_success(commerce.get_supplier(code))
        except Exception as exc:return api_error(exc,404)
    try:
        d=await json_body(request)
        allowed={'name','contact_name','phone','email','comment','is_active'}
        item=commerce.update_supplier(code=code,**{k:v for k,v in d.items() if k in allowed})
        record_api(request,'supplier.update',success=True,details=d,entity_id=code);return api_success(item)
    except Exception as exc:record_api(request,'supplier.update',success=False,details={'error':str(exc)},entity_id=code);return api_error(exc)


async def api_purchases(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    if request.method=='GET':return api_success(commerce.list_purchase_orders(status=request.query_params.get('status') or None,limit=int(request.query_params.get('limit','100'))))
    try:
        d=await json_body(request);item=commerce.create_purchase_order(order_no=str(d.get('order_no','')),supplier_code=str(d.get('supplier_code','')),items=list(d.get('items') or []),comment=str(d.get('comment','')));record_api(request,'purchase.create',success=True,details=d,entity_id=item['order_no']);return api_success(item,201)
    except Exception as exc:record_api(request,'purchase.create',success=False,details={'error':str(exc)});return api_error(exc)


async def api_purchase_detail(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    if request.method=='GET':
        try:return api_success(commerce.get_purchase_order(no))
        except Exception as exc:return api_error(exc,404)
    try:
        d=await json_body(request)
        current=commerce.get_purchase_order(no)
        items=d.get('items')
        if items is None:
            items=[{'sku':x['sku'],'quantity':x['quantity'],'purchase_price':x['purchase_price']} for x in current['items']]
        item=commerce.update_purchase_order(order_no=no,supplier_code=str(d.get('supplier_code',current['supplier_code'])),items=list(items),comment=str(d.get('comment',current['comment'])));record_api(request,'purchase.update',success=True,details=d,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'purchase.update',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_purchase_receive(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=commerce.receive_purchase_order(no);record_api(request,'purchase.receive',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'purchase.receive',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_purchase_cancel(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=commerce.cancel_purchase_order(no);record_api(request,'purchase.cancel',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'purchase.cancel',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_sales(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    if request.method=='GET':return api_success(commerce.list_sales_orders(status=request.query_params.get('status') or None,limit=int(request.query_params.get('limit','100'))))
    try:
        d=await json_body(request);item=commerce.create_sales_order(order_no=str(d.get('order_no','')),customer_name=str(d.get('customer_name','')),items=list(d.get('items') or []),comment=str(d.get('comment','')),customer_code=str(d.get('customer_code','')) or None);record_api(request,'sale.create',success=True,details=d,entity_id=item['order_no']);return api_success(item,201)
    except Exception as exc:record_api(request,'sale.create',success=False,details={'error':str(exc)});return api_error(exc)


async def api_sale_detail(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    if request.method=='GET':
        try:return api_success(commerce.get_sales_order(no))
        except Exception as exc:return api_error(exc,404)
    try:
        d=await json_body(request)
        current=commerce.get_sales_order(no)
        items=d.get('items')
        if items is None:
            items=[{'sku':x['sku'],'quantity':x['quantity'],'unit_price':x['unit_price']} for x in current['items']]
        item=commerce.update_sales_order(order_no=no,customer_name=str(d.get('customer_name',current['customer_name'])),items=list(items),comment=str(d.get('comment',current['comment'])),customer_code=str(d.get('customer_code',current.get('customer_code') or '')) or None);record_api(request,'sale.update',success=True,details=d,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.update',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_sale_complete(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=commerce.complete_sales_order(no);record_api(request,'sale.complete',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.complete',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_sale_cancel(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    no=request.path_params['order_no']
    try:
        item=commerce.cancel_sales_order(no);record_api(request,'sale.cancel',success=True,entity_id=no);return api_success(item)
    except Exception as exc:record_api(request,'sale.cancel',success=False,details={'error':str(exc)},entity_id=no);return api_error(exc)


async def api_audit(request: Request) -> Response:
    denied=api_guard(request)
    if denied:return denied
    return api_success(audit.list(actor_user_id=request.query_params.get('actor') or None,action=request.query_params.get('action') or None,limit=int(request.query_params.get('limit','100'))))


routes=[
    Route('/login',login_get,methods=['GET']),Route('/login',login_post,methods=['POST']),Route('/logout',logout),
    Route('/',dashboard_page),Route('/products',products_page),Route('/products/{sku:str}',product_detail_page),Route('/warehouses',warehouses_page),Route('/customers',customers_page),Route('/customers/{code:str}',customer_detail_page),Route('/commerce',commerce_page),Route('/suppliers/{code:str}',supplier_detail_page),Route('/purchases/{order_no:str}',purchase_detail_page),Route('/sales/{order_no:str}',sale_detail_page),Route('/audit',audit_page),Route('/api-info',api_info_page),
    Route('/actions/product/create',product_create_action,methods=['POST']),Route('/actions/product/{sku:str}/update',product_update_action,methods=['POST']),Route('/actions/stock',stock_action,methods=['POST']),
    Route('/actions/warehouse',warehouse_action,methods=['POST']),Route('/actions/transfer',transfer_action,methods=['POST']),
    Route('/actions/customer/create',customer_create_action,methods=['POST']),Route('/actions/customer/{code:str}/update',customer_update_action,methods=['POST']),
    Route('/actions/supplier/create',supplier_create_action,methods=['POST']),Route('/actions/supplier/{code:str}/update',supplier_update_action,methods=['POST']),
    Route('/actions/purchase/create',purchase_create_action,methods=['POST']),Route('/actions/purchase/{order_no:str}/update',purchase_update_action,methods=['POST']),Route('/actions/purchase/{order_no:str}/receive',purchase_receive_action,methods=['POST']),Route('/actions/purchase/{order_no:str}/cancel',purchase_cancel_action,methods=['POST']),
    Route('/actions/sale/create',sale_create_action,methods=['POST']),Route('/actions/sale/{order_no:str}/update',sale_update_action,methods=['POST']),Route('/actions/sale/{order_no:str}/reserve',sale_reserve_action,methods=['POST']),Route('/actions/sale/{order_no:str}/release',sale_release_action,methods=['POST']),Route('/actions/sale/{order_no:str}/processing',sale_processing_action,methods=['POST']),Route('/actions/sale/{order_no:str}/ship',sale_ship_action,methods=['POST']),Route('/actions/sale/{order_no:str}/complete',sale_complete_action,methods=['POST']),Route('/actions/sale/{order_no:str}/cancel',sale_cancel_action,methods=['POST']),
    Route('/media/{kind:str}/{sku:str}',media_code),
    Route('/api/v1/health',api_health),Route('/api/v1/dashboard',api_dashboard),
    Route('/api/v1/products',api_products,methods=['GET','POST']),Route('/api/v1/products/{sku:str}',api_product_detail,methods=['GET','PATCH']),Route('/api/v1/products/{sku:str}/distribution',api_distribution),
    Route('/api/v1/stock/operation',api_stock_operation,methods=['POST']),
    Route('/api/v1/warehouses',api_warehouses,methods=['GET','POST']),Route('/api/v1/warehouses/{code:str}/stock',api_warehouse_stock),Route('/api/v1/transfers',api_transfer,methods=['POST']),
    Route('/api/v1/availability/{sku:str}',api_availability),
    Route('/api/v1/customers',api_customers,methods=['GET','POST']),Route('/api/v1/customers/{code:str}',api_customer_detail,methods=['GET','PATCH']),Route('/api/v1/customers/{code:str}/orders',api_customer_orders),
    Route('/api/v1/suppliers',api_suppliers,methods=['GET','POST']),Route('/api/v1/suppliers/{code:str}',api_supplier_detail,methods=['GET','PATCH']),
    Route('/api/v1/purchases',api_purchases,methods=['GET','POST']),Route('/api/v1/purchases/{order_no:str}',api_purchase_detail,methods=['GET','PATCH']),Route('/api/v1/purchases/{order_no:str}/receive',api_purchase_receive,methods=['POST']),Route('/api/v1/purchases/{order_no:str}/cancel',api_purchase_cancel,methods=['POST']),
    Route('/api/v1/sales',api_sales,methods=['GET','POST']),Route('/api/v1/sales/{order_no:str}',api_sale_detail,methods=['GET','PATCH']),Route('/api/v1/sales/{order_no:str}/reserve',api_sale_reserve,methods=['POST']),Route('/api/v1/sales/{order_no:str}/release',api_sale_release,methods=['POST']),Route('/api/v1/sales/{order_no:str}/processing',api_sale_processing,methods=['POST']),Route('/api/v1/sales/{order_no:str}/ship',api_sale_ship,methods=['POST']),Route('/api/v1/sales/{order_no:str}/complete',api_sale_complete,methods=['POST']),Route('/api/v1/sales/{order_no:str}/cancel',api_sale_cancel,methods=['POST']),Route('/api/v1/audit',api_audit),
]

app=Starlette(debug=False,routes=routes)
