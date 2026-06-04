from __future__ import annotations

import unicodedata
from pathlib import Path

from .config import PERSONA_DIR


def validate_persona_name(persona_name: str, allow_empty: bool = False) -> str:
    name = str(persona_name or "").strip()
    if not name:
        if allow_empty:
            return ""
        raise ValueError("Persona name cannot be empty.")
    if name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Invalid persona name.")
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise ValueError("Invalid persona name.")
    return name


def persona_path(persona_name: str) -> Path:
    name = validate_persona_name(persona_name)
    base = PERSONA_DIR.resolve()
    path = (PERSONA_DIR / f"{name}.txt").resolve()
    if path.parent != base:
        raise ValueError("Invalid persona name.")
    return path


def load_persona_text(persona_name: str, text: str | None = None) -> str:
    result = ""
    if text:
        result += "## Background knowledge:\n" + text + "\n\n"
    name = validate_persona_name(persona_name, allow_empty=True)
    path = persona_path(name) if name else None
    if path and path.exists():
        result += path.read_text(encoding="utf-8")
    return result
