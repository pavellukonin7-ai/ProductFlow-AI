from __future__ import annotations

import io
import json
from typing import Any

import qrcode
from PIL import Image, ImageDraw, ImageFont


# Code 128 symbol patterns 0..106. Each digit is the width (in modules)
# of alternating black/white bars. Symbol 106 is the stop pattern.
_CODE128_PATTERNS = (
    "212222", "222122", "222221", "121223", "121322", "131222",
    "122213", "122312", "132212", "221213", "221312", "231212",
    "112232", "122132", "122231", "113222", "123122", "123221",
    "223211", "221132", "221231", "213212", "223112", "312131",
    "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321",
    "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121",
    "313121", "211331", "231131", "213113", "213311", "213131",
    "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124",
    "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111",
    "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113",
    "114311", "411113", "411311", "113141", "114131", "311141",
    "411131", "211412", "211214", "211232", "2331112",
)


def _code_value(product: dict[str, Any]) -> str:
    return str(product.get("barcode") or product.get("sku") or "").strip()


def make_qr_png(product: dict[str, Any]) -> bytes:
    payload = {
        "type": "productflow.product",
        "sku": product.get("sku"),
        "name": product.get("name"),
        "barcode": product.get("barcode") or None,
    }
    qr = qrcode.QRCode(version=None, box_size=10, border=4)
    qr.add_data(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _code128b_symbols(value: str) -> list[int]:
    # Code Set B supports printable ASCII (32..126), which covers normal
    # product SKUs and numeric barcodes without any native rendering backend.
    if not value:
        raise ValueError("Пустое значение штрихкода")
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
        raise ValueError("Code128 поддерживает здесь только печатные ASCII-символы")

    start_b = 104
    data = [ord(ch) - 32 for ch in value]
    checksum = (start_b + sum(i * code for i, code in enumerate(data, start=1))) % 103
    return [start_b, *data, checksum, 106]


def make_barcode_png(product: dict[str, Any]) -> bytes:
    value = _code_value(product)
    if not value:
        raise ValueError("У товара нет SKU/штрихкода для генерации")

    symbols = _code128b_symbols(value)
    quiet_modules = 10
    module_px = 3
    bar_height = 110
    text_area = 28

    patterns = [_CODE128_PATTERNS[symbol] for symbol in symbols]
    modules = quiet_modules * 2 + sum(sum(int(w) for w in pattern) for pattern in patterns)
    width = modules * module_px
    height = bar_height + text_area

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    x = quiet_modules * module_px

    for pattern in patterns:
        black = True
        for width_modules in pattern:
            segment = int(width_modules) * module_px
            if black:
                draw.rectangle((x, 0, x + segment - 1, bar_height - 1), fill="black")
            x += segment
            black = not black

    font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), value, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = max(0, (width - text_width) // 2)
    draw.text((text_x, bar_height + 5), value, fill="black", font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()



def _text_font(size: int = 24):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_label_png(product: dict[str, Any]) -> bytes:
    """Build one printable product label with QR and Code128."""
    qr = Image.open(io.BytesIO(make_qr_png(product))).convert("RGB")
    barcode = Image.open(io.BytesIO(make_barcode_png(product))).convert("RGB")

    canvas_w, canvas_h = 1000, 620
    image = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(image)

    title_font = _text_font(34)
    text_font = _text_font(25)
    small_font = _text_font(20)

    sku = str(product.get("sku") or "")
    name = str(product.get("name") or sku)
    price = float(product.get("price") or 0)
    unit = str(product.get("unit") or "шт.")
    barcode_value = _code_value(product)

    draw.rounded_rectangle((8, 8, canvas_w - 8, canvas_h - 8), radius=18, outline="black", width=3)
    draw.text((38, 32), name[:42], fill="black", font=title_font)
    draw.text((38, 86), f"SKU: {sku}", fill="black", font=text_font)
    draw.text((38, 126), f"Цена: {price:.2f} ₽ / {unit}", fill="black", font=text_font)

    qr.thumbnail((330, 330), Image.Resampling.LANCZOS)
    image.paste(qr, (38, 190))
    draw.text((80, 530), "ProductFlow QR", fill="black", font=small_font)

    barcode.thumbnail((560, 235), Image.Resampling.LANCZOS)
    bx = 405 + max(0, (550 - barcode.width) // 2)
    image.paste(barcode, (bx, 225))
    draw.text((430, 485), f"Code128: {barcode_value}", fill="black", font=small_font)
    draw.text((430, 530), "ProductFlow AI", fill="black", font=text_font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
