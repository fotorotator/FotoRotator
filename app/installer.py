"""Auto-instalacia a auto-aktualizacia pri spusteni zabaleneho .exe.

Ked pouzivatel stiahne FotoRotator.exe (typicky do Stiahnute) a spusti ho,
program sa sam skopiruje/aktualizuje v Dokumenty\\FotoRotator, vytvori
skratku na plochu (ak chyba) a znovu sa spusti uz z tejto cesty - takto
nezostava "nainstalovany" priamo v priecinku Stiahnute a skratka na ploche
vzdy spusta aktualnu nainstalovanu verziu.

Ak je cielovy .exe prave spusteny (stara verzia bezi na pozadi / v
systemovej liste), aktualizacia sa NEPREPISUJE poticho "pod rukou" - rovnako
ako klasicke Windows instalatory najprv poziada pouzivatela, aby bezuci
program zavrel (alebo ho zavrie sam na jeho ziadost), a az potom nainstaluje
novu verziu. Ak uz bezi presne z cielovej cesty (t.j. spusteny cez tuto
skratku), nic sa neaktualizuje - len sa doplni skratka na plochu, ak by
nahodou chybala.
"""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import sys
import time
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


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files_identical(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return _sha256_of(a) == _sha256_of(b)
    except OSError:
        return False


def _try_copy(target_path: Path, source_path: Path) -> bool:
    try:
        shutil.copy2(source_path, target_path)
        return True
    except OSError:
        return False


def _close_running_instances(exe_path: Path):
    """Ticho ukonci vsetky bezuce procesy spustene z presne tejto cesty
    (typicky stara verzia FotoRotatora) - vola sa len na vyslovnu ziadost
    pouzivatela (tlacidlo v dialogu), nikdy sama od seba."""
    ps_script = (
        f"Get-Process | Where-Object {{ $_.Path -eq '{_escape_ps(str(exe_path))}' }} "
        "| Stop-Process -Force"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        )
    except Exception:
        pass


def _ask_close_and_retry(target_exe: Path) -> bool:
    """FotoRotator je prave spusteny a subor sa neda aktualizovat - zobrazi
    okno s ziadostou, aby ho pouzivatel zavrel (bud sam, alebo tlacidlom
    v tomto okne), s moznostou Skusit znova / Zrusit. Vrati True, ak sa ma
    kopirovanie skusit znova, False ak pouzivatel zrusil aktualizaciu."""
    import tkinter as tk
    from tkinter import ttk

    outcome = {"retry": False}

    root = tk.Tk()
    root.title("FotoRotator — aktualizácia")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.eval("tk::PlaceWindow . center")

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(
        frame,
        text=(
            "Je dostupná nová verzia programu, ale FotoRotator je momentálne "
            "spustený (aj keby len v systémovej lište).\n\n"
            "Pred inštaláciou aktualizácie ho treba zavrieť."
        ),
        wraplength=380, justify="left",
    ).pack(pady=(0, 16))

    def on_auto_close():
        _close_running_instances(target_exe)
        time.sleep(1)
        outcome["retry"] = True
        root.destroy()

    def on_retry():
        outcome["retry"] = True
        root.destroy()

    def on_cancel():
        outcome["retry"] = False
        root.destroy()

    ttk.Button(
        frame, text="Zavrieť FotoRotator a nainštalovať aktualizáciu", command=on_auto_close,
    ).pack(fill="x", pady=(0, 8))

    button_row = ttk.Frame(frame)
    button_row.pack(fill="x")
    ttk.Button(button_row, text="Už som ho zavrel — skúsiť znova", command=on_retry).pack(side="left")
    ttk.Button(button_row, text="Zrušiť", command=on_cancel).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()

    return outcome["retry"]


def ensure_installed(documents_dir: Path | None = None, desktop_dir: Path | None = None) -> bool:
    """Ak bezi zabaleny .exe mimo cielovej cesty (Dokumenty\\FotoRotator),
    zaisti, aby tam bola najnovsia verzia, vytvori skratku na plochu (ak
    chyba) a znovu sa spusti odtial. Ak je cielovy subor prave spusteny,
    poziada pouzivatela o zatvorenie (viz _ask_close_and_retry) - nikdy ho
    neprepisuje poticho "pod rukou".

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
        target_dir.mkdir(parents=True, exist_ok=True)
        needs_update = not target_exe.exists() or not _files_identical(target_exe, current_exe)
        if needs_update:
            while not _try_copy(target_exe, current_exe):
                if not _ask_close_and_retry(target_exe):
                    return False  # pouzivatel zrusil - pokracuj z aktualnej (nenainstalovanej) kopie

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
