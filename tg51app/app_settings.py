"""settings.json next to the app, with JSONC comments stripped on load."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SETTINGS_NAME = "settings.json"
SAMPLE_NAME = "settings.sample.json"
ENV_SETTINGS = "TG51_SETTINGS"
ENV_CASES = "TG51_CASES"

# Checked after converting temperature to °C and pressure to kPa.
# Voltage limits apply to the magnitude, so -300 and 300 are the same.
# m_reading applies to every electrometer reading. null removes a limit.
DEFAULT_VALID_RANGES = {
    "temperature_c": {"min": 17.0, "max": 27.0},
    "pressure_kpa": {"min": 91.0, "max": 111.0},
    "n_dw": {"min": 1.0, "max": 20.0},
    "p_elec": {"min": 0.98, "max": 1.02},
    "voltage_reference": {"min": 100.0, "max": 500.0},
    "voltage_reduced": {"min": 50.0, "max": 400.0},
    "mu": {"min": 50.0, "max": 500.0},
    "tissue_correction": {"min": 0.97, "max": 1.03},
    "m_reading": {"min": 0.01, "max": 100.0},
    "measured_pdd10": {"min": 62.7, "max": 89.0},
    "clinical_pdd10": {"min": 50.0, "max": 90.0},
    "clinical_pdd": {"min": 50.0, "max": 110.0},
    "i_50": {"min": 1.0, "max": 25.0},
    "k_ecal": {"min": 0.85, "max": 0.97},
}
DEFAULT_HISTORY_WARN_PERCENT = 5.0
DEFAULT_DOSE_DECIMALS = 2

# Institution reference setup. Photons are measured at this field size and depth.
DEFAULT_SETUP = {
    "voltage_reference": 300,
    "voltage_reduced": 150,
    "mu": 100,
    "tissue_correction": 1.0,
    "field_size": "10x10",
    "measurement_depth_cm": 10.0,
}

DEFAULT_SETTINGS = {
    "Institution": "",
    "Font": {"family": "", "size": 0},
    "PreviousCalibrationWarnPercent": DEFAULT_HISTORY_WARN_PERCENT,
    "DoseDecimalPlaces": DEFAULT_DOSE_DECIMALS,
    "Setup": DEFAULT_SETUP,
    "ValidRanges": DEFAULT_VALID_RANGES,
    "Users": [],
    "IonChambers": [],
    "Electrometers": [],
    "Machines": [],
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] not in ("", "-c") else Path()
    try:
        argv0 = argv0.expanduser().resolve()
    except OSError:
        argv0 = Path()
    if argv0.suffix.lower() == ".exe" and argv0.is_file():
        return argv0.parent
    pkg = Path(__file__).resolve().parent
    root = pkg.parent
    if root.name.lower() in ("site-packages", "dist-packages"):
        return argv0.parent if argv0.is_file() else Path.cwd()
    return root


def settings_path() -> Path:
    override = os.environ.get(ENV_SETTINGS, "").strip()
    if override:
        return Path(override)
    return app_dir() / SETTINGS_NAME


def cases_dir() -> Path:
    override = os.environ.get(ENV_CASES, "").strip()
    if override:
        return Path(override)
    return app_dir() / "_cases"


def strip_jsonc(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    in_line = False
    in_block = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch in "\r\n":
                in_line = False
                out.append(ch)
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def default_settings() -> dict:
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def load_settings(path: str | Path | None = None) -> dict:
    """Load settings. A missing file falls back to settings.sample.json beside it, then to defaults."""
    file = Path(path) if path else settings_path()
    if not file.is_file():
        sample = file.with_name(SAMPLE_NAME)
        file = sample if sample.is_file() else None
    if file is None or not file.is_file():
        return default_settings()
    text = strip_jsonc(file.read_text(encoding="utf-8"))
    data = json.loads(text) if text.strip() else {}
    return data if isinstance(data, dict) else default_settings()


def save_settings(data: dict, path: str | Path | None = None) -> Path:
    file = Path(path) if path else settings_path()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return file


def ensure_settings_file() -> Path:
    """Copy the sample into settings.json the first time the app is launched."""
    path = settings_path()
    if path.is_file():
        return path
    sample = path.with_name(SAMPLE_NAME)
    if not sample.is_file():
        sample = app_dir() / SAMPLE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if sample.is_file():
        path.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        save_settings(default_settings(), path)
    return path


def font_settings(data: dict | None = None) -> dict:
    cfg = (data if data is not None else load_settings()).get("Font")
    cfg = cfg if isinstance(cfg, dict) else {}
    try:
        size = int(cfg.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size < 0:
        size = 0
    return {"family": str(cfg.get("family") or ""), "size": size}


def institution_name(data: dict | None = None) -> str:
    return str((data if data is not None else load_settings()).get("Institution") or "").strip()


def _bound(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def valid_ranges(data: dict | None = None) -> dict[str, dict]:
    """Merge ValidRanges over the defaults. A null entry removes that field's check."""
    source = data if data is not None else load_settings()
    merged = {key: dict(bounds) for key, bounds in DEFAULT_VALID_RANGES.items()}
    cfg = source.get("ValidRanges") if isinstance(source, dict) else None
    if not isinstance(cfg, dict):
        return merged
    for key, value in cfg.items():
        if value is None:
            merged.pop(key, None)
            continue
        if not isinstance(value, dict):
            continue
        current = dict(merged.get(key) or {})
        for end in ("min", "max"):
            if end not in value:
                continue
            try:
                current[end] = _bound(value[end])
            except (TypeError, ValueError):
                continue
        merged[key] = current
    return merged


def history_warn_percent(data: dict | None = None) -> float:
    source = data if data is not None else load_settings()
    try:
        value = float(source.get("PreviousCalibrationWarnPercent", DEFAULT_HISTORY_WARN_PERCENT))
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_WARN_PERCENT
    if value < 0:
        return DEFAULT_HISTORY_WARN_PERCENT
    return value


def dose_decimal_places(value) -> int:
    """Digits after the decimal for dose shown outside the Calculations panel."""
    try:
        places = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DOSE_DECIMALS
    if places < 0 or places > 6:
        return DEFAULT_DOSE_DECIMALS
    return places


def window_state_path(settings_file: str | Path) -> Path:
    return Path(settings_file).with_name("window_state.json")


def load_window_states(settings_file: str | Path) -> dict:
    path = window_state_path(settings_file)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_window_state(settings_file: str | Path, name: str) -> dict | None:
    item = load_window_states(settings_file).get(name)
    return item if isinstance(item, dict) else None


def save_window_state(settings_file: str | Path, name: str, state: dict) -> None:
    path = window_state_path(settings_file)
    states = load_window_states(settings_file)
    states[name] = state
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(states, indent=2) + "\n", encoding="utf-8")
