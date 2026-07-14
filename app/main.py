"""Vstupny bod: otoci fotky z merania do landscape orientacie a vytiahne
Seriennr./Zaehlernr. zo stitku. Spustenie: FotoRotator.exe [priecinok]
[--use-claude-api]"""

import argparse
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from . import id_extract, rotate, tesseract_check

MAX_LABEL_ATTEMPTS = 5  # kolko prvych fotiek skusit pre Seriennr./Zaehlernr.

# Zobrazovacie popisky pre pouzivatela (interne sa pouziva ASCII kluc
# "Zaehlernr" kvoli regexom a bezpecnemu vypisu do konzoly).
DISPLAY_LABELS = {"Seriennr": "Seriennr", "Zaehlernr": "Zählernr"}


def safe_print(text: str):
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding))


def ask_for_folder() -> Path | None:
    root = tk.Tk()
    root.withdraw()
    selected = filedialog.askdirectory(title="Vyber priecinok s fotkami z merania")
    root.destroy()
    return Path(selected) if selected else None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Otoci fotky z merania do landscape a vytiahne ID cisla zo stitku."
    )
    parser.add_argument("folder", nargs="?", help="Priecinok s fotkami")
    parser.add_argument(
        "--use-claude-api",
        action="store_true",
        help="Pouzi Claude API (vision) ako zalozny sposob citania stitku, ak lokalny OCR zlyha.",
    )
    return parser.parse_args()


def make_output_dir(folder: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = folder / f"otocene_{timestamp}"
    suffix = 2
    candidate = output_dir
    while candidate.exists():
        candidate = folder / f"otocene_{timestamp}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def try_extract_ids(image, use_ocr: bool, use_claude_api: bool, log_lines: list) -> dict:
    found = id_extract.extract_ids_via_tesseract(image) if use_ocr else {key: None for key in id_extract.IDS}
    missing = [key for key in id_extract.IDS if not found.get(key)]
    if use_claude_api and missing:
        try:
            claude_found = id_extract.extract_ids_via_claude(image)
            for key in missing:
                if claude_found.get(key):
                    found[key] = claude_found[key]
        except Exception as exc:
            log_lines.append(f"  Claude API zlyhalo pri citani stitku: {exc}")
    return found


def main():
    args = parse_args()

    folder = Path(args.folder) if args.folder else ask_for_folder()
    if folder is None:
        print("Nebol vybrany ziadny priecinok, koniec.")
        return
    if not folder.is_dir():
        print(f"Priecinok '{folder}' neexistuje.")
        sys.exit(1)

    has_tesseract = tesseract_check.ensure_tesseract()
    if not has_tesseract:
        answer = input(
            "Pokracovat aj bez OCR? Fotky sa oriented iba podla EXIF a ID cisla "
            "sa nevytiahnu. [a/N]: "
        )
        if answer.strip().lower() not in ("a", "ano", "y", "yes"):
            sys.exit(1)

    rotate.register_heif_support()

    photos = rotate.list_photos(folder)
    if not photos:
        print(f"V priecinku '{folder}' sa nenasli ziadne podporovane fotky (jpg/jpeg/png/heic/heif).")
        sys.exit(1)

    sorted_photos = rotate.sort_photos(photos)
    output_dir = make_output_dir(folder)

    log_lines = []
    ids = {key: None for key in id_extract.IDS}
    ids_source_file = None

    for index, (path, capture_time, used_exif) in enumerate(sorted_photos, start=1):
        output_name = rotate.output_name_for(index, path)
        try:
            processed = rotate.process_photo(path, use_ocr=has_tesseract)
            rotate.save_output(processed.image, path, output_dir / output_name)

            time_source = "EXIF" if used_exif else "datum zmeny suboru"
            status = f"otocena o {processed.rotation_applied} stupnov" if processed.rotation_applied else "bez zmeny (uz vodorovna)"
            if processed.rotation_uncertain:
                status += " - NEISTA ROTACIA, skontroluj rucne"
            log_lines.append(f"{output_name}: cas={capture_time} ({time_source}), {status}")

            if any(ids[key] is None for key in id_extract.IDS) and index <= MAX_LABEL_ATTEMPTS:
                found = try_extract_ids(processed.image, has_tesseract, args.use_claude_api, log_lines)
                for key in id_extract.IDS:
                    if ids[key] is None and found.get(key):
                        ids[key] = found[key]
                        ids_source_file = output_name

        except Exception as exc:
            log_lines.append(f"{path.name}: CHYBA pri spracovani - {exc} (fotka preskocena)")

    ids_lines = [f"{DISPLAY_LABELS[key]}: {ids[key] or 'NENAJDENE'}" for key in id_extract.IDS]
    if ids_source_file:
        ids_lines.append(f"(najdene na fotke: {ids_source_file})")
    else:
        ids_lines.append("(nepodarilo sa najst ziadne z ID cisel na prvych fotkach)")

    (output_dir / "identifikacne_cisla.txt").write_text("\n".join(ids_lines), encoding="utf-8")
    (output_dir / "log.txt").write_text("\n".join(log_lines), encoding="utf-8")

    summary = "\n".join(ids_lines)
    safe_print("\nHotovo. Vysledok:")
    safe_print(summary)
    safe_print(f"\nVystup je v priecinku: {output_dir}")

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Hotovo", f"{summary}\n\nVystup:\n{output_dir}")
    root.destroy()


if __name__ == "__main__":
    main()
