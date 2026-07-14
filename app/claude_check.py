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

from PIL import Image

DEFAULT_MODEL = "claude-sonnet-5"
MAX_IMAGE_SIDE = 1568  # odporucane maximum pre Claude vision, staci aj na LCD

_PROMPT = """Dostal si DVA obrazky: A a B. Je to TA ISTA fotka z elektro merania (rozvadzac, meraci pristroj, elektromer alebo stitok), obrazok B je otoceny o 180 stupnov oproti A. Prave jeden z nich je spravne orientovany. Text na pristrojoch je v nemcine.

Odpovedz PRESNE v tomto formate (4 riadky, nic ine):
SPRAVNY: <A alebo B>
STAV: <stav elektromera v kWh, alebo NIE>
SERIENNR: <hodnota, alebo NIE>
ZAEHLERNR: <hodnota, alebo NIE>

Pravidla:
- SPRAVNY: na ktorom obrazku su pristroje, ich displeje a POTLAC PRISTROJOV vzpriamene a citatelne. POZOR: samolepky/nalepky (napr. okruhla zlta "Nachster Pruftermin") byvaju na pristrojoch nalepene hore nohami - NERIAD sa nalepkami, riad sa displejmi (LCD cislice, kod 1.8.0, napis kWh) a potlacou pristrojov.
- STAV: ak je na fotke elektromer s LCD displejom so stavom v kWh (pri hodnote byva kod 1.8.0 a jednotka kWh), precitaj HODNOTU zo SPRAVNEHO obrazka, vratane desatinnej bodky, napr. "02854.4". Cislice su sedemsegmentove. Ak taky displej na fotke nie je alebo sa neda precitat, napis NIE.
- SERIENNR / ZAEHLERNR: ak je na fotke stitok s "Seriennr.:" alebo "Zaehlernr.:" (Zahler-Nr.), uved hodnoty zo spravneho obrazka. Inak NIE."""


def _encode_image(image: Image.Image) -> str:
    scaled = image.copy()
    scaled.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    scaled.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def _parse_reply(text: str) -> dict:
    result = {"rotate": 0, "reading": None, "Seriennr": None, "Zaehlernr": None}
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


def analyze_photo(image: Image.Image, model: str = DEFAULT_MODEL) -> dict:
    """Posle fotku na Claude API v dvoch orientaciach (A = ako je, B = +180
    stupnov) - porovnanie vedla seba je spolahlivejsie nez posudenie jednej
    fotky, najma pri elektromeroch s naopak nalepenymi nalepkami. Vrati dict:
    {"rotate": 0/180, "reading": str|None, "Seriennr": str|None,
     "Zaehlernr": str|None}. Rotacia je relativna k dodanej fotke.
    Vynimky necha prejst - volajuci ich osetri (API rezim je volitelny)."""
    import anthropic

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

    client = anthropic.Anthropic(api_key=api_key)
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
    return _parse_reply(reply)
