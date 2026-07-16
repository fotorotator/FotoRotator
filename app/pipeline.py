"""Samotne spracovanie fotiek (bez GUI) - vola sa z okna programu.

Kazdy priecinok s fotkami sa spracuje samostatne: vlastne chronologicke
poradie, cislovanie od 001, vlastne identifikacne_cisla.txt a log.txt.
Fotky z roznych priecinkov sa nemozu pomiesat.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import id_extract, rotate

MAX_LABEL_ATTEMPTS = 10  # kolko prvych fotiek skusit pre Seriennr./Zaehlernr. (lokalny OCR fallback;
# v rezime AI kontroly sa Seriennr/Zaehlernr aj tak skusa na KAZDEJ fotke cez Claude, bez tohto limitu)

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


def _friendly_api_error(exc_text: str) -> str:
    """Prelozi najcastejsie chyby Claude API do zrozumitelnej slovenciny -
    zobrazuje sa priamo vo vysledku, nech chyba nezostane schovana v logu."""
    if "credit balance is too low" in exc_text:
        return ("na Claude účte nie je dostatočný kredit — dobi si ho na "
                "console.anthropic.com (Plans & Billing)")
    if "invalid x-api-key" in exc_text or "authentication_error" in exc_text:
        return "API kľúč je neplatný — vlož v okne programu nový"
    if "rate_limit" in exc_text or "overloaded" in exc_text:
        return "API je dočasne preťažené — skús o chvíľu znova"
    return exc_text[:120]


def _process_one_photo(
    index: int,
    path: Path,
    capture_time,
    used_exif: bool,
    out_dir: Path,
    use_ocr: bool,
    use_claude_api: bool,
    model: str | None,
    max_side: int | None,
    quality: int,
    cancel_event: threading.Event | None,
    ids_complete_event: threading.Event,
) -> dict:
    """Kompletne spracuje JEDNU fotku (rotacia, volitelna AI kontrola,
    ulozenie, lokalny OCR fallback na ID). Vracia slovnik s vysledkami -
    agregacia (poradie logu, vyber ID podla najnizsieho indexu, sucty) sa
    robi az v process_folder, takze funkcia moze bezat v lubovolnom poradi
    aj subezne s inymi fotkami."""
    output_name = rotate.output_name_for(index, path)
    entry = {
        "index": index, "output_name": output_name,
        "skipped": False, "error": None, "api_error": None,
        "log": None, "extra_log": [],
        "uncertain": False, "cost": 0.0,
        "ids": {}, "reading": None,
    }

    if cancel_event is not None and cancel_event.is_set():
        entry["skipped"] = True
        return entry

    try:
        processed = rotate.process_photo(path, use_ocr=use_ocr)
        rotation_applied = processed.rotation_applied
        rotation_uncertain = processed.rotation_uncertain
        image = processed.image
        api_note = ""

        if use_claude_api:
            from . import claude_check

            try:
                result = claude_check.analyze_photo(image, model=model or claude_check.DEFAULT_MODEL)
                if result.get("cost_usd"):
                    entry["cost"] = result["cost_usd"]
                if result["rotate"]:
                    image = image.rotate(-result["rotate"], expand=True)
                    rotation_applied = (rotation_applied + result["rotate"]) % 360
                    api_note = f", otocenie opravene Claude API (+{result['rotate']})"
                # Uspesna API kontrola (A/B porovnanie) orientaciu overila -
                # lokalna neistota uz neplati, aj ked sa otocenie nemenilo.
                rotation_uncertain = False
                entry["reading"] = result["reading"]
                for key in id_extract.IDS:
                    if result.get(key):
                        entry["ids"][key] = result[key]
            except Exception as exc:
                entry["extra_log"].append(f"  Claude API zlyhalo pri fotke {output_name}: {exc}")
                entry["api_error"] = _friendly_api_error(str(exc))

        rotate.save_output(image, path, out_dir / output_name, max_side=max_side, quality=quality)

        time_source = "EXIF" if used_exif else "datum zmeny suboru"
        status = f"otocena o {rotation_applied} stupnov" if rotation_applied else "bez zmeny (uz vodorovna)"
        if rotation_uncertain:
            status += " - NEISTA ROTACIA, skontroluj rucne"
            entry["uncertain"] = True
        entry["log"] = f"{output_name}: cas={capture_time} ({time_source}), {status}{api_note}"

        # Lokalny OCR fallback na Seriennr/Zaehlernr - len na prvych
        # MAX_LABEL_ATTEMPTS fotkach a len kym ID nie su najdene (event
        # nastavuje agregacia, aby ostatne fotky uz OCR necitali zbytocne).
        if (
            use_ocr
            and index <= MAX_LABEL_ATTEMPTS
            and len(entry["ids"]) < len(id_extract.IDS)
            and not ids_complete_event.is_set()
        ):
            found = id_extract.extract_ids_via_tesseract(image)
            for key in id_extract.IDS:
                if key not in entry["ids"] and found.get(key):
                    entry["ids"][key] = found[key]

    except Exception as exc:
        entry["error"] = f"{path.name}: CHYBA pri spracovani - {exc} (fotka preskocena)"

    return entry


def process_folder(
    photos_folder: Path,
    out_dir: Path,
    use_ocr: bool,
    use_claude_api: bool,
    progress=None,
    cancel_event: threading.Event | None = None,
    model: str | None = None,
    max_side: int | None = None,
    quality: int = 95,
    concurrency: int = 1,
) -> dict:
    """Spracuje JEDEN priecinok s fotkami do out_dir. `progress(done_in_folder,
    total_in_folder, message)` sa vola po kazdej dokoncenej fotke.
    `max_side`/`quality` riadia velkost/kvalitu ulozenych fotiek.
    `concurrency` = kolko fotiek sa spracuva naraz (1 = postupne) - vystup
    (cislovanie, poradie logu, vyber ID) je pri kazdej hodnote rovnaky,
    subezne bezi len samotna praca. Vrati suhrn."""
    out_dir.mkdir(parents=True, exist_ok=True)

    log_lines = []
    ids = {key: None for key in id_extract.IDS}
    ids_source_file = None
    meter_reading = None
    meter_source_file = None
    photo_count = 0
    uncertain_count = 0
    error_count = 0
    cost_usd = 0.0

    sorted_photos = rotate.sort_photos(rotate.list_photos(photos_folder))
    total = len(sorted_photos)
    ids_complete_event = threading.Event()

    entries: dict[int, dict] = {}
    workers = max(1, min(int(concurrency or 1), 8))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _process_one_photo, index, path, capture_time, used_exif,
                out_dir, use_ocr, use_claude_api, model, max_side, quality,
                cancel_event, ids_complete_event,
            ): index
            for index, (path, capture_time, used_exif) in enumerate(sorted_photos, start=1)
        }
        done_count = 0
        for future in as_completed(futures):
            entry = future.result()
            entries[entry["index"]] = entry
            done_count += 1
            # Ked su obe ID najdene (hocikde), dalsie fotky uz OCR na stitok
            # nemusia skusat - len optimalizacia, na vysledok nema vplyv.
            found_keys = set()
            for e in entries.values():
                found_keys.update(k for k, v in e["ids"].items() if v)
            if len(found_keys) >= len(id_extract.IDS):
                ids_complete_event.set()
            if progress is not None and not entry["skipped"]:
                progress(done_count, total, entry["output_name"])

    # Agregacia v poradi fotiek (podla indexu) - log aj vyber ID/stavu su
    # deterministicke bez ohladu na to, v akom poradi fotky dobehli.
    cancelled = False
    api_error_count = 0
    api_error_reason = None
    for index in sorted(entries):
        entry = entries[index]
        if entry["skipped"]:
            cancelled = True
            continue
        if entry["error"]:
            error_count += 1
            log_lines.append(entry["error"])
            continue
        log_lines.extend(entry["extra_log"])
        log_lines.append(entry["log"])
        photo_count += 1
        cost_usd += entry["cost"]
        if entry["api_error"]:
            api_error_count += 1
            if api_error_reason is None:
                api_error_reason = entry["api_error"]
        if entry["uncertain"]:
            uncertain_count += 1
        if meter_reading is None and entry["reading"]:
            meter_reading = entry["reading"]
            meter_source_file = entry["output_name"]
        for key in id_extract.IDS:
            if ids[key] is None and entry["ids"].get(key):
                ids[key] = entry["ids"][key]
                ids_source_file = entry["output_name"]
    if cancelled:
        log_lines.append("PRERUSENE POUZIVATELOM - zvysne fotky nespracovane")

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
    if cost_usd:
        ids_lines.append(f"Cena AI kontroly: ${cost_usd:.4f}")
    if api_error_count:
        ids_lines.append(
            f"POZOR — AI kontrola zlyhala pri {api_error_count} z {photo_count} fotiek: {api_error_reason}"
        )

    (out_dir / "identifikacne_cisla.txt").write_text("\n".join(ids_lines), encoding="utf-8")
    (out_dir / "log.txt").write_text("\n".join(log_lines), encoding="utf-8")

    return {
        "ids_lines": ids_lines,
        "photo_count": photo_count,
        "uncertain_count": uncertain_count,
        "error_count": error_count,
        "cost_usd": cost_usd,
    }


def run_job(
    folder: Path,
    use_ocr: bool,
    use_claude_api: bool,
    progress=None,
    cancel_event: threading.Event | None = None,
    model: str | None = None,
    max_side: int | None = None,
    quality: int = 95,
    concurrency: int = 1,
) -> dict:
    """Cely beh: najde priecinky s fotkami a kazdy spracuje samostatne.
    `progress(done_total, total_photos, message)` hlasi celkovy priebeh.
    Vrati {"output_root": Path, "summary": str, "total_photos": int,
    "cost_usd": float}."""
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
    total_cost_usd = 0.0

    if photo_folders == [folder]:
        def folder_progress(done, total, name):
            if progress is not None:
                progress(done, total_photos, name)

        info = process_folder(folder, output_root, use_ocr, use_claude_api,
                              folder_progress, cancel_event, model=model,
                              max_side=max_side, quality=quality, concurrency=concurrency)
        total_cost_usd = info["cost_usd"]
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
                                  folder_progress, cancel_event, model=model,
                                  max_side=max_side, quality=quality, concurrency=concurrency)
            done_before += totals[photos_folder]
            total_cost_usd += info["cost_usd"]
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
        if total_cost_usd:
            overview.insert(2, f"Cena AI kontroly spolu: ${total_cost_usd:.4f}")
        (output_root / "prehlad.txt").write_text("\n".join(overview), encoding="utf-8")
        summary = "\n".join(overview_lines).strip()
        if total_cost_usd:
            summary += f"\n\nCena AI kontroly spolu: ${total_cost_usd:.4f}"

    return {
        "output_root": output_root,
        "summary": summary,
        "total_photos": total_photos,
        "cost_usd": total_cost_usd,
    }
