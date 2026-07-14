"""Vytiahnutie Seriennr. a Zaehlernr. zo stitku meracieho pristroja (OCR)."""

from __future__ import annotations

import base64
import io
import os
import re

import pytesseract
from PIL import Image

IDS = ("Seriennr", "Zaehlernr")

# Tolerantne aj na drobne OCR chyby: "Serien-Nr", "Ser.Nr", "SerNr",
# "Zaehler-Nr", "Zähler-Nr", "Zahlernr" a pod.
_SERIEN_LABEL = re.compile(r"Serien\s*-?\s*Nr\.?|Ser\.?\s*-?\s*Nr\.?", re.IGNORECASE)
_ZAEHLER_LABEL = re.compile(r"Z(?:ähler|ahler|aehler)\s*-?\s*Nr\.?", re.IGNORECASE)
# Hodnota moze obsahovat viac slov oddelenych JEDNOU medzerou (napr. cislo
# elektromera "1 EBZ03 0003 2874"). Dve a viac medzier znamena iny stlpec
# stitku - tam hodnota konci. OCR sa pusta s preserve_interword_spaces=1,
# aby velke medzery medzi stlpcami ostali zachovane.
_VALUE = re.compile(r"[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/]*(?: [A-Za-z0-9][A-Za-z0-9\-/]*)*)")


def _value_after(line: str, label_match: re.Match) -> str | None:
    remainder = line[label_match.end():label_match.end() + 60]
    value_match = _VALUE.match(remainder.lstrip())
    return value_match.group(1) if value_match else None


def extract_ids_from_text(text: str) -> dict:
    result = {key: None for key in IDS}
    for line in text.splitlines():
        if result["Seriennr"] is None:
            m = _SERIEN_LABEL.search(line)
            if m:
                result["Seriennr"] = _value_after(line, m)
        if result["Zaehlernr"] is None:
            m = _ZAEHLER_LABEL.search(line)
            if m:
                result["Zaehlernr"] = _value_after(line, m)
    return result


def extract_ids_via_tesseract(image: Image.Image) -> dict:
    from .rotate import ocr_friendly

    text = pytesseract.image_to_string(
        ocr_friendly(image), lang="deu+eng", config="-c preserve_interword_spaces=1"
    )
    return extract_ids_from_text(text)


def extract_ids_via_claude(image: Image.Image, model: str = "claude-sonnet-5") -> dict:
    """Zalozny sposob citania stitku cez Claude API (vision) - pouziva sa iba
    na tuto jednu fotku, nie na cele davky. Vyzaduje ANTHROPIC_API_KEY."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Premenna prostredia ANTHROPIC_API_KEY nie je nastavena.")

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=90)
    image_b64 = base64.standard_b64encode(buffer.getvalue()).decode("ascii")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
                },
                {
                    "type": "text",
                    "text": (
                        "Na fotke je stitok merac. pristroja v nemcine. Najdi hodnoty za "
                        "'Seriennr.:' a 'Zaehlernr.:' (Zähler-Nr.). Odpovedz IBA v tvare:\n"
                        "Seriennr: <hodnota alebo NENAJDENE>\n"
                        "Zaehlernr: <hodnota alebo NENAJDENE>"
                    ),
                },
            ],
        }],
    )
    reply_text = "".join(block.text for block in message.content if block.type == "text")

    result = {key: None for key in IDS}
    for line in reply_text.splitlines():
        lowered = line.lower()
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        value = value.strip()
        if value.upper() == "NENAJDENE":
            value = None
        if lowered.startswith("seriennr"):
            result["Seriennr"] = value
        elif lowered.startswith("zaehlernr") or lowered.startswith("zählernr"):
            result["Zaehlernr"] = value
    return result
