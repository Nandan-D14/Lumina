from __future__ import annotations

import io

import pytest
from reportlab.pdfgen import canvas

from backend.app.tools.parse_csv_json import parse_csv_bytes, parse_json_bytes
from backend.app.tools.parse_pdf import parse_pdf_bytes


def make_pdf_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buffer.getvalue()


def test_parse_csv_bytes() -> None:
    text, tables = parse_csv_bytes(b"quarter,revenue\nQ1,45\nQ2,89\n", "revenue.csv")
    assert "quarter" in text
    assert len(tables) == 1
    assert tables[0].columns == ["quarter", "revenue"]
    assert tables[0].rows[1][1] == 89


def test_parse_json_bytes() -> None:
    payload = b'[{"quarter":"Q1","revenue":45},{"quarter":"Q2","revenue":89}]'
    text, tables = parse_json_bytes(payload, "revenue.json")
    assert '"quarter"' in text
    assert len(tables) == 1
    assert "revenue" in tables[0].columns


def test_parse_pdf_bytes() -> None:
    payload = make_pdf_bytes("Revenue summary Q1 45 Q2 89")
    text = parse_pdf_bytes(payload)
    assert "Revenue summary" in text


def test_parse_json_bytes_raises_on_invalid_json() -> None:
    with pytest.raises(ValueError):
        parse_json_bytes(b"{not json}", "broken.json")


def test_parse_pdf_bytes_raises_when_no_text() -> None:
    payload = make_pdf_bytes(" ")
    with pytest.raises(ValueError):
        parse_pdf_bytes(payload)
