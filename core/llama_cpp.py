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
import tempfile
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
MODEL_PRESET_PATH = PRIVATE_RUNTIME_ROOT / "models-preset.ini"
MODEL_CONFIGS_OPTION = "model_configs"
UNLOAD_INHERIT = "inherit"
UNLOAD_AFTER_RUN = "after_run"
UNLOAD_KEEP_WARM = "keep_warm"
UNLOAD_IDLE = "idle"
UNLOAD_POLICIES = (UNLOAD_INHERIT, UNLOAD_AFTER_RUN, UNLOAD_KEEP_WARM, UNLOAD_IDLE)
MEMORY_AUTO = "auto"
MEMORY_KEEP = "keep"
MEMORY_POLICIES = (MEMORY_AUTO, MEMORY_KEEP)
MODEL_CONFIG_INTEGER_FIELDS = {
    "context_size": ("ctx-size", 1024, 1048576),
    "n_gpu_layers": ("n-gpu-layers", 0, 9999),
    "parallel": ("parallel", 1, 128),
    "batch_size": ("batch-size", 1, 8192),
    "ubatch_size": ("ubatch-size", 1, 8192),
    "threads": ("threads", 1, 1024),
    "image_max_tokens": ("image-max-tokens", 1, 65536),
}
MODEL_CONFIG_ENUM_FIELDS = {
    "flash_attn": ("flash-attn", {"auto", "on", "off"}),
    "cache_type_k": ("cache-type-k", {"f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"}),
    "cache_type_v": ("cache-type-v", {"f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"}),
}
MODEL_CONFIG_MODALITY_FIELDS = {
    "supports_image": "image",
    "supports_video": "video",
}
MODEL_CONFIG_MODALITY_VALUES = {"auto", "enabled", "disabled"}
MODEL_CONFIG_RESERVED_ARGS = {
    "api-key", "alias", "host", "port", "model", "model-url", "models-dir",
    "models-max", "models-preset", "models-autoload", "hf-repo", "hf-file", "hf-token",
}
MODEL_CONFIG_ADVANCED_ARGS = {
    "cache-prompt", "cache-reuse", "chat-template", "chat-template-file",
    "cont-batching", "kv-offload", "load-mode", "main-gpu", "no-cache-prompt",
    "no-cont-batching", "no-kv-offload", "no-mmproj", "rope-freq-base",
    "rope-freq-scale", "rope-scale", "rope-scaling", "split-mode", "swa-full",
    "tensor-split", "yarn-attn-factor", "yarn-beta-fast", "yarn-beta-slow",
    "yarn-ext-factor", "yarn-orig-ctx",
}


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


def _validate_model_id(model: Any) -> str:
    model = str(model or "").strip()
    if not model or len(model) > 512 or any(char in model for char in "\r\n[]"):
        raise ValueError("Invalid llama.cpp model ID for a model preset.")
    return model


def _normalize_advanced_model_args(value: Any) -> str:
    lines = []
    seen = set()
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if "=" not in line:
            raise ValueError("Advanced model parameters must use one 'name = value' entry per line.")
        name, raw_value = (part.strip() for part in line.split("=", 1))
        name = name.lstrip("-").lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            raise ValueError(f"Invalid advanced llama.cpp parameter name: {name}")
        standard_names = {spec[0] for spec in MODEL_CONFIG_INTEGER_FIELDS.values()} | {spec[0] for spec in MODEL_CONFIG_ENUM_FIELDS.values()}
        if name in MODEL_CONFIG_RESERVED_ARGS or name in standard_names:
            raise ValueError(f"The llama.cpp parameter cannot be overridden in advanced settings: {name}")
        if name not in MODEL_CONFIG_ADVANCED_ARGS:
            raise ValueError(f"Unsupported advanced llama.cpp model parameter: {name}")
        if name in seen:
            raise ValueError(f"Duplicate advanced llama.cpp parameter: {name}")
        if not raw_value or len(raw_value) > 2048 or any(ord(char) < 32 for char in raw_value):
            raise ValueError(f"Invalid value for advanced llama.cpp parameter: {name}")
        seen.add(name)
        lines.append(f"{name} = {raw_value}")
    if len(lines) > 64:
        raise ValueError("At most 64 advanced llama.cpp parameters are allowed per model.")
    return "\n".join(lines)


def normalize_llama_cpp_model_config(values: dict[str, Any] | None) -> dict[str, Any]:
    values = values or {}
    normalized: dict[str, Any] = {}
    for field, (_, minimum, maximum) in MODEL_CONFIG_INTEGER_FIELDS.items():
        raw = values.get(field)
        if raw in (None, ""):
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be an integer.") from exc
        if number < minimum or number > maximum:
            raise ValueError(f"{field} must be between {minimum} and {maximum}.")
        normalized[field] = number
    for field, (_, allowed) in MODEL_CONFIG_ENUM_FIELDS.items():
        raw = str(values.get(field, "") or "").strip().lower()
        if not raw or raw == "inherit":
            continue
        if raw not in allowed:
            raise ValueError(f"Invalid value for {field}.")
        normalized[field] = raw
    for field in MODEL_CONFIG_MODALITY_FIELDS:
        raw_value = values.get(field, "")
        if isinstance(raw_value, bool):
            raw = "enabled" if raw_value else "disabled"
        else:
            raw = str(raw_value or "").strip().lower()
        if not raw or raw in {"auto", "inherit"}:
            continue
        if raw not in MODEL_CONFIG_MODALITY_VALUES:
            raise ValueError(f"Invalid value for {field}.")
        normalized[field] = raw
    advanced = _normalize_advanced_model_args(values.get("advanced", ""))
    if advanced:
        normalized["advanced"] = advanced
    return normalized


def effective_model_input_modalities(
    model: str,
    record: dict[str, Any],
    configs: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """合并 router 上报模态与插件的单模型能力覆盖。"""
    architecture = record.get("architecture") or {}
    reported = architecture.get("input_modalities") or []
    modalities = {str(value).strip().lower() for value in reported if str(value).strip()}
    config = (configs if configs is not None else load_llama_cpp_model_configs()).get(model, {})
    for field, modality in MODEL_CONFIG_MODALITY_FIELDS.items():
        override = config.get(field)
        if override == "enabled":
            modalities.add(modality)
        elif override == "disabled":
            modalities.discard(modality)
    return [value for value in ("text", "image", "video", "audio") if value in modalities] + sorted(
        modalities.difference({"text", "image", "video", "audio"})
    )


def model_with_effective_modalities(
    record: dict[str, Any],
    configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    model = str(record.get("id") or record.get("model") or "")
    result = dict(record)
    architecture = dict(record.get("architecture") or {})
    reported = list(architecture.get("input_modalities") or [])
    architecture["reported_input_modalities"] = reported
    architecture["input_modalities"] = effective_model_input_modalities(model, record, configs)
    result["architecture"] = architecture
    return result


def load_llama_cpp_model_configs() -> dict[str, dict[str, Any]]:
    config = load_ini()
    if not config.has_option("llama_cpp", MODEL_CONFIGS_OPTION):
        return {}
    try:
        payload = json.loads(config.get("llama_cpp", MODEL_CONFIGS_OPTION, fallback="{}", raw=True))
        if not isinstance(payload, dict):
            return {}
        return {
            _validate_model_id(model): normalize_llama_cpp_model_config(values)
            for model, values in payload.items()
            if isinstance(values, dict)
        }
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}


def save_llama_cpp_model_config(model: Any, values: dict[str, Any] | None) -> dict[str, Any]:
    model = _validate_model_id(model)
    normalized = normalize_llama_cpp_model_config(values)
    configs = load_llama_cpp_model_configs()
    if normalized:
        configs[model] = normalized
    else:
        configs.pop(model, None)
    config = load_ini()
    if not config.has_section("llama_cpp"):
        config.add_section("llama_cpp")
    config["llama_cpp"][MODEL_CONFIGS_OPTION] = json.dumps(configs, ensure_ascii=False, separators=(",", ":"))
    save_ini(config)
    return normalized


def write_llama_cpp_model_preset(settings: LlamaCppSettings | None = None) -> Path:
    settings = settings or llama_cpp_settings()
    lines = [
        "version = 1",
        "",
        "[*]",
        f"ctx-size = {settings.context_size}",
        f"n-gpu-layers = {settings.n_gpu_layers}",
    ]
    for model, values in sorted(load_llama_cpp_model_configs().items()):
        lines.extend(["", f"[{model}]"])
        for field, (argument, _, _) in MODEL_CONFIG_INTEGER_FIELDS.items():
            if field in values:
                lines.append(f"{argument} = {values[field]}")
        for field, (argument, _) in MODEL_CONFIG_ENUM_FIELDS.items():
            if field in values:
                lines.append(f"{argument} = {values[field]}")
        if values.get("advanced"):
            lines.extend(values["advanced"].splitlines())
    MODEL_PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=MODEL_PRESET_PATH.parent, prefix=".models-preset.", suffix=".tmp", delete=False) as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, MODEL_PRESET_PATH)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return MODEL_PRESET_PATH


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
        "router_capable": bool(help_text and all(flag in help_text for flag in ("--models-dir", "--models-max", "--models-preset"))),
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
        self._maintenance = False

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
        if any(flag not in help_text for flag in ("--models-dir", "--models-max", "--models-preset")):
            raise LlamaCppError("The configured llama-server does not support router model presets. Please install a current llama.cpp build.")
        return executable_spec, help_text

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._maintenance:
                raise LlamaCppConflictError("llama.cpp runtime maintenance is in progress.")
            if self.running:
                return self.status(include_models=False)
            settings = llama_cpp_settings()
            executable_spec, help_text = self._validate_start(settings)
            executable = executable_spec.path
            preset_path = write_llama_cpp_model_preset(settings)
            self._port = self._free_port()
            self._token = secrets.token_urlsafe(32)
            self._log_tail.clear()
            args = [
                str(executable),
                "--host", "127.0.0.1",
                "--port", str(self._port),
                "--models-dir", str(settings.model_root),
                "--models-preset", str(preset_path),
                "--models-max", str(settings.models_max),
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

    def begin_maintenance(self) -> None:
        """在没有活动请求时进入维护状态并阻止新请求。"""
        with self._lock:
            if self._maintenance:
                raise LlamaCppConflictError("llama.cpp runtime maintenance is already in progress.")
            active = sum(self._active.values())
            if active:
                raise LlamaCppConflictError(
                    f"Cannot install or upgrade llama.cpp while {active} request(s) are active."
                )
            self._maintenance = True

    def end_maintenance(self) -> None:
        with self._lock:
            self._maintenance = False

    @contextlib.contextmanager
    def maintenance(self) -> Iterator[None]:
        """阻止新请求，并在没有活动请求时安全停止本项目的 router。"""
        self.begin_maintenance()
        try:
            self.stop()
            yield
        finally:
            self.end_maintenance()

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
        has_video: bool = False,
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
        modalities = effective_model_input_modalities(model, preview)
        if has_images and "image" not in modalities:
            raise LlamaCppError(f"The selected llama.cpp model does not advertise image input support: {model}")
        if has_video and "video" not in modalities:
            raise LlamaCppError(f"The selected llama.cpp model does not advertise video input support: {model}")
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
            maintenance = self._maintenance
        models: list[dict[str, Any]] = []
        error = ""
        if running and include_models:
            try:
                configs = load_llama_cpp_model_configs()
                models = [model_with_effective_modalities(model, configs) for model in self.models()]
            except Exception as exc:
                error = str(exc)
        return {
            "running": running,
            "pid": process_id,
            "base_url": base_url,
            "active_requests": active,
            "maintenance": maintenance,
            "settings": asdict(llama_cpp_settings()) | {"resolved_models_dir": str(llama_cpp_settings().model_root)},
            "model_configs": load_llama_cpp_model_configs(),
            "model_preset_path": str(MODEL_PRESET_PATH),
            "environment": check,
            "models": models,
            "error": error,
        }


RUNTIME = LlamaCppRuntime()
atexit.register(lambda: RUNTIME.stop(force=True))
