from __future__ import annotations

import csv
import io
import json

from ..schemas.domain import TableData


def _coerce_cell(value: str) -> str | int | float | None:
    cleaned = value.strip()
    if cleaned == "":
        return None
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return cleaned


def parse_csv_bytes(payload: bytes, name: str) -> tuple[str, list[TableData]]:
    text = payload.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV file is empty.")
    columns = [column.strip() or f"column_{idx + 1}" for idx, column in enumerate(rows[0])]
    table_rows = [[_coerce_cell(cell) for cell in row] for row in rows[1:]]
    table = TableData(name=name, columns=columns, rows=table_rows)
    return text, [table]


def parse_json_bytes(payload: bytes, name: str) -> tuple[str, list[TableData]]:
    text = payload.decode("utf-8-sig")
    data = json.loads(text)
    tables: list[TableData] = []

    if isinstance(data, list) and data and all(isinstance(row, dict) for row in data):
        columns = list({key for row in data for key in row.keys()})
        rows = [[row.get(column) for column in columns] for row in data]
        tables.append(TableData(name=name, columns=columns, rows=rows))
    elif isinstance(data, dict):
        columns = ["key", "value"]
        rows = [[key, value if isinstance(value, (str, int, float)) else json.dumps(value)] for key, value in data.items()]
        tables.append(TableData(name=name, columns=columns, rows=rows))

    normalized_text = json.dumps(data, ensure_ascii=False, indent=2)
    return normalized_text, tables
