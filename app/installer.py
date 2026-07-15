"""Auto-instalacia pri prvom spusteni zabaleneho .exe.

Ked pouzivatel stiahne FotoRotator.exe (typicky do Stiahnute) a spusti ho,
program sa sam skopiruje do Dokumenty\\FotoRotator, vytvori skratku na
plochu a znovu sa spusti uz z tejto novej cesty - takto nezostava
"nainstalovany" priamo v priecinku Stiahnute a pouzivatel ma normalnu
skratku na plochu ako pri hocijakom inom programe.

Ak uz bezi presne z cielovej cesty (t.j. spusteny cez tuto skratku), nic sa
nekopiruje - len sa doplni skratka na plochu, ak by nahodou chybala.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

APP_EXE_NAME = "FotoRotator.exe"
SHORTCUT_NAME = "FotoRotator.lnk"

_CSIDL_PERSONAL = 5           # Dokumenty (respektuje presmerovanie napr. na OneDrive)
_CSIDL_DESKTOPDIRECTORY = 16  # Plocha
_SHGFP_TYPE_CURRENT = 0


def _known_folder(csidl: int) -> Path:
    buffer = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, _SHGFP_TYPE_CURRENT, buffer)
    return Path(buffer.value)


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def _create_desktop_shortcut(target_exe: Path, shortcut_path: Path):
    ps_script = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$sc = $s.CreateShortcut('{_escape_ps(str(shortcut_path))}'); "
        f"$sc.TargetPath = '{_escape_ps(str(target_exe))}'; "
        f"$sc.WorkingDirectory = '{_escape_ps(str(target_exe.parent))}'; "
        f"$sc.IconLocation = '{_escape_ps(str(target_exe))},0'; "
        "$sc.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=True,
        timeout=15,
    )


def ensure_installed(documents_dir: Path | None = None, desktop_dir: Path | None = None) -> bool:
    """Ak bezi zabaleny .exe mimo cielovej cesty (Dokumenty\\FotoRotator),
    skopiruje sa tam, vytvori skratku na plochu a znovu sa spusti odtial.

    `documents_dir`/`desktop_dir` su len pre testy (aby sa dalo nasmerovat
    mimo skutocnej Plochy/Dokumentov pouzivatela) - za normalnej prevadzky
    sa zistuju automaticky.

    Vrati True, ak sa ma tento proces hned ukoncit (lebo uz pokracuje nova
    kopia), inak False (pokracuj normalne z aktualnej cesty)."""
    if not getattr(sys, "frozen", False):
        return False  # vyvojarsky beh (python -m app.main) - nic neinstaluj

    current_exe = Path(sys.executable).resolve()

    try:
        documents = documents_dir or _known_folder(_CSIDL_PERSONAL)
        desktop = desktop_dir or _known_folder(_CSIDL_DESKTOPDIRECTORY)
    except Exception:
        return False  # nepodarilo sa zistit systemove priecinky - radsej nic nerob

    target_dir = documents / "FotoRotator"
    target_exe = target_dir / APP_EXE_NAME
    shortcut_path = desktop / SHORTCUT_NAME

    already_at_target = str(current_exe).lower() == str(target_exe).lower()

    if not already_at_target:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_exe, target_exe)
        except OSError:
            return False  # napr. cielovy subor je prave uzamknuty (uz bezi) - pokracuj z aktualnej kopie

    if not shortcut_path.exists():
        try:
            _create_desktop_shortcut(target_exe, shortcut_path)
        except Exception:
            pass  # skratka nie je kriticka - appka funguje aj bez nej

    if already_at_target:
        return False

    try:
        subprocess.Popen(
            [str(target_exe), *sys.argv[1:]],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
        return True
    except OSError:
        return False  # spustenie kopie zlyhalo - pokracuj aspon z aktualnej
