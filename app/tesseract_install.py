"""Automaticke stiahnutie a nainstalovanie Tesseract OCR + nemeckeho jazyka.

Stiahne aktualny instalator UB-Mannheim (cez GitHub API ich najnovsi release),
spusti ho ticho (/S) a doplni nemecky jazykovy balik deu.traineddata - ten sa
pri tichej instalacii nezaskrtne sam, preto sa stahuje zvlast a kopiruje do
priecinka tessdata. Instalacia ide do Program Files, takze vyskoci UAC okno
(povolenie spravcu) - jedno na cely proces.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

# Instalator pre Windows byva prilozeny k releasom oficialneho tesseract-ocr
# repozitara (stavia ho UB-Mannheim), historicky aj k UB-Mannheim repozitaru —
# nie kazdy release ma instalator, preto sa prehladavaju vsetky a berie sa
# najvyssia najdena verzia.
INSTALLER_SOURCES = (
    "https://api.github.com/repos/tesseract-ocr/tesseract/releases",
    "https://api.github.com/repos/UB-Mannheim/tesseract/releases",
)
_TRUSTED_DOWNLOAD_PREFIXES = (
    "https://github.com/tesseract-ocr/tesseract/",
    "https://github.com/UB-Mannheim/tesseract/",
)
_INSTALLER_ASSET = re.compile(r"tesseract-ocr-w64-setup-([0-9.]+)\.exe$", re.IGNORECASE)

# Zalozna adresa, keby GitHub API nefungovalo (znama stabilna verzia).
FALLBACK_INSTALLER_URL = (
    "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/"
    "tesseract-ocr-w64-setup-5.5.0.20241111.exe"
)

# Nemcina z tessdata_fast - rovnaka sada, aku pouziva instalator UB-Mannheim
# pri interaktivnom vybere "Additional language data".
DEU_TRAINEDDATA_URLS = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/deu.traineddata",
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/master/deu.traineddata",
)

DEFAULT_INSTALL_DIR = Path(r"C:\Program Files\Tesseract-OCR")


def get_latest_installer_url() -> str:
    best_version = None
    best_url = None
    for api_url in INSTALLER_SOURCES:
        try:
            with urllib.request.urlopen(api_url, timeout=10) as response:
                releases = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
        for release in releases:
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                url = asset.get("browser_download_url", "")
                match = _INSTALLER_ASSET.search(name)
                if not match or not url.startswith(_TRUSTED_DOWNLOAD_PREFIXES):
                    continue
                version = tuple(int(p) for p in match.group(1).split(".") if p.isdigit())
                if best_version is None or version > best_version:
                    best_version = version
                    best_url = url
    return best_url or FALLBACK_INSTALLER_URL


def _download(url: str, dest: Path, label: str, log=print):
    log(f"Stahujem {label}...")
    with urllib.request.urlopen(url, timeout=30) as response:
        total = int(response.headers.get("Content-Length", 0)) or None
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
    size_mb = done / (1024 * 1024)
    log(f"  stiahnute {size_mb:.1f} MB")


def _download_deu(dest: Path, log=print):
    last_error = None
    for url in DEU_TRAINEDDATA_URLS:
        try:
            _download(url, dest, "nemecky jazykovy balik (deu)", log)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Nepodarilo sa stiahnut deu.traineddata: {last_error}")


def _run_elevated_bat(bat_path: Path) -> bool:
    """Spusti .bat s pravami spravcu (vyskoci UAC okno) a pocka na dokoncenie.
    Vrati False, ak pouzivatel UAC odmietne."""
    result = subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            f"Start-Process -FilePath '{bat_path}' -Verb RunAs -Wait",
        ],
        capture_output=True,
    )
    return result.returncode == 0


def _tessdata_dir(tesseract_cmd: str | None) -> Path:
    if tesseract_cmd:
        return Path(tesseract_cmd).parent / "tessdata"
    return DEFAULT_INSTALL_DIR / "tessdata"


def install_full(log=print) -> bool:
    """Stiahne a ticho nainstaluje cely Tesseract + doplni nemcinu.
    Vrati True pri uspechu."""
    work_dir = Path(tempfile.mkdtemp(prefix="fotorotator_tesseract_"))
    installer_path = work_dir / "tesseract_setup.exe"
    deu_path = work_dir / "deu.traineddata"

    _download(get_latest_installer_url(), installer_path, "instalator Tesseract OCR", log)
    _download_deu(deu_path, log)

    tessdata = DEFAULT_INSTALL_DIR / "tessdata"
    bat_path = work_dir / "install.bat"
    bat_path.write_text(
        "@echo off\r\n"
        f'"{installer_path}" /S\r\n'
        "if errorlevel 1 exit /b 1\r\n"
        f'copy /Y "{deu_path}" "{tessdata}\\deu.traineddata" >NUL\r\n',
        encoding="utf-8",
    )

    log("Instalujem Tesseract (povol pristup v okne Windows, ktore vyskoci)...")
    if not _run_elevated_bat(bat_path):
        log("Instalacia bola zrusena (nepovoleny pristup spravcu).")
        return False
    return True


def install_german_only(tesseract_cmd: str | None, log=print) -> bool:
    """Tesseract uz je nainstalovany, chyba len nemcina - stiahne
    deu.traineddata a skopiruje ho (s pravami spravcu) do tessdata."""
    work_dir = Path(tempfile.mkdtemp(prefix="fotorotator_tesseract_"))
    deu_path = work_dir / "deu.traineddata"
    _download_deu(deu_path, log)

    tessdata = _tessdata_dir(tesseract_cmd)
    bat_path = work_dir / "install_deu.bat"
    bat_path.write_text(
        "@echo off\r\n"
        f'copy /Y "{deu_path}" "{tessdata}\\deu.traineddata" >NUL\r\n',
        encoding="utf-8",
    )

    log("Kopirujem nemecky jazykovy balik (povol pristup v okne Windows)...")
    if not _run_elevated_bat(bat_path):
        log("Kopirovanie bolo zrusene (nepovoleny pristup spravcu).")
        return False
    return True
