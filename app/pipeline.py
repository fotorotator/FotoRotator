"""Samotne spracovanie fotiek (bez GUI) - vola sa z okna programu.

Kazdy priecinok s fotkami sa spracuje samostatne: vlastne chronologicke
poradie, cislovanie od 001, vlastne identifikacne_cisla.txt a log.txt.
Fotky z roznych priecinkov sa nemozu pomiesat.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from . import id_extract, rotate

MAX_LABEL_ATTEMPTS = 5  # kolko prvych fotiek skusit pre Seriennr./Zaehlernr.

# Zobrazovacie popisky (interne sa pouziva ASCII kluc "Zaehlernr" kvoli
# regexom a bezpecnemu vypisu).
DISPLAY_LABELS = {"Seriennr": "Seriennr", "Zaehlernr": "Zählernr"}


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


def find_photo_folders(root: Path) -> list[Path]:
    """Najde vsetky priecinky (vratane korena a vnorenych), ktore priamo
    obsahuju fotky. Vystupne priecinky (otocene_*) sa preskakuju. Zoznam je
    zoradeny abecedne - poradie je deterministicke."""
    candidates = [root] + sorted(
        p for p in root.rglob("*")
        if p.is_dir() and not any(part.startswith("otocene_") for part in p.relative_to(root).parts)
    )
    return [d for d in candidates if rotate.list_photos(d)]


def try_extract_ids(image, use_ocr: bool) -> dict:
    return id_extract.extract_ids_via_tesseract(image) if use_ocr else {key: None for key in id_extract.IDS}


def process_folder(
    photos_folder: Path,
    out_dir: Path,
    use_ocr: bool,
    use_claude_api: bool,
    progress=None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Spracuje JEDEN priecinok s fotkami do out_dir. `progress(done_in_folder,
    total_in_folder, message)` sa vola po kazdej fotke. Vrati suhrn."""
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
    total = len(sorted_photos)

    for index, (path, capture_time, used_exif) in enumerate(sorted_photos, start=1):
        if cancel_event is not None and cancel_event.is_set():
            log_lines.append("PRERUSENE POUZIVATELOM - zvysne fotky nespracovane")
            break
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

        if progress is not None:
            progress(index, total, output_name)

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


def run_job(
    folder: Path,
    use_ocr: bool,
    use_claude_api: bool,
    progress=None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Cely beh: najde priecinky s fotkami a kazdy spracuje samostatne.
    `progress(done_total, total_photos, message)` hlasi celkovy priebeh.
    Vrati {"output_root": Path, "summary": str, "total_photos": int}."""
    photo_folders = find_photo_folders(folder)
    if not photo_folders:
        raise RuntimeError(
            f"V priecinku '{folder}' (ani v podpriecinkoch) sa nenasli ziadne "
            "podporovane fotky (jpg/jpeg/png/heic/heif)."
        )

    totals = {f: len(rotate.list_photos(f)) for f in photo_folders}
    total_photos = sum(totals.values())
    output_root = make_output_dir(folder)
    done_before = 0

    if photo_folders == [folder]:
        def folder_progress(done, total, name):
            if progress is not None:
                progress(done, total_photos, name)

        info = process_folder(folder, output_root, use_ocr, use_claude_api,
                              folder_progress, cancel_event)
        summary = "\n".join(info["ids_lines"])
        if info["uncertain_count"]:
            summary += f"\n\nPOZOR: {info['uncertain_count']} fotiek ma neistu rotaciu - pozri log.txt"
    else:
        overview_lines = []
        for photos_folder in photo_folders:
            if cancel_event is not None and cancel_event.is_set():
                break
            rel = photos_folder.relative_to(folder)
            label = str(rel) if str(rel) != "." else "(hlavny priecinok)"
            out_sub = output_root / rel if str(rel) != "." else output_root / "hlavny_priecinok"

            def folder_progress(done, total, name, _base=done_before, _label=label):
                if progress is not None:
                    progress(_base + done, total_photos, f"{_label} - {name}")

            info = process_folder(photos_folder, out_sub, use_ocr, use_claude_api,
                                  folder_progress, cancel_event)
            done_before += totals[photos_folder]
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

    return {"output_root": output_root, "summary": summary, "total_photos": total_photos}
