"""Volitelna kontrola fotiek cez Claude API (vision) - rezim --use-claude-api.

Pre kazdu fotku (uz otocenu lokalnym pipeline) overi, ci je spravne
orientovana, a precita z nej udaje, ktore lokalny OCR nezvladne:
- stav elektromera (Zaehlerstand, OBIS 1.8.0) zo sedemsegmentoveho LCD,
- Seriennr./Zaehlernr. zo stitku (zaloha za lokalny OCR).

Preco to lokalne nejde: sedemsegmentove cislice bezny Tesseract neprecita
a nalepky nalepene hore nohami (bezna vec na elektromeroch) okla mu aj
detekciu orientacie - presne to sa stalo na realnych fotkach z merania.
"""

from __future__ import annotations

import base64
import io
import os
import re
import threading

from PIL import Image

DEFAULT_MODEL = "claude-haiku-4-5"  # najlacnejsi model s vision - overene na realnych fotkach, presne ako Sonnet 5
MAX_IMAGE_SIDE = 1568  # odporucane maximum pre Claude vision, staci aj na LCD

# USD za 1 milion tokenov (vstup, vystup). Iba pre modely, ktore tento program
# realne pouziva - ak sa DEFAULT_MODEL zmeni na nieco tu nechybajuce,
# odhad ceny sa jednoducho vynecha (None) namiesto vymyslania cisla.
PRICING_PER_MILLION_TOKENS = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-fable-5": {"input": 10.00, "output": 50.00},
}


def _estimate_cost_usd(model: str, usage) -> float | None:
    prices = PRICING_PER_MILLION_TOKENS.get(model)
    if not prices or usage is None:
        return None
    return (
        usage.input_tokens * prices["input"] + usage.output_tokens * prices["output"]
    ) / 1_000_000

_PROMPT = """Dostal si DVA obrazky: A a B. Je to TA ISTA fotka z elektro merania (rozvadzac, meraci pristroj, elektromer alebo stitok), obrazok B je otoceny o 180 stupnov oproti A. Prave jeden z nich je spravne orientovany. Text na pristrojoch je v nemcine.

Odpovedz PRESNE v tomto formate (4 riadky, nic ine):
SPRAVNY: <A alebo B>
STAV: <stav elektromera v kWh, alebo NIE>
SERIENNR: <hodnota, alebo NIE>
ZAEHLERNR: <hodnota, alebo NIE>

Pravidla:
- NAJDOLEZITEJSI udaj je STAV elektromera z LCD displeja - ak je na fotke displej, vsetko posudzuj podla neho.
- Samolepky/nalepky (napr. okruhla zlta "Nachster Pruftermin") UPLNE IGNORUJ - byvaju nalepene hore nohami a klamu.
- SPRAVNY: na ktorom obrazku su displeje (LCD cislice, kod 1.8.0, napis kWh) a potlac pristrojov vzpriamene a citatelne.
- STAV: ak je na fotke elektromer s LCD displejom so stavom v kWh (pri hodnote byva kod 1.8.0 a jednotka kWh), precitaj HODNOTU zo SPRAVNEHO obrazka, vratane desatinnej bodky, napr. "02854.4". Cislice su sedemsegmentove. Ak taky displej na fotke nie je alebo sa neda precitat, napis NIE.
- SERIENNR / ZAEHLERNR: ak je na fotke stitok s "Seriennr.:" alebo "Zaehlernr.:" (Zahler-Nr.), uved hodnoty zo spravneho obrazka. Inak NIE."""


def _encode_image(image: Image.Image) -> str:
    scaled = image.copy()
    scaled.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    scaled.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def _parse_reply(text: str) -> dict:
    result = {"rotate": 0, "reading": None, "Seriennr": None, "Zaehlernr": None, "cost_usd": None}
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = label.strip().upper()
        value = value.strip()
        if not value or value.upper() == "NIE":
            continue
        if label == "SPRAVNY":
            if value.strip().upper().startswith("B"):
                result["rotate"] = 180
        elif label == "STAV":
            result["reading"] = value
        elif label == "SERIENNR":
            result["Seriennr"] = value
        elif label == "ZAEHLERNR":
            result["Zaehlernr"] = value
    return result


_client_lock = threading.Lock()
_client_cache: dict[str, object] = {}


def _get_client(api_key: str):
    """Jeden zdielany klient na kluc - je thread-safe, takze ho mozu naraz
    pouzivat vsetky subezne fotky. max_retries=5: pri docasnom odmietnuti
    (rate limit 429 / preplnenie 529) SDK pocka a skusi znova samo - taketo
    odmietnute poziadavky sa NEUCTUJU."""
    import anthropic

    with _client_lock:
        client = _client_cache.get(api_key)
        if client is None:
            client = anthropic.Anthropic(api_key=api_key, max_retries=5)
            _client_cache[api_key] = client
        return client


def analyze_photo(image: Image.Image, model: str = DEFAULT_MODEL) -> dict:
    """Posle fotku na Claude API v dvoch orientaciach (A = ako je, B = +180
    stupnov) - porovnanie vedla seba je spolahlivejsie nez posudenie jednej
    fotky, najma pri elektromeroch s naopak nalepenymi nalepkami. Vrati dict:
    {"rotate": 0/180, "reading": str|None, "Seriennr": str|None,
     "Zaehlernr": str|None, "cost_usd": float|None}. Rotacia je relativna
    k dodanej fotke. Je thread-safe - vola sa subezne pre viac fotiek naraz.
    Vynimky necha prejst - volajuci ich osetri (API rezim je volitelny)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Premenna prostredia ANTHROPIC_API_KEY nie je nastavena.")

    def image_block(img):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": _encode_image(img),
            },
        }

    client = _get_client(api_key)
    message = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "OBRAZOK A:"},
                image_block(image),
                {"type": "text", "text": "OBRAZOK B (otoceny o 180):"},
                image_block(image.rotate(180)),
                {"type": "text", "text": _PROMPT},
            ],
        }],
    )
    reply = "".join(block.text for block in message.content if block.type == "text")
    result = _parse_reply(reply)
    result["cost_usd"] = _estimate_cost_usd(model, message.usage)
    return result
