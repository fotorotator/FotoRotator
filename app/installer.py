"""Auto-instalacia a auto-aktualizacia pri spusteni zabaleneho .exe.

Ked pouzivatel stiahne FotoRotator.exe (typicky do Stiahnute) a spusti ho,
program sa sam skopiruje/aktualizuje v Dokumenty\\FotoRotator, vytvori
skratku na plochu (ak chyba) a znovu sa spusti uz z tejto cesty - takto
nezostava "nainstalovany" priamo v priecinku Stiahnute a skratka na ploche
vzdy spusta aktualnu nainstalovanu verziu.

Kluc k spolahlivej aktualizacii: cielovy .exe moze byt prave spusteny (stara
verzia bezi na pozadi / v systemovej liste) - priame prepisanie (copy) vtedy
zlyha, lebo Windows nedovoli zapisovat do suboru, ktory ma otvoreny bezuci
proces. RIESENIE: bezuci .exe sa DA PREMENOVAT (bezuci proces si drzi svoj
povodny subor cez handle nezavisle od jeho mena v priecinku), takze sa stara
verzia odsunie nabok a na jej miesto sa skopiruje nova - dalsie spustenie
skratky uz pouzije novy obsah, aj ked stara instancia medzicasom dobehne.
Ak uz bezi presne z cielovej cesty (t.j. spusteny cez tuto skratku), nic sa
neaktualizuje - len sa doplni skratka na plochu, ak by nahodou chybala.
"""

from __future__ import annotations

import ctypes
import hashlib
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


def _replace_possibly_running_exe(target_path: Path, source_path: Path) -> bool:
    """Nahradi obsah target_path obsahom source_path, aj ked je target_path
    prave spusteny (zamknuty bezucim procesom). Skusi priamy zapis; ak
    zlyha, subor najprv premenuje nabok (to Windows dovoli aj pri bezuci
    .exe) a az potom skopiruje novy na jeho miesto. Pri zlyhani sa povodny
    subor vrati spat, aby appka nikdy neostala bez funkcnej instalacie."""
    try:
        shutil.copy2(source_path, target_path)
        return True
    except OSError:
        pass  # pravdepodobne zamknuty bezucim procesom - skusime premenovat

    backup = target_path.with_name(target_path.name + ".old")
    try:
        if backup.exists():
            backup.unlink()
    except OSError:
        pass  # predoslý needpratany zvysok - skusime prepisat nizsie aj tak

    try:
        target_path.rename(backup)
    except OSError:
        return False  # ani premenovanie nevyslo - vzdame to, appka zostava na starej verzii

    try:
        shutil.copy2(source_path, target_path)
    except OSError:
        try:
            backup.rename(target_path)  # vratime povodny subor spat, nech appka ostane funkcna
        except OSError:
            pass
        return False

    try:
        backup.unlink()  # stary subor uz nepotrebujeme (ak sa medzicasom uvolnil)
    except OSError:
        pass  # stara bezuca instancia ho este drzi - zmaze sa niekedy pri buducej aktualizacii

    return True


def ensure_installed(documents_dir: Path | None = None, desktop_dir: Path | None = None) -> bool:
    """Ak bezi zabaleny .exe mimo cielovej cesty (Dokumenty\\FotoRotator),
    zaisti, aby tam bola najnovsia verzia (aj ked tam uz nejaka je a prave
    bezi), vytvori skratku na plochu (ak chyba) a znovu sa spusti odtial.

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

    # Prilezitostne upraceme zvysok z predoslej aktualizacie, ktory sa vtedy
    # nedal zmazat (stara verzia ho este drzala) - skusa sa pri kazdom
    # spusteni, nielen ked prave prebieha dalsia aktualizacia.
    stale_backup = target_exe.with_name(target_exe.name + ".old")
    try:
        stale_backup.unlink()
    except OSError:
        pass

    already_at_target = str(current_exe).lower() == str(target_exe).lower()

    if not already_at_target:
        target_dir.mkdir(parents=True, exist_ok=True)
        needs_update = not target_exe.exists() or not _files_identical(target_exe, current_exe)
        if needs_update and not _replace_possibly_running_exe(target_exe, current_exe):
            return False  # aktualizacia sa nepodarila (napr. aj premenovanie zlyhalo) - pokracuj z aktualnej kopie

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
