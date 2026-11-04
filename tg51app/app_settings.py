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

DEFAULT_SETTINGS = {
    "Institution": "",
    "Font": {"family": "", "size": 0},
    "Users": [],
    "IonChambers": [],
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
