"""Ukladanie nastaveni - config.json v %APPDATA%\\FotoRotator.

API kluc sa uklada zasifrovany cez Windows DPAPI, viazany na ucet
prihlaseneho pouzivatela (rovnaky princip ako StrategyScribe, ale cez
ctypes - bez zavislosti na pywin32). Kluc v cistom texte sa na disk
nikdy nezapisuje.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path

_PROTECTED_PREFIX = "dpapi:"

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "FotoRotator"
CONFIG_PATH = CONFIG_DIR / "config.json"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> _DATA_BLOB:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _bytes_from_blob(blob: _DATA_BLOB) -> bytes:
    data = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return data


def _protect(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    blob_in = _blob_from_bytes(plaintext.encode("utf-8"))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), "FotoRotator", None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError("DPAPI sifrovanie zlyhalo")
    return _PROTECTED_PREFIX + base64.b64encode(_bytes_from_blob(blob_out)).decode("ascii")


def _unprotect(value: str) -> str:
    if not value or not value.startswith(_PROTECTED_PREFIX):
        return value or ""
    blob_in = _blob_from_bytes(base64.b64decode(value[len(_PROTECTED_PREFIX):]))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        return ""  # napr. kluc patri inemu pouzivatelovi/PC
    return _bytes_from_blob(blob_out).decode("utf-8")


def _read_raw() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_raw(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def load() -> dict:
    config = {"api_key": "", "total_cost_usd": 0.0, "model": "", "quality": ""}
    config.update(_read_raw())
    config["api_key"] = _unprotect(config.get("api_key", ""))
    config["total_cost_usd"] = float(config.get("total_cost_usd", 0.0))
    return config


def save_api_key(api_key: str):
    config = _read_raw()
    config["api_key"] = _protect(api_key) if api_key else ""
    _write_raw(config)


def save_model(model_id: str):
    config = _read_raw()
    config["model"] = model_id
    _write_raw(config)


def save_quality(quality_key: str):
    config = _read_raw()
    config["quality"] = quality_key
    _write_raw(config)


def add_total_cost_usd(amount: float) -> float:
    """Pripocita amount k celkovej minutej sume za AI kontrolu (ulozenej
    lokalne v config.json) a vrati novy celkovy sucet."""
    config = _read_raw()
    total = float(config.get("total_cost_usd", 0.0)) + amount
    config["total_cost_usd"] = total
    _write_raw(config)
    return total
