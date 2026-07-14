"""Overenie, ci je nainstalovany Tesseract OCR a nemecky jazykovy balik."""

import os
import shutil

import pytesseract

INSTALL_INSTRUCTIONS = """
Tesseract OCR nie je najdeny (alebo nie je v PATH).

Ako ho doinstalovat rucne na Windows (ak nechces automaticku instalaciu):
  1. Stiahni instalator UB-Mannheim verzie Tesseractu:
     https://github.com/UB-Mannheim/tesseract/wiki
  2. Spusti instalator. Pri vybere komponentov ("Additional language data")
     zaskrtni aj "German" (deu) - text na stitku merania je v nemcine.
  3. Po instalacii pridaj priecinok Tesseractu (zvycajne
     C:\\Program Files\\Tesseract-OCR) do premennej prostredia PATH.
  4. Over instalaciu v prikazovom riadku prikazom: tesseract --version

Bez Tesseractu program nevie zistit spravny smer otocenia fotiek ani precitat
cisla zo stitku - fotky sa otocia iba podla EXIF (ak ho maju).
"""

NO_DEU_INSTRUCTIONS = """
Tesseract je nainstalovany, ale chyba nemecky jazykovy balik 'deu'.
Rucne ho doinstalujes cez instalator UB-Mannheim (zaskrtni 'German' pri vybere
jazykov), pripadne stiahni deu.traineddata z
https://github.com/tesseract-ocr/tessdata_fast a skopiruj ho do priecinka
'tessdata' v instalacii Tesseractu.
"""

DEFAULT_WINDOWS_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def find_tesseract_cmd():
    for candidate in ("tesseract.exe", "tesseract"):
        path = shutil.which(candidate)
        if path:
            return path
    if os.path.exists(DEFAULT_WINDOWS_PATH):
        return DEFAULT_WINDOWS_PATH
    return None


def diagnose() -> str:
    """Vrati stav OCR: 'ok' | 'missing' (Tesseract chyba) | 'no_deu'
    (Tesseract je, ale chyba nemecky jazykovy balik)."""
    cmd = find_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return "missing"

    try:
        langs = pytesseract.get_languages(config="")
    except Exception:
        langs = []

    return "ok" if "deu" in langs else "no_deu"


def ensure_tesseract() -> bool:
    """Over, ze je Tesseract dostupny a vie jazyk 'deu'. Ak nie, vypise navod
    a vrati False - volajuci sa rozhodne, ci pokracovat bez OCR."""
    status = diagnose()
    if status == "missing":
        print(INSTALL_INSTRUCTIONS)
        return False
    if status == "no_deu":
        print(NO_DEU_INSTRUCTIONS)
        return False
    return True
