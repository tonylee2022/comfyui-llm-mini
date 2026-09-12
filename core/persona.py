from __future__ import annotations

import unicodedata
from pathlib import Path

from .config import PERSONA_DIR, PERSONA_LOCAL_DIR


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


def _persona_path(directory: Path, persona_name: str) -> Path:
    name = validate_persona_name(persona_name)
    base = directory.resolve()
    path = (directory / f"{name}.txt").resolve()
    if path.parent != base:
        raise ValueError("Invalid persona name.")
    return path


def builtin_persona_path(persona_name: str) -> Path:
    return _persona_path(PERSONA_DIR, persona_name)


def local_persona_path(persona_name: str) -> Path:
    return _persona_path(PERSONA_LOCAL_DIR, persona_name)


def resolve_persona_path(persona_name: str) -> tuple[Path | None, str]:
    local_path = local_persona_path(persona_name)
    if local_path.is_file():
        return local_path, "local"
    builtin_path = builtin_persona_path(persona_name)
    if builtin_path.is_file():
        return builtin_path, "builtin"
    return None, "missing"


def persona_path(persona_name: str) -> Path:
    """兼容原读取接口；本地同名模板优先。"""
    path, _ = resolve_persona_path(persona_name)
    return path if path is not None else local_persona_path(persona_name)


def load_persona_text(persona_name: str, text: str | None = None) -> str:
    result = ""
    if text:
        result += "## Background knowledge:\n" + text + "\n\n"
    name = validate_persona_name(persona_name, allow_empty=True)
    if name:
        path, _ = resolve_persona_path(name)
        if path is None:
            raise FileNotFoundError(f"Persona was not found: {name}")
        result += path.read_text(encoding="utf-8")
    return result
