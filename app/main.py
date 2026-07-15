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
        help=(
            "Posli kazdu fotku aj na Claude API (vision): overi spravnost otocenia "
            "(napr. elektromery s naopak nalepenymi nalepkami), precita stav "
            "elektromera z LCD displeja a zalohuje citanie stitku. Vyzaduje "
            "ANTHROPIC_API_KEY."
        ),
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


def try_extract_ids(image, use_ocr: bool) -> dict:
    return id_extract.extract_ids_via_tesseract(image) if use_ocr else {key: None for key in id_extract.IDS}


def setup_ocr() -> bool:
    """Over Tesseract; ak chyba (cely alebo len nemcina), ponukni automaticku
    instalaciu. Vrati True, ked je OCR pripravene."""
    status = tesseract_check.diagnose()
    if status == "ok":
        return True

    from . import tesseract_install

    if status == "missing":
        answer = input(
            "Tesseract OCR nie je nainstalovany. Chces ho teraz automaticky "
            "stiahnut a nainstalovat (aj s nemcinou)? [A/n]: "
        )
        if answer.strip().lower() in ("", "a", "ano", "y", "yes"):
            try:
                tesseract_install.install_full()
            except Exception as exc:
                print(f"Automaticka instalacia zlyhala: {exc}")
    else:  # no_deu
        answer = input(
            "Tesseractu chyba nemecky jazykovy balik. Chces ho teraz "
            "automaticky stiahnut a doplnit? [A/n]: "
        )
        if answer.strip().lower() in ("", "a", "ano", "y", "yes"):
            try:
                tesseract_install.install_german_only(tesseract_check.find_tesseract_cmd())
            except Exception as exc:
                print(f"Stiahnutie jazykoveho balika zlyhalo: {exc}")

    return tesseract_check.ensure_tesseract()


def find_photo_folders(root: Path) -> list[Path]:
    """Najde vsetky priecinky (vratane korena a vnorenych), ktore priamo
    obsahuju fotky. Vystupne priecinky (otocene_*) sa preskakuju. Zoznam je
    zoradeny abecedne - poradie priecinkov je vzdy rovnake a deterministicke."""
    candidates = [root] + sorted(
        p for p in root.rglob("*")
        if p.is_dir() and not any(part.startswith("otocene_") for part in p.relative_to(root).parts)
    )
    return [d for d in candidates if rotate.list_photos(d)]


def process_folder(photos_folder: Path, out_dir: Path, use_ocr: bool, use_claude_api: bool) -> dict:
    """Spracuje JEDEN priecinok s fotkami do out_dir - fotky sa zoradia,
    otocia a ocisluju VYHRADNE v ramci tohto priecinka, takze sa nemozu
    pomiesat s fotkami z inych priecinkov. Vrati suhrn spracovania."""
    out_dir.mkdir(parents=True, exist_ok=True)

    log_lines = []
    ids = {key: None for key in id_extract.IDS}
    ids_source_file = None
    meter_reading = None
    meter_source_file = None
    photo_count = 0
    uncertain_count = 0
    error_count = 0

    sorted_photos = rotate.sort_photos(rotate.list_photos(photos_folder))

    for index, (path, capture_time, used_exif) in enumerate(sorted_photos, start=1):
        output_name = rotate.output_name_for(index, path)
        try:
            processed = rotate.process_photo(path, use_ocr=use_ocr)
            rotation_applied = processed.rotation_applied
            rotation_uncertain = processed.rotation_uncertain
            image = processed.image
            api_note = ""

            if use_claude_api:
                from . import claude_check

                try:
                    result = claude_check.analyze_photo(image)
                    if result["rotate"]:
                        image = image.rotate(-result["rotate"], expand=True)
                        rotation_applied = (rotation_applied + result["rotate"]) % 360
                        api_note = f", otocenie opravene Claude API (+{result['rotate']})"
                    # Uspesna API kontrola (A/B porovnanie) orientaciu overila -
                    # lokalna neistota uz neplati, aj ked sa otocenie nemenilo.
                    rotation_uncertain = False
                    if meter_reading is None and result["reading"]:
                        meter_reading = result["reading"]
                        meter_source_file = output_name
                    for key in id_extract.IDS:
                        if ids[key] is None and result.get(key):
                            ids[key] = result[key]
                            ids_source_file = output_name
                except Exception as exc:
                    log_lines.append(f"  Claude API zlyhalo pri fotke {output_name}: {exc}")

            rotate.save_output(image, path, out_dir / output_name)
            photo_count += 1

            time_source = "EXIF" if used_exif else "datum zmeny suboru"
            status = f"otocena o {rotation_applied} stupnov" if rotation_applied else "bez zmeny (uz vodorovna)"
            if rotation_uncertain:
                status += " - NEISTA ROTACIA, skontroluj rucne"
                uncertain_count += 1
            log_lines.append(f"{output_name}: cas={capture_time} ({time_source}), {status}{api_note}")

            if any(ids[key] is None for key in id_extract.IDS) and index <= MAX_LABEL_ATTEMPTS:
                found = try_extract_ids(image, use_ocr)
                for key in id_extract.IDS:
                    if ids[key] is None and found.get(key):
                        ids[key] = found[key]
                        ids_source_file = output_name

        except Exception as exc:
            error_count += 1
            log_lines.append(f"{path.name}: CHYBA pri spracovani - {exc} (fotka preskocena)")

    ids_lines = [f"{DISPLAY_LABELS[key]}: {ids[key] or 'NENAJDENE'}" for key in id_extract.IDS]
    if meter_reading is not None:
        reading_text = meter_reading if "kwh" in meter_reading.lower() else f"{meter_reading} kWh"
        ids_lines.append(f"Stav elektromera (1.8.0): {reading_text}")
        if meter_source_file:
            ids_lines.append(f"(stav precitany z fotky: {meter_source_file})")
    if ids_source_file:
        ids_lines.append(f"(najdene na fotke: {ids_source_file})")
    else:
        ids_lines.append("(nepodarilo sa najst ziadne z ID cisel na prvych fotkach)")

    (out_dir / "identifikacne_cisla.txt").write_text("\n".join(ids_lines), encoding="utf-8")
    (out_dir / "log.txt").write_text("\n".join(log_lines), encoding="utf-8")

    return {
        "ids_lines": ids_lines,
        "photo_count": photo_count,
        "uncertain_count": uncertain_count,
        "error_count": error_count,
    }


def main():
    args = parse_args()

    folder = Path(args.folder) if args.folder else ask_for_folder()
    if folder is None:
        print("Nebol vybrany ziadny priecinok, koniec.")
        return
    if not folder.is_dir():
        print(f"Priecinok '{folder}' neexistuje.")
        sys.exit(1)

    has_tesseract = setup_ocr()
    if not has_tesseract:
        answer = input(
            "Pokracovat aj bez OCR? Fotky sa otocia iba podla EXIF a ID cisla "
            "sa nevytiahnu. [a/N]: "
        )
        if answer.strip().lower() not in ("a", "ano", "y", "yes"):
            sys.exit(1)

    rotate.register_heif_support()

    photo_folders = find_photo_folders(folder)
    if not photo_folders:
        print(
            f"V priecinku '{folder}' (ani v jeho podpriecinkoch) sa nenasli ziadne "
            "podporovane fotky (jpg/jpeg/png/heic/heif)."
        )
        sys.exit(1)

    output_root = make_output_dir(folder)

    if photo_folders == [folder]:
        # Jednoduchy rezim: fotky su priamo vo vybranom priecinku.
        summary_info = process_folder(folder, output_root, has_tesseract, args.use_claude_api)
        summary = "\n".join(summary_info["ids_lines"])
        if summary_info["uncertain_count"]:
            summary += f"\n\nPOZOR: {summary_info['uncertain_count']} fotiek ma neistu rotaciu - pozri log.txt"
    else:
        # Viac priecinkov: kazdy sa spracuje samostatne do vlastneho
        # podpriecinka vo vystupe - cislovanie, poradie aj ID cisla su
        # oddelene, fotky z roznych priecinkov sa nemozu pomiesat.
        safe_print(f"Najdenych priecinkov s fotkami: {len(photo_folders)}")
        overview_lines = []
        total_photos = 0
        for photos_folder in photo_folders:
            rel = photos_folder.relative_to(folder)
            label = str(rel) if str(rel) != "." else "(hlavny priecinok)"
            out_sub = output_root / rel if str(rel) != "." else output_root / "hlavny_priecinok"
            safe_print(f"Spracovavam: {label} ...")
            info = process_folder(photos_folder, out_sub, has_tesseract, args.use_claude_api)
            total_photos += info["photo_count"]
            overview_lines.append(f"[{label}]")
            overview_lines.extend(info["ids_lines"])
            note = f"(fotiek: {info['photo_count']}"
            if info["uncertain_count"]:
                note += f", neiste rotacie: {info['uncertain_count']}"
            if info["error_count"]:
                note += f", chyby: {info['error_count']}"
            overview_lines.append(note + ")")
            overview_lines.append("")

        overview = [
            f"PREHLAD SPRACOVANIA - {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            f"Priecinkov: {len(photo_folders)}, fotiek spolu: {total_photos}",
            "",
        ] + overview_lines
        (output_root / "prehlad.txt").write_text("\n".join(overview), encoding="utf-8")
        summary = "\n".join(overview_lines).strip()

    safe_print("\nHotovo. Vysledok:")
    safe_print(summary)
    safe_print(f"\nVystup je v priecinku: {output_root}")

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Hotovo", f"{summary}\n\nVystup:\n{output_root}")
    root.destroy()


if __name__ == "__main__":
    main()
