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
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw

from . import config, pipeline, rotate, tesseract_check, tesseract_install

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

API_KEYS_URL = "https://console.anthropic.com/settings/keys"


def _make_tray_image() -> Image.Image:
    """Jednoducha ikona pre listu - modry stvorec s bielou sipkou otacania,
    kreslena cez Pillow (ziadny externy subor)."""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([3, 3, size - 3, size - 3], radius=14, fill=(30, 110, 220, 255))
    draw.arc([15, 15, size - 15, size - 15], start=25, end=300, fill=(255, 255, 255, 255), width=6)
    draw.polygon([(size - 17, 17), (size - 6, 24), (size - 21, 33)], fill=(255, 255, 255, 255))
    return image


class App(ctk.CTk):
    def __init__(self, initial_folder: Path | None = None, auto_start: bool = False):
        super().__init__()
        self.title("FotoRotator")
        self.geometry("760x680")
        self.minsize(660, 580)

        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.output_root: Path | None = None
        self.saved_api_key = config.load().get("api_key", "")

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
        self._refresh_api_status()

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
        self.bind("<Unmap>", self._on_unmap)
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

    def _set_running(self, running: bool):
        state = "disabled" if running else "normal"
        for widget in (self.start_button, self.pick_button, self.folder_entry,
                       self.api_entry, self.api_save_button, self.api_delete_button,
                       self.ai_checkbox):
            widget.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    # ---------- akcie ----------

    def pick_folder(self):
        selected = filedialog.askdirectory(title="Vyber priečinok s fotkami z merania")
        if selected:
            self.folder_var.set(selected)

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
        self.log(f"Štart: {folder}" + ("  (AI kontrola zapnutá)" if use_api else "  (offline režim)"))

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

    def _on_unmap(self, event):
        # Fici aj pri minimalizovani cez OS tlacidlo na titulnom pruhu, nielen
        # cez nase tlacidlo "Skryt do listy".
        if event.widget is self and self.state() == "iconic":
            self.minimize_to_tray()

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

            result = pipeline.run_job(folder, use_ocr, use_api, progress, self.cancel_event)
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
                    self.log("\n===== VÝSLEDOK =====")
                    self.log(result["summary"])
                    self.log(f"\nVýstup: {self.output_root}")
                    self.open_button.configure(state="normal")
                    if self.tray_icon is not None:
                        self._tray_notify("FotoRotator — Hotovo", result["summary"])
                    elif not was_cancelled:
                        messagebox.showinfo("Hotovo", f"{result['summary']}\n\nVýstup:\n{self.output_root}")
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
