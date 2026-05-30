from __future__ import annotations

from .config import PERSONA_DIR


def load_persona_text(persona_name: str, text: str | None = None) -> str:
    result = ""
    if text:
        result += "## Background knowledge:\n" + text + "\n\n"
    path = PERSONA_DIR / f"{persona_name}.txt"
    if persona_name and path.exists():
        result += path.read_text(encoding="utf-8")
    return result
