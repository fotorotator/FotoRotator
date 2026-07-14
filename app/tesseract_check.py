"""Overenie, ci je nainstalovany Tesseract OCR a nemecky jazykovy balik."""

import os
import shutil

import pytesseract

INSTALL_INSTRUCTIONS = """
Tesseract OCR nie je najdeny (alebo nie je v PATH).

Ako ho doinstalovat na Windows:
  1. Stiahni instalator UB-Mannheim verzie Tesseractu:
     https://github.com/UB-Mannheim/tesseract/wiki
  2. Spusti instalator. Pri vybere komponentov ("Additional language data")
     zaskrtni aj "German" (deu) - text na stitku merania je v nemcine.
  3. Po instalacii pridaj priecinok Tesseractu (zvycajne
     C:\\Program Files\\Tesseract-OCR) do premennej prostredia PATH.
  4. Over instalaciu v prikazovom riadku prikazom: tesseract --version

Bez Tesseractu program nevie zistit spravny smer otocenia fotiek ani precitat
cisla zo stitku - fotky sa iba oriented podla EXIF (ak ho maju).
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


def ensure_tesseract() -> bool:
    """Over, ze je Tesseract dostupny a vie jazyk 'deu'. Ak nie, vypise navod
    a vrati False - volajuci sa rozhodne, ci pokracovat bez OCR."""
    cmd = find_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        version = pytesseract.get_tesseract_version()
    except Exception:
        print(INSTALL_INSTRUCTIONS)
        return False

    try:
        langs = pytesseract.get_languages(config="")
    except Exception:
        langs = []

    if "deu" not in langs:
        print(
            f"Tesseract je nainstalovany (verzia {version}), ale chyba nemecky "
            "jazykovy balik 'deu'.\n"
            "Doinstaluj ho cez instalator UB-Mannheim (zaskrtni 'German' pri "
            "vybere jazykov pri instalacii), prípadne stiahni deu.traineddata "
            "z https://github.com/tesseract-ocr/tessdata a skopiruj ho do "
            "priecinka 'tessdata' v instalacii Tesseractu."
        )
        return False

    return True
