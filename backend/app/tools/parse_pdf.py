from __future__ import annotations

import io

from pypdf import PdfReader


def parse_pdf_bytes(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload))
    chunks: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        stripped = text.strip()
        if stripped:
            chunks.append(stripped)
    combined = "\n\n".join(chunks).strip()
    if not combined:
        raise ValueError("PDF does not contain extractable text.")
    return combined
