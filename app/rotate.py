"""Zoradenie fotiek podla casu vytvorenia a ich otocenie do landscape orientacie."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytesseract
from PIL import ExifTags, Image, ImageOps
from pytesseract import Output

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

# HEIC/HEIF sa uklada ako .jpg - Pillow/pillow-heif nemaju vzdy spolahlivy
# HEIC encoder, JPEG vieme ulozit vzdy.
_CONVERT_TO_JPEG = {".heic", ".heif"}

_DATETIME_ORIGINAL_TAG = next(
    (tag for tag, name in ExifTags.TAGS.items() if name == "DateTimeOriginal"), 36867
)
_EXIF_IFD_POINTER = 0x8769


def register_heif_support():
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError:
        pass


def list_photos(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def get_capture_time(path: Path) -> tuple[datetime, bool]:
    """Vrati (cas, pouzil_sa_exif). Skusi EXIF DateTimeOriginal, inak pouzije
    cas poslednej zmeny suboru."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get(_DATETIME_ORIGINAL_TAG)
            if not raw:
                try:
                    exif_ifd = exif.get_ifd(_EXIF_IFD_POINTER)
                    raw = exif_ifd.get(_DATETIME_ORIGINAL_TAG)
                except Exception:
                    raw = None
            if raw:
                return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S"), True
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime), False


def sort_photos(paths: list[Path]) -> list[tuple[Path, datetime, bool]]:
    """Zoradi fotky podla casu vytvorenia. Stabilne triedenie + abecedne
    zoradeny vstup (list_photos) zarucuju rovnaky vysledok pri opakovanom
    spusteni, aj ked sa viacero fotiek zhoduje v case na sekundu presne."""
    items = [(p, *get_capture_time(p)) for p in paths]
    items.sort(key=lambda item: item[1])
    return items


def _score_rotation(image: Image.Image, clockwise_angle: int) -> float:
    rotated = image if clockwise_angle == 0 else image.rotate(-clockwise_angle, expand=True)
    try:
        data = pytesseract.image_to_data(rotated, lang="deu+eng", output_type=Output.DICT)
    except Exception:
        return 0.0
    confidences = [int(c) for c in data.get("conf", []) if str(c) not in ("-1",)]
    confidences = [c for c in confidences if c > 0]
    if not confidences:
        return 0.0
    return sum(confidences) / len(confidences)


def determine_extra_rotation(image: Image.Image) -> tuple[int, bool]:
    """Fotka je po EXIF transpozicii na vysku (treba ju otocit do landscape).
    Vyskusa otocenie o 90 a 270 stupnov v smere hodinovych ruciciek a cez OCR
    spolahlivost textu vyberie tu spravnu. Vrati (uhol, neisté)."""
    score_90 = _score_rotation(image, 90)
    score_270 = _score_rotation(image, 270)

    if score_90 == 0.0 and score_270 == 0.0:
        return 270, True  # ziaden citatelny text - neisty odhad, treba skontrolovat rucne

    return (90, False) if score_90 >= score_270 else (270, False)


@dataclass
class ProcessedPhoto:
    image: Image.Image
    rotation_applied: int
    rotation_uncertain: bool
    used_ocr: bool


def process_photo(path: Path, use_ocr: bool) -> ProcessedPhoto:
    """Nacita fotku, aplikuje EXIF orientaciu a - ak treba - doplni otocenie
    do landscape (cez OCR, ak je k dispozicii)."""
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)

    if image.width >= image.height:
        return ProcessedPhoto(image, 0, False, False)

    if not use_ocr:
        return ProcessedPhoto(image, 0, True, False)

    angle, uncertain = determine_extra_rotation(image)
    rotated = image.rotate(-angle, expand=True)
    return ProcessedPhoto(rotated, angle, uncertain, True)


def output_name_for(index: int, source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix in _CONVERT_TO_JPEG:
        return f"{index:03d}_{source_path.stem}.jpg"
    return f"{index:03d}_{source_path.name}"


def save_output(image: Image.Image, source_path: Path, dest_path: Path):
    if source_path.suffix.lower() in _CONVERT_TO_JPEG:
        image.convert("RGB").save(dest_path, format="JPEG", quality=95)
    else:
        image.save(dest_path)
