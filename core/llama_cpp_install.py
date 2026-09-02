from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from .llama_cpp import PRIVATE_RUNTIME_CONFIG, PRIVATE_RUNTIME_ROOT, RUNTIME, LlamaCppConflictError

try:
    from .. import llama_cpp_setup
except ImportError:
    import llama_cpp_setup


def _private_runtime_metadata() -> dict[str, str]:
    try:
        payload = json.loads(PRIVATE_RUNTIME_CONFIG.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        return {}
    return {
        key: str(payload.get(key, "") or "")
        for key in ("tag", "commit", "backend", "source")
    }


def _safe_error(exc: Exception) -> str:
    text = re.sub(
        r"(?i)(api[_ -]?key|token|authorization)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        str(exc),
    )
    replacements = {
        str(PRIVATE_RUNTIME_ROOT.parent): "[PLUGIN_RUNTIME]",
        str(Path.home()): "[HOME]",
    }
    for value, replacement in replacements.items():
        if value:
            text = text.replace(value, replacement)
    return text[-1200:]


class LlamaCppInstallManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "state": "idle",
            "phase": "idle",
            "message": "",
            "error": "",
            "result": {},
        }

    def plan(self, backend: str = "auto") -> dict[str, Any]:
        plan = llama_cpp_setup.install_runtime(
            backend,
            offline=False,
            force=True,
            dry_run=True,
            jobs=max(1, min(16, os.cpu_count() or 1)),
        )
        return {
            **plan,
            "current": _private_runtime_metadata(),
            "installed": (PRIVATE_RUNTIME_ROOT / "installed").is_dir(),
        }

    def status(self, backend: str = "auto") -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        if state.get("plan"):
            return state
        try:
            state["plan"] = self.plan(backend)
        except Exception as exc:
            state["plan"] = {"error": _safe_error(exc)}
        return state

    def start(self, backend: str = "auto") -> dict[str, Any]:
        if backend not in {"auto", "cuda", "vulkan", "metal", "cpu"}:
            raise ValueError("backend must be auto, cuda, vulkan, metal, or cpu.")
        plan = self.plan(backend)
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise LlamaCppConflictError("A llama.cpp installation or upgrade is already running.")
            RUNTIME.begin_maintenance()
            self._state = {
                "state": "running",
                "phase": "queued",
                "message": "llama.cpp 安装任务已进入队列。",
                "error": "",
                "result": {},
                "plan": plan,
            }
            try:
                self._thread = threading.Thread(
                    target=self._run,
                    args=(backend,),
                    daemon=True,
                    name="llm-mini-llama-install",
                )
                self._thread.start()
            except Exception:
                RUNTIME.end_maintenance()
                raise
        return self.status(backend)

    def _set_progress(self, phase: str, message: str) -> None:
        with self._lock:
            self._state["phase"] = phase
            self._state["message"] = message

    def _run(self, backend: str) -> None:
        try:
            RUNTIME.stop()
            result = llama_cpp_setup.install_runtime(
                backend,
                offline=False,
                force=True,
                dry_run=False,
                jobs=max(1, min(16, os.cpu_count() or 1)),
                progress=self._set_progress,
            )
            with self._lock:
                completed_plan = dict(self._state.get("plan") or {})
                completed_plan.update({
                    "current": _private_runtime_metadata(),
                    "installed": True,
                })
                self._state.update({
                    "state": "succeeded",
                    "phase": "complete",
                    "message": "llama.cpp 节点私有运行时安装完成。",
                    "error": "",
                    "result": result,
                    "plan": completed_plan,
                })
        except Exception as exc:
            with self._lock:
                self._state.update({
                    "state": "failed",
                    "phase": "failed",
                    "message": "llama.cpp 安装或升级失败，原运行时未被覆盖。",
                    "error": _safe_error(exc),
                    "result": {},
                })
        finally:
            RUNTIME.end_maintenance()


INSTALLER = LlamaCppInstallManager()
