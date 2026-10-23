from __future__ import annotations

import html
import re


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}.*\|\s*$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`\n]+)`")


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _inline_format(value: str) -> str:
    escaped = html.escape(value)
    escaped = _BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    return escaped


def _format_table_block(lines: list[str]) -> str:
    rows = [_split_table_row(line) for line in lines if not _TABLE_SEPARATOR.match(line)]
    if not rows:
        return ""
    headers = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    if not body:
        return " • ".join(_inline_format(cell) for cell in headers if cell)

    rendered: list[str] = []
    for row in body:
        pairs = []
        for idx, value in enumerate(row):
            if not value:
                continue
            key = headers[idx] if idx < len(headers) and headers[idx] else f"Поле {idx + 1}"
            pairs.append(f"<b>{html.escape(key)}:</b> {_inline_format(value)}")
        if pairs:
            rendered.append("• " + " · ".join(pairs))
    return "\n".join(rendered)


def ai_text_to_telegram_html(text: str) -> str:
    """Convert common model Markdown into safe Telegram HTML and readable lists.

    It intentionally supports only a small subset instead of passing arbitrary HTML
    from the model to Telegram.
    """
    source = (text or "").replace("&#x20;", " ").replace("&nbsp;", " ").strip()
    if not source:
        return "Готово."

    lines = source.splitlines()
    output: list[str] = []
    table_buffer: list[str] = []

    def flush_table() -> None:
        nonlocal table_buffer
        if table_buffer:
            rendered = _format_table_block(table_buffer)
            if rendered:
                output.append(rendered)
            table_buffer = []

    for raw in lines:
        line = raw.rstrip()
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            table_buffer.append(line)
            continue
        flush_table()

        escaped = html.escape(line)
        escaped = re.sub(r"^\s*#{1,6}\s*", "", escaped)
        escaped = _BOLD.sub(r"<b>\1</b>", escaped)
        escaped = _CODE.sub(r"<code>\1</code>", escaped)
        escaped = re.sub(r"^\s*[-*]\s+", "• ", escaped)
        output.append(escaped)

    flush_table()
    return "\n".join(output).strip()
