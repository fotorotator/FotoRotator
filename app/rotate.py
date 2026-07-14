"""Zoradenie fotiek podla casu vytvorenia a ich otocenie do landscape orientacie."""

from __future__ import annotations

import io
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


def ocr_friendly(image: Image.Image) -> Image.Image:
    """Kopia fotky pripravena pre OCR. Fotky displejov maju moire vzor (jemna
    mriezka pixelov obrazovky), na ktorom Tesseract uplne zlyhava - text
    nevidi vobec. JPEG kompresia s kvalitou 75 tento vzor vyhladi; overene na
    realnych fotkach z merania (bez toho skore 0, s tym stovky bodov).
    Gaussovske rozmazanie prekvapivo nepomaha - funguje prave JPEG."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=75)
    buffer.seek(0)
    smoothed = Image.open(buffer)
    smoothed.load()
    return smoothed


def _score_rotation(image: Image.Image, clockwise_angle: int) -> int:
    """Sucet spolahlivosti rozpoznanych slov (nad prah). Sucet - nie priemer -
    aby vela citatelneho textu vzdy prebilo par nahodnych 'slov' na fotke
    otocenej zle. Skoruje sa na plnom rozliseni: zmensenie nici drobny/sikmy
    text a skore potom vychadza nulove aj pri spravnej rotacii."""
    rotated = image if clockwise_angle == 0 else image.rotate(-clockwise_angle, expand=True)
    try:
        data = pytesseract.image_to_data(rotated, lang="deu+eng", output_type=Output.DICT)
    except Exception:
        return 0
    total = 0
    for conf, word in zip(data.get("conf", []), data.get("text", [])):
        try:
            c = int(float(conf))
        except (TypeError, ValueError):
            continue
        if c > 40 and word.strip():
            total += c - 40
    return total


def _osd_rotation(image: Image.Image):
    """Tesseract OSD (Orientation and Script Detection) - vrati uhol v smere
    hodinovych ruciciek, o ktory treba fotku otocit, alebo None ak sa neda
    urcit (malo textu)."""
    try:
        osd = pytesseract.image_to_osd(image, output_type=Output.DICT)
        return int(osd.get("rotate", 0)) % 360
    except Exception:
        return None


def detect_rotation(image: Image.Image, candidates: tuple, default: int) -> tuple[int, bool]:
    """Vyberie spravny uhol otocenia z dvoch kandidatov (pre fotku na sirku
    0/180, pre fotku na vysku 90/270). Primarne plati OSD - na realnych
    fotkach z merania (displeje pristrojov, sedemsegmentove cislice) bolo OSD
    spravne v kazdom overenom pripade, zatial co OCR skorovanie sa na
    cifernikoch obcas pomylilo (cislice su citatelne aj hore nohami). OCR
    skorovanie je zaloha, ked OSD zlyha alebo vrati uhol mimo kandidatov
    (napr. malo textu na fotke). Vrati (uhol, neista)."""
    image = ocr_friendly(image)

    osd_angle = _osd_rotation(image)
    if osd_angle in candidates:
        return osd_angle, False

    scores = {angle: _score_rotation(image, angle) for angle in candidates}
    first, second = candidates
    if scores[first] == scores[second]:  # remiza (typicky 0:0 - ziaden text)
        return default, True
    return (first if scores[first] > scores[second] else second), False


@dataclass
class ProcessedPhoto:
    image: Image.Image
    rotation_applied: int
    rotation_uncertain: bool
    used_ocr: bool


def process_photo(path: Path, use_ocr: bool) -> ProcessedPhoto:
    """Nacita fotku, aplikuje EXIF orientaciu a cez OCR overi/doplni otocenie:
    fotka na vysku sa otoci do landscape (90 alebo 270), fotka na sirku sa
    skontroluje, ci nie je hore nohami (0 alebo 180)."""
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)

    is_landscape = image.width >= image.height

    if not use_ocr:
        # Bez OCR sa neda zistit smer - na sirku nechavame (moze byt hore
        # nohami), na vysku oznacime ako neiste.
        return ProcessedPhoto(image, 0, not is_landscape, False)

    candidates = (0, 180) if is_landscape else (90, 270)
    default = 0 if is_landscape else 270
    angle, uncertain = detect_rotation(image, candidates, default)
    rotated = image if angle == 0 else image.rotate(-angle, expand=True)
    return ProcessedPhoto(rotated, angle, uncertain, True)


def output_name_for(index: int, source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix in _CONVERT_TO_JPEG:
        return f"{index:03d}_{source_path.stem}.jpg"
    return f"{index:03d}_{source_path.name}"


def save_output(image: Image.Image, source_path: Path, dest_path: Path):
    if source_path.suffix.lower() in _CONVERT_TO_JPEG:
        image.convert("RGB").save(dest_path, format="JPEG", quality=95)
    elif source_path.suffix.lower() in (".jpg", ".jpeg"):
        image.save(dest_path, quality=95)
    else:
        image.save(dest_path)
