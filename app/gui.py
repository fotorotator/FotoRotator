"""Okno programu FotoRotator (customtkinter - rovnaky vzhlad ako StrategyScribe).

- vyber priecinka s fotkami (zakazka s podpriecinkami alebo jedno meranie)
- ulozenie Claude API kluca (volitelne; DPAPI cez config.py) - s klucom sa
  automaticky zapina AI kontrola otocenia + citanie stavu elektromera
- priebeh prace: progress bar, aktualna fotka, zivy log
- na konci suhrn vysledkov a tlacidlo na otvorenie vystupneho priecinka
- skrytie do systemovej listy (pystray) - spracovanie bezi dalej na pozadi,
  po dokonceni prijde upozornenie priamo z listy
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pystray

from . import claude_check, config, icon, pipeline, rotate, tesseract_check, tesseract_install

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

API_KEYS_URL = "https://console.anthropic.com/settings/keys"
APP_VERSION = "0.4.4"

# Ponuka modelov pre AI kontrolu - poznamka pri kazdom hovori o cene/kvalite
# (ceny za milion tokenov vstup/vystup, k 7/2026). Haiku 4.5 je default -
# overene na realnych fotkach, ze na tuto ulohu staci (viz CLAUDE.md).
MODEL_OPTIONS = {
    "Claude Haiku 4.5 — najlacnejší, odporúčané ($1 / $5)": "claude-haiku-4-5",
    "Claude Sonnet 5 — kvalitnejší, ~2× drahší ($2 / $10)": "claude-sonnet-5",
    "Claude Opus 4.8 — najkvalitnejší bežný, ~5× drahší ($5 / $25)": "claude-opus-4-8",
    "Claude Fable 5 — najsilnejší vôbec, ~10× drahší ($10 / $50)": "claude-fable-5",
}
_MODEL_ID_TO_LABEL = {v: k for k, v in MODEL_OPTIONS.items()}

# Riadok vysledku v tvare "Popis: hodnota" (Seriennr, Zählernr, Stav
# elektromera (1.8.0), Cena AI kontroly, ...) - takyto riadok dostane v okne
# vysledku vlastne tlacidlo "Kopírovať". Poznamky, ktore CELE zacinaju
# zatvorkou (napr. "(najdene na fotke: ...)"), a nadpisy priecinkov v [ ]
# sa takto nerozpoznaju - zobrazia sa ako obycajny text (osetrene v cykle,
# lebo popis sam moze obsahovat zatvorku, napr. "Stav elektromera (1.8.0)").
_RESULT_KV_LINE = re.compile(r"^([^:]{1,40}):\s(.+)$")


def _resource_path(relative: str) -> Path:
    """Cesta k prilozenemu suboru (assets/...) - funguje aj v zabalenom
    .exe (PyInstaller rozbaluje data do docasneho priecinka _MEIPASS)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


def _make_tray_image():
    """Ikona pre systemovu listu - rovnaka ako ikona programu, len mensia."""
    return icon.draw_icon(64)


class App(ctk.CTk):
    def __init__(self, initial_folder: Path | None = None, auto_start: bool = False):
        super().__init__()
        self.title(f"FotoRotator v{APP_VERSION}")
        self.geometry("760x680")
        self.minsize(660, 580)
        try:
            self.iconbitmap(str(_resource_path("assets/icon.ico")))
        except Exception:
            pass  # chybajuca/nepodporovana ikona nema brzdit spustenie appky

        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.output_root: Path | None = None
        saved_config = config.load()
        self.saved_api_key = saved_config["api_key"]
        self.total_cost_usd = saved_config["total_cost_usd"]
        self.selected_model = saved_config["model"] or claude_check.DEFAULT_MODEL

        pad = {"padx": 12, "pady": (6, 0)}

        # --- Priecinok ---
        folder_frame = ctk.CTkFrame(self)
        folder_frame.pack(fill="x", **pad)
        ctk.CTkLabel(folder_frame, text="Priečinok s fotkami:").pack(side="left", padx=(12, 8), pady=10)
        self.folder_var = ctk.StringVar(value=str(initial_folder) if initial_folder else "")
        self.folder_entry = ctk.CTkEntry(folder_frame, textvariable=self.folder_var,
                                         placeholder_text="vyber priečinok zákazky alebo merania…")
        self.folder_entry.pack(side="left", fill="x", expand=True, pady=10)
        self.pick_button = ctk.CTkButton(folder_frame, text="Vybrať…", width=90, command=self.pick_folder)
        self.pick_button.pack(side="left", padx=12, pady=10)

        # --- API kluc ---
        api_frame = ctk.CTkFrame(self)
        api_frame.pack(fill="x", **pad)
        top_row = ctk.CTkFrame(api_frame, fg_color="transparent")
        top_row.pack(fill="x", padx=0, pady=(8, 0))
        ctk.CTkLabel(top_row, text="Claude API kľúč (voliteľné):").pack(side="left", padx=(12, 8))
        self.api_entry = ctk.CTkEntry(top_row, show="•",
                                      placeholder_text="sk-ant-…  (vlož kľúč a klikni Uložiť)")
        self.api_entry.pack(side="left", fill="x", expand=True)
        self.api_save_button = ctk.CTkButton(top_row, text="Uložiť kľúč", width=100, command=self.save_api_key)
        self.api_save_button.pack(side="left", padx=(8, 4))
        self.api_delete_button = ctk.CTkButton(top_row, text="Zmazať", width=70,
                                               fg_color="gray30", hover_color="gray25",
                                               command=self.delete_api_key)
        self.api_delete_button.pack(side="left", padx=(0, 12))

        model_row = ctk.CTkFrame(api_frame, fg_color="transparent")
        model_row.pack(fill="x", padx=0, pady=(4, 0))
        ctk.CTkLabel(model_row, text="Model AI kontroly:").pack(side="left", padx=(12, 8))
        self.model_menu = ctk.CTkOptionMenu(
            model_row, values=list(MODEL_OPTIONS.keys()), width=380,
            command=self._on_model_selected,
        )
        self.model_menu.set(_MODEL_ID_TO_LABEL.get(self.selected_model, next(iter(MODEL_OPTIONS))))
        self.model_menu.pack(side="left", padx=(0, 12))

        bottom_row = ctk.CTkFrame(api_frame, fg_color="transparent")
        bottom_row.pack(fill="x", padx=0, pady=(2, 8))
        self.ai_var = ctk.BooleanVar(value=bool(self.saved_api_key))
        self.ai_checkbox = ctk.CTkCheckBox(
            bottom_row, variable=self.ai_var,
            text="AI kontrola (správne otočenie ťažkých fotiek + stav elektromera z displeja)",
        )
        self.ai_checkbox.pack(side="left", padx=12)
        self.api_status = ctk.CTkLabel(bottom_row, text="", text_color="gray70")
        self.api_status.pack(side="right", padx=12)
        self.cost_label = ctk.CTkLabel(bottom_row, text="", text_color="gray70")
        self.cost_label.pack(side="right", padx=(12, 0))
        self._refresh_api_status()
        self._refresh_cost_label()

        # --- Spustit / Zastavit ---
        run_frame = ctk.CTkFrame(self, fg_color="transparent")
        run_frame.pack(fill="x", **pad)
        self.start_button = ctk.CTkButton(run_frame, text="Spustiť", height=40,
                                          font=ctk.CTkFont(size=16, weight="bold"),
                                          command=self.start)
        self.start_button.pack(side="left", fill="x", expand=True)
        self.stop_button = ctk.CTkButton(run_frame, text="Zastaviť", height=40, width=110,
                                         fg_color="#8B2E2E", hover_color="#742626",
                                         state="disabled", command=self.stop)
        self.stop_button.pack(side="left", padx=(8, 0))
        self.tray_button = ctk.CTkButton(run_frame, text="Skryť do lišty", height=40, width=130,
                                         fg_color="gray30", hover_color="gray25",
                                         command=self.minimize_to_tray)
        self.tray_button.pack(side="left", padx=(8, 0))

        # --- Priebeh ---
        self.progress = ctk.CTkProgressBar(self)
        self.progress.pack(fill="x", **pad)
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(self, text="Pripravený.", anchor="w")
        self.status_label.pack(fill="x", padx=12)

        # --- Log ---
        self.log_box = ctk.CTkTextbox(self, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(6, 0))

        # --- Vystup ---
        self.open_button = ctk.CTkButton(self, text="Otvoriť výstupný priečinok",
                                         state="disabled", command=self.open_output)
        self.open_button.pack(fill="x", padx=12, pady=(6, 12))

        self.tray_icon = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<FocusIn>", self._on_focus_in)
        self.after(100, self._poll_queue)

        if auto_start and initial_folder:
            self.after(300, self.start)

    # ---------- pomocne ----------

    def log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh_api_status(self):
        if self.saved_api_key:
            self.api_status.configure(text="kľúč uložený ✓", text_color="#7CC97C")
            if not self.api_entry.get():
                self.api_entry.configure(placeholder_text="kľúč je uložený (vlož nový pre zmenu)")
        else:
            self.api_status.configure(text="bez kľúča — offline režim", text_color="gray70")
            self.ai_var.set(False)

    def _refresh_cost_label(self):
        self.cost_label.configure(text=f"minuté doteraz: ${self.total_cost_usd:.4f}")

    def _on_focus_in(self, event):
        if event.widget is self:
            self._reload_cost_from_disk()

    def _reload_cost_from_disk(self):
        """Znova nacita celkovu minutu sumu zo suboru - rieli, ked ju medzitym
        zmenila ina spustena kopia programu (napr. druhe okno) a tato relacia
        by inak ukazovala zastaralu hodnotu z vlastneho startu."""
        try:
            self.total_cost_usd = config.load()["total_cost_usd"]
        except Exception:
            pass
        self._refresh_cost_label()

    def _set_running(self, running: bool):
        state = "disabled" if running else "normal"
        for widget in (self.start_button, self.pick_button, self.folder_entry,
                       self.api_entry, self.api_save_button, self.api_delete_button,
                       self.ai_checkbox, self.model_menu):
            widget.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    # ---------- akcie ----------

    def pick_folder(self):
        selected = filedialog.askdirectory(title="Vyber priečinok s fotkami z merania")
        if selected:
            self.folder_var.set(selected)

    def _on_model_selected(self, label: str):
        self.selected_model = MODEL_OPTIONS[label]
        config.save_model(self.selected_model)

    def save_api_key(self):
        key = self.api_entry.get().strip()
        if not key:
            messagebox.showinfo("API kľúč", f"Vlož kľúč do políčka.\nKľúč získaš na:\n{API_KEYS_URL}")
            return
        self.api_save_button.configure(state="disabled", text="Overujem…")

        def verify():
            try:
                import anthropic
                anthropic.Anthropic(api_key=key).models.list()
                self.queue.put(("api_key_ok", key))
            except Exception as exc:
                self.queue.put(("api_key_bad", str(exc)))

        threading.Thread(target=verify, daemon=True).start()

    def delete_api_key(self):
        if self.saved_api_key and messagebox.askyesno("Zmazať kľúč", "Naozaj zmazať uložený API kľúč?"):
            config.save_api_key("")
            self.saved_api_key = ""
            self.api_entry.delete(0, "end")
            self._refresh_api_status()
            self.log("API kľúč zmazaný — program pobeží offline.")

    def start(self):
        self._reload_cost_from_disk()
        folder_text = self.folder_var.get().strip().strip('"')
        if not folder_text:
            messagebox.showinfo("Priečinok", "Najprv vyber priečinok s fotkami.")
            return
        folder = Path(folder_text)
        if not folder.is_dir():
            messagebox.showerror("Priečinok", f"Priečinok '{folder}' neexistuje.")
            return

        use_api = bool(self.ai_var.get() and self.saved_api_key)
        if self.ai_var.get() and not self.saved_api_key:
            messagebox.showinfo("AI kontrola", "AI kontrola potrebuje uložený API kľúč — najprv ho vlož a ulož,"
                                               " alebo odškrtni AI kontrolu.")
            return
        if use_api:
            os.environ["ANTHROPIC_API_KEY"] = self.saved_api_key

        ocr_status = tesseract_check.diagnose()
        install_action = None
        if ocr_status == "missing":
            if messagebox.askyesno(
                "Tesseract OCR",
                "Tesseract OCR nie je nainštalovaný — bez neho sa nedá zistiť správne otočenie fotiek"
                " ani prečítať štítok.\n\nStiahnuť a nainštalovať ho teraz automaticky (aj s nemčinou)?"
                "\n(Vyskočí okno Windows na povolenie inštalácie.)",
            ):
                install_action = "full"
        elif ocr_status == "no_deu":
            if messagebox.askyesno(
                "Tesseract OCR",
                "Tesseractu chýba nemecký jazykový balík (potrebný na čítanie štítkov)."
                "\n\nStiahnuť a doplniť ho teraz automaticky?",
            ):
                install_action = "german"

        if ocr_status != "ok" and install_action is None:
            if not messagebox.askyesno(
                "Bez OCR",
                "Pokračovať bez OCR? Fotky sa otočia len podľa EXIF a ID čísla sa neprečítajú.",
            ):
                return

        self.cancel_event.clear()
        self.output_root = None
        self.open_button.configure(state="disabled")
        self.progress.set(0)
        self._set_running(True)
        model_note = f"  (AI kontrola zapnutá — {_MODEL_ID_TO_LABEL.get(self.selected_model, self.selected_model)})"
        self.log(f"Štart: {folder}" + (model_note if use_api else "  (offline režim)"))

        self.worker = threading.Thread(
            target=self._worker, args=(folder, install_action, use_api), daemon=True
        )
        self.worker.start()

    def stop(self):
        self.cancel_event.set()
        self.log("Zastavujem po aktuálnej fotke…")

    def open_output(self):
        if self.output_root and self.output_root.exists():
            os.startfile(self.output_root)

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()  # bez tohto sa obsah schranky niekedy strati po strate fokusu

    def _show_result_dialog(self, summary: str, output_root: Path):
        """Okno s vysledkom - kazda hodnota (Seriennr, Zählernr, stav
        elektromera, ...) ma vlastne tlacidlo 'Kopírovať', nemusi sa
        vypisovat rucne z logu."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Výsledok")
        dialog.geometry("580x520")
        dialog.minsize(420, 320)
        try:
            dialog.iconbitmap(str(_resource_path("assets/icon.ico")))
        except Exception:
            pass

        top_row = ctk.CTkFrame(dialog, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(top_row, text="Hotovo", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkButton(
            top_row, text="Kopírovať všetko", width=150,
            command=lambda: self._copy_to_clipboard(summary),
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(dialog)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        for raw_line in summary.splitlines():
            line = raw_line.rstrip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                ctk.CTkLabel(
                    scroll, text=line, font=ctk.CTkFont(weight="bold"), anchor="w",
                ).pack(fill="x", pady=(10, 2))
                continue
            match = None if line.startswith("(") else _RESULT_KV_LINE.match(line)
            if match:
                label, value = match.group(1), match.group(2)
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=f"{label}:", width=150, anchor="w").pack(side="left")
                ctk.CTkLabel(row, text=value, anchor="w", justify="left", wraplength=230).pack(
                    side="left", fill="x", expand=True, padx=(0, 8)
                )
                ctk.CTkButton(
                    row, text="Kopírovať", width=90,
                    command=lambda v=value: self._copy_to_clipboard(v),
                ).pack(side="right")
            else:
                ctk.CTkLabel(scroll, text=line, anchor="w", justify="left", wraplength=520).pack(
                    fill="x", pady=1
                )

        bottom_row = ctk.CTkFrame(dialog, fg_color="transparent")
        bottom_row.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(
            bottom_row, text="Otvoriť výstupný priečinok",
            command=lambda: os.startfile(output_root),
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(
            bottom_row, text="Zavrieť", width=90, fg_color="gray30", hover_color="gray25",
            command=dialog.destroy,
        ).pack(side="right")

        dialog.transient(self)
        dialog.lift()
        dialog.focus_force()

    def on_close(self):
        if self.worker and self.worker.is_alive():
            answer = messagebox.askyesnocancel(
                "Spracovanie beží",
                "Spracovanie ešte beží.\n\n"
                "Áno = schovať do lišty (pokračuje na pozadí)\n"
                "Nie = zastaviť spracovanie a ukončiť program\n"
                "(Zrušiť = vrátiť sa do programu)",
            )
            if answer is None:
                return
            if answer:
                self.minimize_to_tray()
                return
            self.cancel_event.set()
        self._stop_tray_icon()
        self.destroy()

    # ---------- systemova lista ----------

    def minimize_to_tray(self):
        if self.tray_icon is not None:
            self.withdraw()
            return
        self.withdraw()
        menu = pystray.Menu(
            pystray.MenuItem("Otvoriť FotoRotator", self._tray_restore, default=True),
            pystray.MenuItem("Ukončiť", self._tray_quit),
        )
        self.tray_icon = pystray.Icon("FotoRotator", _make_tray_image(), "FotoRotator", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _stop_tray_icon(self):
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

    def _tray_restore(self, icon=None, item=None):
        # Bezi vo vlakne pystray - spat do Tk hlavneho vlakna posielame cez
        # tu istu frontu, ktoru pouziva aj pracovne vlakno.
        self.queue.put(("tray_restore",))

    def _tray_quit(self, icon=None, item=None):
        self.queue.put(("tray_quit",))

    def _tray_notify(self, title: str, message: str):
        if self.tray_icon is None:
            return
        try:
            self.tray_icon.notify(message[:250], title)
        except Exception:
            pass  # nie vsetky Windows verzie/konfiguracie balonove upozornenia podporuju

    # ---------- vlakno spracovania ----------

    def _worker(self, folder: Path, install_action: str | None, use_api: bool):
        try:
            if install_action == "full":
                self.queue.put(("status", "Inštalujem Tesseract OCR…"))
                tesseract_install.install_full(log=lambda m: self.queue.put(("log", m)))
            elif install_action == "german":
                self.queue.put(("status", "Sťahujem nemecký jazykový balík…"))
                tesseract_install.install_german_only(
                    tesseract_check.find_tesseract_cmd(),
                    log=lambda m: self.queue.put(("log", m)),
                )
            use_ocr = tesseract_check.diagnose() == "ok"
            if install_action and not use_ocr:
                self.queue.put(("log", "Inštalácia OCR sa nepodarila — pokračujem bez OCR."))

            rotate.register_heif_support()

            def progress(done, total, message):
                self.queue.put(("progress", done, total, message))

            result = pipeline.run_job(folder, use_ocr, use_api, progress, self.cancel_event,
                                      model=self.selected_model)
            if result.get("cost_usd"):
                result["lifetime_cost_usd"] = config.add_total_cost_usd(result["cost_usd"])
            self.queue.put(("done", result))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    # ---------- spracovanie sprav z vlakna ----------

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.log(item[1])
                elif kind == "status":
                    self.status_label.configure(text=item[1])
                elif kind == "progress":
                    _, done, total, message = item
                    self.progress.set(done / total if total else 0)
                    self.status_label.configure(text=f"Fotka {done}/{total} — {message}")
                elif kind == "done":
                    result = item[1]
                    self.output_root = result["output_root"]
                    self._set_running(False)
                    self.progress.set(1)
                    was_cancelled = self.cancel_event.is_set()
                    self.status_label.configure(
                        text="Zastavené používateľom." if was_cancelled else "Hotovo!"
                    )
                    if "lifetime_cost_usd" in result:
                        self.total_cost_usd = result["lifetime_cost_usd"]
                        self._refresh_cost_label()
                    self.log("\n===== VÝSLEDOK =====")
                    self.log(result["summary"])
                    self.log(f"\nVýstup: {self.output_root}")
                    self.open_button.configure(state="normal")
                    if self.tray_icon is not None:
                        self._tray_notify("FotoRotator — Hotovo", result["summary"])
                    elif not was_cancelled:
                        self._show_result_dialog(result["summary"], self.output_root)
                elif kind == "error":
                    self._set_running(False)
                    self.status_label.configure(text="Chyba.")
                    self.log(f"CHYBA: {item[1]}")
                    if self.tray_icon is not None:
                        self._tray_notify("FotoRotator — Chyba", item[1])
                    else:
                        messagebox.showerror("Chyba", item[1])
                elif kind == "tray_restore":
                    self._stop_tray_icon()
                    self.deiconify()
                    self.state("normal")
                    self.lift()
                    self.focus_force()
                    self._reload_cost_from_disk()
                elif kind == "tray_quit":
                    if self.worker and self.worker.is_alive():
                        self.cancel_event.set()
                    self._stop_tray_icon()
                    self.destroy()
                    return
                elif kind == "api_key_ok":
                    key = item[1]
                    config.save_api_key(key)
                    self.saved_api_key = key
                    self.api_entry.delete(0, "end")
                    self.ai_var.set(True)
                    self.api_save_button.configure(state="normal", text="Uložiť kľúč")
                    self._refresh_api_status()
                    self.log("API kľúč overený a uložený — AI kontrola je zapnutá.")
                elif kind == "api_key_bad":
                    self.api_save_button.configure(state="normal", text="Uložiť kľúč")
                    messagebox.showerror(
                        "API kľúč",
                        f"Kľúč sa nepodarilo overiť:\n{item[1]}\n\nSkontroluj ho a skús znova."
                        f"\nKľúč získaš na: {API_KEYS_URL}",
                    )
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def run(initial_folder: Path | None = None, auto_start: bool = False):
    app = App(initial_folder=initial_folder, auto_start=auto_start)
    app.mainloop()
