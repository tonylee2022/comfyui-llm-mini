from __future__ import annotations

import atexit
import contextlib
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

import requests

from .config import load_ini, save_ini
from .interrupt import check_interrupted


LLAMA_CPP_PROVIDER = "llama_cpp"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_RUNTIME_ROOT = PACKAGE_ROOT / "runtime" / "llama_cpp"
PRIVATE_RUNTIME_CONFIG = PRIVATE_RUNTIME_ROOT / "runtime_config.json"
UNLOAD_INHERIT = "inherit"
UNLOAD_AFTER_RUN = "after_run"
UNLOAD_KEEP_WARM = "keep_warm"
UNLOAD_IDLE = "idle"
UNLOAD_POLICIES = (UNLOAD_INHERIT, UNLOAD_AFTER_RUN, UNLOAD_KEEP_WARM, UNLOAD_IDLE)
MEMORY_AUTO = "auto"
MEMORY_KEEP = "keep"
MEMORY_POLICIES = (MEMORY_AUTO, MEMORY_KEEP)


class LlamaCppError(RuntimeError):
    pass


class LlamaCppConflictError(LlamaCppError):
    pass


def _default_models_dir() -> Path:
    try:
        import folder_paths

        return (Path(folder_paths.models_dir) / "LLM").resolve()
    except Exception:
        return (Path(__file__).resolve().parents[3] / "ComfyUI" / "models" / "LLM").resolve()


@dataclass(frozen=True)
class LlamaCppSettings:
    executable: str = ""
    models_dir: str = ""
    context_size: int = 32768
    n_gpu_layers: int = 999
    models_max: int = 1
    default_unload_policy: str = UNLOAD_AFTER_RUN
    idle_unload_seconds: int = 600
    comfy_memory_policy: str = MEMORY_AUTO

    @property
    def model_root(self) -> Path:
        return Path(self.models_dir).expanduser().resolve() if self.models_dir else _default_models_dir()


@dataclass(frozen=True)
class LlamaCppExecutable:
    path: Path
    source: str
    library_dirs: tuple[Path, ...] = ()


def _private_runtime_spec() -> LlamaCppExecutable | None:
    if not PRIVATE_RUNTIME_CONFIG.is_file():
        return None
    try:
        payload = json.loads(PRIVATE_RUNTIME_CONFIG.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            return None

        def private_path(value: Any) -> Path:
            raw = Path(str(value or ""))
            resolved = raw.resolve() if raw.is_absolute() else (PRIVATE_RUNTIME_ROOT / raw).resolve()
            resolved.relative_to(PRIVATE_RUNTIME_ROOT.resolve())
            return resolved

        executable = private_path(payload.get("executable"))
        if not executable.is_file() or (os.name != "nt" and not os.access(executable, os.X_OK)):
            return None
        raw_dirs = payload.get("library_dirs") or [str(executable.parent)]
        library_dirs = tuple(path for path in (private_path(value) for value in raw_dirs) if path.is_dir())
        return LlamaCppExecutable(executable, "private", library_dirs)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def llama_cpp_settings() -> LlamaCppSettings:
    config = load_ini()
    section = "llama_cpp"

    def integer(name: str, default: int, minimum: int, maximum: int) -> int:
        value = config.getint(section, name, fallback=default) if config.has_section(section) else default
        return max(minimum, min(maximum, value))

    policy = config.get(section, "default_unload_policy", fallback=UNLOAD_AFTER_RUN).strip() if config.has_section(section) else UNLOAD_AFTER_RUN
    if policy not in UNLOAD_POLICIES[1:]:
        policy = UNLOAD_AFTER_RUN
    memory_policy = config.get(section, "comfy_memory_policy", fallback=MEMORY_AUTO).strip() if config.has_section(section) else MEMORY_AUTO
    if memory_policy not in MEMORY_POLICIES:
        memory_policy = MEMORY_AUTO
    return LlamaCppSettings(
        executable=config.get(section, "executable", fallback="").strip() if config.has_section(section) else "",
        models_dir=config.get(section, "models_dir", fallback="").strip() if config.has_section(section) else "",
        context_size=integer("context_size", 32768, 1024, 1048576),
        n_gpu_layers=integer("n_gpu_layers", 999, 0, 9999),
        models_max=integer("models_max", 1, 1, 32),
        default_unload_policy=policy,
        idle_unload_seconds=integer("idle_unload_seconds", 600, 10, 86400),
        comfy_memory_policy=memory_policy,
    )


def save_llama_cpp_settings(values: dict[str, Any]) -> LlamaCppSettings:
    current = llama_cpp_settings()
    executable = str(values.get("executable", current.executable) or "").strip()
    if executable:
        executable_path = Path(executable).expanduser()
        if not executable_path.is_absolute():
            raise ValueError("llama-server executable must be an absolute path or left empty to use PATH.")
        executable = str(executable_path.resolve())
    models_dir = str(values.get("models_dir", current.models_dir) or "").strip()
    if models_dir:
        model_path = Path(models_dir).expanduser()
        if not model_path.is_absolute():
            raise ValueError("llama.cpp models_dir must be an absolute path or left empty for ComfyUI/models/LLM.")
        models_dir = str(model_path.resolve())

    policy = str(values.get("default_unload_policy", current.default_unload_policy) or "").strip()
    if policy not in UNLOAD_POLICIES[1:]:
        raise ValueError("Invalid llama.cpp default unload policy.")
    memory_policy = str(values.get("comfy_memory_policy", current.comfy_memory_policy) or "").strip()
    if memory_policy not in MEMORY_POLICIES:
        raise ValueError("Invalid llama.cpp ComfyUI memory policy.")

    def integer(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(values.get(name, default))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer.") from exc
        if value < minimum or value > maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return value

    updated = LlamaCppSettings(
        executable=executable,
        models_dir=models_dir,
        context_size=integer("context_size", current.context_size, 1024, 1048576),
        n_gpu_layers=integer("n_gpu_layers", current.n_gpu_layers, 0, 9999),
        models_max=integer("models_max", current.models_max, 1, 32),
        default_unload_policy=policy,
        idle_unload_seconds=integer("idle_unload_seconds", current.idle_unload_seconds, 10, 86400),
        comfy_memory_policy=memory_policy,
    )
    config = load_ini()
    if not config.has_section("llama_cpp"):
        config.add_section("llama_cpp")
    for key, value in asdict(updated).items():
        config["llama_cpp"][key] = str(value)
    save_ini(config)
    return updated


def resolve_llama_server_spec(settings: LlamaCppSettings | None = None) -> LlamaCppExecutable | None:
    settings = settings or llama_cpp_settings()
    if settings.executable:
        candidate = Path(settings.executable)
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            path = candidate.resolve()
            return LlamaCppExecutable(path, "configured", (path.parent,))
    private = _private_runtime_spec()
    if private:
        return private
    found = shutil.which("llama-server") or (shutil.which("llama-server.exe") if os.name == "nt" else None)
    if found:
        path = Path(found).resolve()
        return LlamaCppExecutable(path, "PATH", (path.parent,))
    return None


def resolve_llama_server(settings: LlamaCppSettings | None = None) -> Path | None:
    spec = resolve_llama_server_spec(settings)
    return spec.path if spec else None


def _executable_environment(executable_spec: LlamaCppExecutable, token: str = "") -> dict[str, str]:
    environment = os.environ.copy()
    if token:
        environment["LLAMA_API_KEY"] = token
    library_path = os.pathsep.join(str(path) for path in executable_spec.library_dirs)
    if library_path:
        environment["PATH"] = library_path + os.pathsep + environment.get("PATH", "")
        if os.name != "nt":
            key = "DYLD_LIBRARY_PATH" if platform.system() == "Darwin" else "LD_LIBRARY_PATH"
            environment[key] = library_path + os.pathsep + environment.get(key, "")
    return environment


def _command_output(command: list[str], timeout: float = 5.0, *, env: dict[str, str] | None = None, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, env=env, cwd=cwd)
        return (result.stdout or result.stderr or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def environment_check() -> dict[str, Any]:
    settings = llama_cpp_settings()
    executable_spec = resolve_llama_server_spec(settings)
    executable = executable_spec.path if executable_spec else None
    release = platform.release().lower()
    is_wsl = "microsoft" in release or bool(os.environ.get("WSL_DISTRO_NAME"))
    nvidia_smi = shutil.which("nvidia-smi")
    nvcc = shutil.which("nvcc")
    cuda_home = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME") or ""
    if not cuda_home and Path("/usr/local/cuda").is_dir():
        cuda_home = "/usr/local/cuda"
    gpu_info = _command_output([nvidia_smi, "--query-gpu=name,compute_cap", "--format=csv,noheader"], 5) if nvidia_smi else ""
    executable_env = _executable_environment(executable_spec) if executable_spec else None
    version = _command_output([str(executable), "--version"], 5, env=executable_env, cwd=executable.parent).splitlines()[0] if executable else ""
    help_text = _command_output([str(executable), "--help"], 10, env=executable_env, cwd=executable.parent) if executable else ""
    model_root = settings.model_root
    gguf_count = 0
    mmproj_count = 0
    if model_root.is_dir():
        for path in model_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() != ".gguf":
                continue
            gguf_count += 1
            if path.name.lower().startswith("mmproj"):
                mmproj_count += 1
    return {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "is_wsl": is_wsl,
        "git": shutil.which("git") or "",
        "cmake": shutil.which("cmake") or "",
        "compiler": shutil.which("c++") or shutil.which("g++") or shutil.which("clang++") or shutil.which("cl") or "",
        "nvidia_smi": nvidia_smi or "",
        "nvidia_driver": bool(nvidia_smi),
        "nvcc": nvcc or "",
        "cuda_toolkit": cuda_home or (str(Path(nvcc).resolve().parents[1]) if nvcc else ""),
        "gpu_info": gpu_info,
        "executable": str(executable) if executable else "",
        "executable_source": executable_spec.source if executable_spec else "",
        "private_runtime_dir": str(PRIVATE_RUNTIME_ROOT),
        "private_runtime_installed": bool(_private_runtime_spec()),
        "version": version,
        "router_capable": bool(help_text and "--models-dir" in help_text and "--models-max" in help_text),
        "models_dir": str(model_root),
        "models_dir_exists": model_root.is_dir(),
        "gguf_count": gguf_count,
        "mmproj_count": mmproj_count,
    }


def install_help(backend: str = "auto", shell: str = "auto", ref: str = "master") -> dict[str, Any]:
    if backend not in {"auto", "cuda", "cpu"}:
        raise ValueError("backend must be auto, cuda, or cpu.")
    if shell not in {"auto", "bash", "powershell"}:
        raise ValueError("shell must be auto, bash, or powershell.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", ref) or ".." in ref:
        raise ValueError("ref contains unsupported characters.")
    check = environment_check()
    selected_shell = ("powershell" if os.name == "nt" else "bash") if shell == "auto" else shell
    warnings: list[str] = []
    if backend == "auto":
        if check.get("nvidia_driver") and check.get("nvcc") and check.get("cuda_toolkit"):
            backend = "cuda"
        elif check.get("nvidia_driver"):
            backend = "cuda"
        else:
            backend = "cpu"
    if backend == "cuda" and (not check.get("nvcc") or not check.get("cuda_toolkit")):
        warnings.append("NVIDIA CUDA build selected but the CUDA Toolkit or nvcc is missing. Install the Toolkit before running these commands.")
    if not check.get("git"):
        warnings.append("git was not found.")
    if not check.get("cmake"):
        warnings.append("cmake was not found.")
    if not check.get("compiler"):
        warnings.append("A C/C++ compiler was not found.")
    source = "llama.cpp"
    configure = "cmake -B build -DGGML_CUDA=ON" if backend == "cuda" else "cmake -B build"
    if selected_shell == "powershell":
        commands = [
            "git clone https://github.com/ggml-org/llama.cpp.git",
            f"Set-Location {source}",
            f"git checkout {ref}",
            configure,
            "cmake --build build --config Release --target llama-server",
            ".\\build\\bin\\Release\\llama-server.exe --version",
        ]
    else:
        commands = [
            "git clone https://github.com/ggml-org/llama.cpp.git",
            f"cd {source}",
            f"git checkout {ref}",
            configure,
            "cmake --build build --config Release --target llama-server -j",
            "./build/bin/llama-server --version",
        ]
    project_root = Path(__file__).resolve().parents[1]
    build_root = (Path.cwd() / source / "build" / "bin").resolve()
    executable_example = build_root / ("Release/llama-server.exe" if selected_shell == "powershell" else "llama-server")
    model_example = _default_models_dir()
    config_examples = [
        f"# Edit: {project_root / 'config.ini'}",
        "[llama_cpp]",
        f"executable = {executable_example}",
        f"models_dir = {model_example}",
    ]
    setup_script = project_root / "llama_cpp_setup.py"
    if selected_shell == "powershell":
        private_install_commands = [
            f'& "{sys.executable}" "{setup_script}" install-runtime --backend auto',
            f'& "{sys.executable}" "{setup_script}" check',
        ]
    else:
        private_install_commands = [
            f"{shlex.quote(sys.executable)} {shlex.quote(str(setup_script))} install-runtime --backend auto",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(setup_script))} check",
        ]
    return {
        "backend": backend,
        "shell": selected_shell,
        "ref": ref,
        "warnings": warnings,
        "commands": commands,
        "private_install_commands": private_install_commands,
        "config_examples": config_examples,
        "note": "Provider Manager only copies these commands. install-runtime changes files only when you explicitly run it.",
    }


class LlamaCppRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._port = 0
        self._token = ""
        self._log_tail: deque[str] = deque(maxlen=80)
        self._active: dict[str, int] = {}
        self._model_locks: dict[str, threading.Lock] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._deferred_policies: dict[str, set[str]] = {}
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def base_url(self) -> str:
        if not self.running or not self._port:
            return ""
        return f"http://127.0.0.1:{self._port}/"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _read_logs(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            self._log_tail.append(line.rstrip())

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _validate_start(self, settings: LlamaCppSettings) -> tuple[LlamaCppExecutable, str]:
        executable_spec = resolve_llama_server_spec(settings)
        if not executable_spec:
            raise LlamaCppError("llama-server was not found. Run: python3 llama_cpp_setup.py print-install")
        model_root = settings.model_root
        if not model_root.is_dir():
            raise LlamaCppError(f"llama.cpp model directory does not exist: {model_root}")
        help_text = _command_output(
            [str(executable_spec.path), "--help"], 10,
            env=_executable_environment(executable_spec), cwd=executable_spec.path.parent,
        )
        if "--models-dir" not in help_text or "--models-max" not in help_text:
            raise LlamaCppError("The configured llama-server does not support router mode. Please install a current llama.cpp build.")
        return executable_spec, help_text

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.running:
                return self.status(include_models=False)
            settings = llama_cpp_settings()
            executable_spec, help_text = self._validate_start(settings)
            executable = executable_spec.path
            self._port = self._free_port()
            self._token = secrets.token_urlsafe(32)
            self._log_tail.clear()
            args = [
                str(executable),
                "--host", "127.0.0.1",
                "--port", str(self._port),
                "--models-dir", str(settings.model_root),
                "--models-max", str(settings.models_max),
                "--ctx-size", str(settings.context_size),
                "--n-gpu-layers", str(settings.n_gpu_layers),
                "--no-webui",
                "--jinja",
            ]
            if "--fit" in help_text:
                args.extend(["--fit", "on"])
            popen_kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
                "cwd": str(executable.parent),
                "env": self._runtime_environment(executable_spec),
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True
            try:
                self._process = subprocess.Popen(args, **popen_kwargs)
            except OSError as exc:
                self._process = None
                raise LlamaCppError(f"Failed to start llama-server: {exc}") from exc
            self._reader = threading.Thread(target=self._read_logs, args=(self._process,), daemon=True, name="llm-mini-llama-log")
            self._reader.start()

        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            check_interrupted()
            with self._lock:
                process = self._process
                if process is None or process.poll() is not None:
                    details = self._safe_log_tail()
                    self._clear_process()
                    raise LlamaCppError(f"llama-server exited during startup. {details}")
                url = self.base_url + "health"
            try:
                response = requests.get(url, headers=self._headers(), timeout=2)
                if response.status_code == 200:
                    models_response = requests.get(self.base_url + "models", headers=self._headers(), timeout=5)
                    models_payload = models_response.json() if models_response.status_code == 200 else None
                    if isinstance(models_payload, dict) and isinstance(models_payload.get("data"), list):
                        return self.status(include_models=False)
            except requests.RequestException:
                pass
            time.sleep(0.25)
        self.stop(force=True)
        raise LlamaCppError("llama-server did not become ready within 45 seconds.")

    def _runtime_environment(self, executable_spec: LlamaCppExecutable) -> dict[str, str]:
        return _executable_environment(executable_spec, self._token)

    def _safe_log_tail(self) -> str:
        text = " | ".join(list(self._log_tail)[-8:])
        if self._token:
            text = text.replace(self._token, "[REDACTED]")
        return text[-2000:]

    def _clear_process(self) -> None:
        self._process = None
        self._port = 0
        self._token = ""
        self._active.clear()
        self._deferred_policies.clear()
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()

    def stop(self, force: bool = False) -> None:
        with self._lock:
            active = sum(self._active.values())
            if active and not force:
                raise LlamaCppConflictError(f"Cannot stop llama-server while {active} request(s) are active.")
            process = self._process
            if process is None:
                self._clear_process()
                return
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            try:
                if process.poll() is None:
                    if os.name == "nt":
                        process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True,
                                timeout=10,
                                check=False,
                            )
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
            except ProcessLookupError:
                pass
            finally:
                self._clear_process()

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        self.start()
        url = self.base_url + path.lstrip("/")
        try:
            response = requests.request(method, url, headers=self._headers(), timeout=kwargs.pop("timeout", 30), **kwargs)
        except requests.RequestException as exc:
            raise LlamaCppError(f"llama-server request failed: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
                error = payload.get("error", payload) if isinstance(payload, dict) else payload
                message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            except ValueError:
                message = response.text[:1000]
            if response.status_code == 409:
                raise LlamaCppConflictError(message)
            raise LlamaCppError(f"llama-server HTTP {response.status_code}: {message}")
        return response

    def models(self, reload: bool = False) -> list[dict[str, Any]]:
        response = self._request("GET", "models" + ("?reload=1" if reload else ""), timeout=30)
        payload = response.json()
        data = payload.get("data", []) if isinstance(payload, dict) else []
        return [item for item in data if isinstance(item, dict) and item.get("id")]

    def _model(self, model: str, reload: bool = False) -> dict[str, Any] | None:
        return next((item for item in self.models(reload=reload) if item.get("id") == model), None)

    def _maybe_release_comfy_memory(self, record: dict[str, Any], policy: str) -> None:
        if policy != MEMORY_AUTO:
            return
        path_value = str(record.get("path", "") or "")
        path = Path(path_value) if path_value else None
        required = 0
        try:
            if path and path.is_file():
                required = path.stat().st_size
                for candidate in path.parent.iterdir():
                    if candidate.is_file() and candidate.name.lower().startswith("mmproj") and candidate.suffix.lower() == ".gguf":
                        required += candidate.stat().st_size
            if required <= 0:
                return
            import torch

            if not torch.cuda.is_available():
                return
            free_bytes, _ = torch.cuda.mem_get_info()
            threshold = int(required * 1.15) + 1024**3
            if free_bytes >= threshold:
                return
            import comfy.model_management as model_management

            model_management.unload_all_models()
            model_management.soft_empty_cache()
        except Exception:
            return

    def load_model(self, model: str, memory_policy: str | None = None) -> dict[str, Any]:
        model = str(model or "").strip()
        if not model:
            raise ValueError("Model ID cannot be empty.")
        with self._lock:
            model_lock = self._model_locks.setdefault(model, threading.Lock())
        with model_lock:
            return self._load_model_locked(model, memory_policy)

    def _load_model_locked(self, model: str, memory_policy: str | None = None) -> dict[str, Any]:
        record = self._model(model, reload=True)
        if record is None:
            raise LlamaCppError(f"llama.cpp model was not found: {model}")
        status = str((record.get("status") or {}).get("value", ""))
        if status in {"loaded", "sleeping"}:
            return record
        settings = llama_cpp_settings()
        self._maybe_release_comfy_memory(record, memory_policy or settings.comfy_memory_policy)
        self._request("POST", "models/load", json={"model": model}, timeout=30)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            check_interrupted()
            record = self._model(model)
            if record is None:
                raise LlamaCppError(f"llama.cpp model disappeared while loading: {model}")
            status_info = record.get("status") or {}
            status = str(status_info.get("value", ""))
            if status in {"loaded", "sleeping"}:
                return record
            if status == "unloaded" and status_info.get("failed"):
                raise LlamaCppError(f"llama.cpp failed to load model {model} (exit code {status_info.get('exit_code', 'unknown')}).")
            time.sleep(0.5)
        raise LlamaCppError(f"Timed out waiting for llama.cpp model to load: {model}")

    def unload_model(self, model: str, manual: bool = True) -> None:
        model = str(model or "").strip()
        if not model:
            raise ValueError("Model ID cannot be empty.")
        with self._lock:
            if manual and self._active.get(model, 0):
                raise LlamaCppConflictError(f"Cannot unload {model} while requests are active.")
            timer = self._timers.pop(model, None)
            if timer:
                timer.cancel()
        self._request("POST", "models/unload", json={"model": model}, timeout=30)

    def _idle_unload(self, model: str) -> None:
        with self._lock:
            self._timers.pop(model, None)
            if self._active.get(model, 0):
                return
        try:
            self.unload_model(model, manual=False)
        except Exception:
            pass

    @contextlib.contextmanager
    def model_session(
        self,
        model: str,
        unload_policy: str = UNLOAD_INHERIT,
        has_images: bool = False,
        memory_policy: str | None = None,
    ) -> Iterator[tuple[str, str]]:
        if unload_policy not in UNLOAD_POLICIES:
            raise ValueError("Invalid llama.cpp unload policy.")
        settings = llama_cpp_settings()
        effective_policy = settings.default_unload_policy if unload_policy == UNLOAD_INHERIT else unload_policy
        with self._lock:
            timer = self._timers.pop(model, None)
            if timer:
                timer.cancel()
        preview = self._model(model, reload=True)
        if preview is None:
            raise LlamaCppError(f"llama.cpp model was not found: {model}")
        modalities = ((preview.get("architecture") or {}).get("input_modalities") or [])
        if has_images and "image" not in modalities:
            raise LlamaCppError(f"The selected llama.cpp model does not advertise image input support: {model}")
        with self._lock:
            self._active[model] = self._active.get(model, 0) + 1
        try:
            self.load_model(model, memory_policy)
            with self._lock:
                base_url = self.base_url + "v1/"
                token = self._token
            yield base_url, token
        finally:
            should_unload = False
            with self._lock:
                self._deferred_policies.setdefault(model, set()).add(effective_policy)
                remaining = max(0, self._active.get(model, 1) - 1)
                if remaining:
                    self._active[model] = remaining
                else:
                    self._active.pop(model, None)
                    policies = self._deferred_policies.pop(model, set())
                    if UNLOAD_AFTER_RUN in policies:
                        should_unload = True
                    elif UNLOAD_IDLE in policies:
                        timer = threading.Timer(settings.idle_unload_seconds, self._idle_unload, args=(model,))
                        timer.daemon = True
                        self._timers[model] = timer
                        timer.start()
            if should_unload:
                try:
                    self.unload_model(model, manual=False)
                except Exception:
                    pass

    def status(self, include_models: bool = True) -> dict[str, Any]:
        check = environment_check()
        with self._lock:
            running = self.running
            process_id = self._process.pid if running and self._process else None
            active = dict(self._active)
            base_url = self.base_url
        models: list[dict[str, Any]] = []
        error = ""
        if running and include_models:
            try:
                models = self.models()
            except Exception as exc:
                error = str(exc)
        return {
            "running": running,
            "pid": process_id,
            "base_url": base_url,
            "active_requests": active,
            "settings": asdict(llama_cpp_settings()) | {"resolved_models_dir": str(llama_cpp_settings().model_root)},
            "environment": check,
            "models": models,
            "error": error,
        }


RUNTIME = LlamaCppRuntime()
atexit.register(lambda: RUNTIME.stop(force=True))
