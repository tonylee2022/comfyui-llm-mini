from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core.llama_cpp import PRIVATE_RUNTIME_CONFIG, PRIVATE_RUNTIME_ROOT, environment_check, install_help


LLAMA_CPP_TAG = "b10436"
LLAMA_CPP_COMMIT = "6fed9f6ff7a603b124cb8c5864fca6ea879f9f99"
RELEASE_BASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_TAG}"


@dataclass(frozen=True)
class Asset:
    filename: str
    sha256: str

    @property
    def url(self) -> str:
        return f"{RELEASE_BASE_URL}/{self.filename}"


ASSETS = {
    "windows-cuda12": (
        Asset("llama-b10436-bin-win-cuda-12.4-x64.zip", "063423954c7aec2cafa09b8caee9dfddd111a91ca46cbb59cc0f743334371c32"),
        Asset("cudart-llama-bin-win-cuda-12.4-x64.zip", "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"),
    ),
    "windows-cuda13": (
        Asset("llama-b10436-bin-win-cuda-13.3-x64.zip", "679428e6c243590bac14a113bd4147401639dee5483097446caa5a5eddf5d3aa"),
        Asset("cudart-llama-bin-win-cuda-13.3-x64.zip", "1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e"),
    ),
    "windows-cpu": (Asset("llama-b10436-bin-win-cpu-x64.zip", "eebe233f29bd89a6c3c03a1e92c8b97a216a67977f4742aef28005c784b1f02c"),),
    "linux-vulkan-x86_64": (Asset("llama-b10436-bin-ubuntu-vulkan-x64.tar.gz", "ecc51b5052498c9a41abb24d686165013658c12902230461175ac33c0de3090f"),),
    "linux-cpu-x86_64": (Asset("llama-b10436-bin-ubuntu-x64.tar.gz", "ca375784486e71640f984289461c2a4c46a246c9328c0765af2be09bb00d9539"),),
    "linux-vulkan-aarch64": (Asset("llama-b10436-bin-ubuntu-vulkan-arm64.tar.gz", "b7091af7320faccf001c91a77f74c8ab7f2b9334863f5095d24ca754786aae2"),),
    "linux-cpu-aarch64": (Asset("llama-b10436-bin-ubuntu-arm64.tar.gz", "960f90e69565be7ef135bced730340d3e6a30a0f1c7826d687626b0e0e383d0c"),),
    "darwin-metal-arm64": (Asset("llama-b10436-bin-macos-arm64.tar.gz", "abd65dbfd770bde9ea17acc73521919b69073e0873d4301b8678a88e7c423fcc"),),
    "darwin-cpu-x86_64": (Asset("llama-b10436-bin-macos-x64.tar.gz", "36138386bc4fcc99305309b16228b358ea801731af34e2fb50cd5d93d67cd6c3"),),
}


def _architecture() -> str:
    value = platform.machine().lower()
    if value in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "aarch64"
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(asset: Asset, offline: bool) -> Path:
    cache = PRIVATE_RUNTIME_ROOT / ".downloads" / LLAMA_CPP_TAG
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / asset.filename
    if target.is_file() and _sha256(target) == asset.sha256:
        return target
    if offline:
        raise RuntimeError(f"离线缓存缺失或校验失败: {target}")
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(asset.url, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
            output.flush()
            os.fsync(output.fileno())
        if _sha256(partial) != asset.sha256:
            raise RuntimeError(f"下载文件 SHA256 校验失败: {asset.filename}")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _safe_destination(root: Path, name: str) -> Path:
    posix = PurePosixPath(name.replace("\\", "/"))
    if posix.is_absolute() or ".." in posix.parts:
        raise RuntimeError(f"安装包包含不安全路径: {name}")
    destination = (root / Path(*posix.parts)).resolve()
    destination.relative_to(root.resolve())
    return destination


def _extract(archive: Path, destination: Path) -> None:
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = _safe_destination(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return
    with tarfile.open(archive, "r:*") as bundle:
        for member in bundle.getmembers():
            target = _safe_destination(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError(f"无法读取安装包成员: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
            else:
                raise RuntimeError(f"安装包包含不支持的链接或设备文件: {member.name}")


def _find_server(root: Path) -> Path:
    names = {"llama-server.exe", "llama-server"}
    matches = sorted(path for path in root.rglob("*") if path.is_file() and path.name in names)
    if not matches:
        raise RuntimeError("安装包中没有找到 llama-server")
    server = matches[0]
    if os.name != "nt":
        server.chmod(server.stat().st_mode | 0o755)
    return server


def _library_dirs(root: Path) -> list[Path]:
    suffixes = {".dll", ".so", ".dylib"}
    return sorted({path.parent for path in root.rglob("*") if path.is_file() and (path.suffix.lower() in suffixes or ".so." in path.name)})


def _runtime_env(library_dirs: list[Path]) -> dict[str, str]:
    env = os.environ.copy()
    variable = "PATH" if os.name == "nt" else ("DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH")
    prefix = os.pathsep.join(str(path) for path in library_dirs)
    env[variable] = prefix + (os.pathsep + env[variable] if prefix and env.get(variable) else "")
    return env


def _validate_runtime(server: Path, backend: str, library_dirs: list[Path]) -> None:
    env = _runtime_env(library_dirs)
    outputs: dict[str, str] = {}
    for flag, timeout in (("--version", 15), ("--list-devices", 30), ("--help", 15)):
        result = subprocess.run([str(server), flag], capture_output=True, text=True, timeout=timeout, check=False, env=env, cwd=server.parent)
        outputs[flag] = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            raise RuntimeError(f"llama-server {flag} 验证失败: {outputs[flag][-500:]}")
    if "--models-dir" not in outputs["--help"] or "--models-max" not in outputs["--help"]:
        raise RuntimeError("该 llama-server 不支持所需的多模型 router API")
    devices = outputs["--list-devices"].lower()
    if backend == "cuda" and "cuda" not in devices:
        raise RuntimeError("CUDA 运行时未检测到 CUDA 设备")
    if backend == "vulkan" and "vulkan" not in devices:
        raise RuntimeError("Vulkan 运行时未检测到 Vulkan 设备")


def _activate(payload: Path, server: Path, library_dirs: list[Path], backend: str, source: str, force: bool) -> dict[str, str]:
    installed = PRIVATE_RUNTIME_ROOT / "installed"
    if installed.exists() and not force:
        raise RuntimeError(f"私有运行时已存在: {installed}；如需替换请加 --force")
    server_relative = server.relative_to(payload)
    library_relatives = [path.relative_to(payload) for path in library_dirs]
    backup = PRIVATE_RUNTIME_ROOT / ".installed.backup"
    if backup.exists():
        shutil.rmtree(backup)
    if installed.exists():
        os.replace(installed, backup)
    try:
        os.replace(payload, installed)
        config = {
            "schema_version": 1,
            "tag": LLAMA_CPP_TAG,
            "commit": LLAMA_CPP_COMMIT,
            "backend": backend,
            "source": source,
            "executable": str(Path("installed") / server_relative),
            "library_dirs": [str(Path("installed") / path) for path in library_relatives],
        }
        PRIVATE_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        temporary = PRIVATE_RUNTIME_CONFIG.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, PRIVATE_RUNTIME_CONFIG)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if installed.exists():
            shutil.rmtree(installed)
        if backup.exists():
            os.replace(backup, installed)
        raise
    return {"backend": backend, "source": source, "executable": str(installed / server_relative)}


def _asset_key(backend: str) -> str:
    system = platform.system().lower()
    arch = _architecture()
    if system == "windows":
        if arch != "x86_64":
            raise RuntimeError(f"官方 Windows 私有运行时暂不支持架构: {arch}")
        if backend == "cuda":
            gpu_info = environment_check().get("gpu_info", "")
            return "windows-cuda13" if any(token.startswith("12.") for token in gpu_info.replace(",", " ").split()) else "windows-cuda12"
        if backend == "cpu":
            return "windows-cpu"
        raise RuntimeError(f"Windows 不支持所选私有运行时后端: {backend}")
    if system == "linux":
        if arch not in {"x86_64", "aarch64"}:
            raise RuntimeError(f"官方 Linux 私有运行时暂不支持架构: {arch}")
        if backend not in {"vulkan", "cpu"}:
            raise RuntimeError(f"Linux 预编译包不支持后端: {backend}")
        return f"linux-{backend}-{arch}"
    if system == "darwin":
        if backend == "metal" and arch == "aarch64":
            return "darwin-metal-arm64"
        if backend == "cpu" and arch == "x86_64":
            return "darwin-cpu-x86_64"
        raise RuntimeError(f"macOS 不支持所选私有运行时组合: {backend}/{arch}")
    raise RuntimeError(f"不支持的平台: {system}")


def _select_backend(requested: str) -> str:
    if requested != "auto":
        return requested
    check = environment_check()
    system = platform.system().lower()
    if system == "windows":
        return "cuda" if check.get("nvidia_driver") else "cpu"
    if system == "linux":
        if check.get("nvidia_driver") and check.get("nvcc"):
            return "cuda"
        return "vulkan" if shutil.which("vulkaninfo") else "cpu"
    return "metal" if system == "darwin" and _architecture() == "aarch64" else "cpu"


def _install_prebuilt(backend: str, offline: bool, force: bool) -> dict[str, str]:
    key = _asset_key(backend)
    assets = ASSETS.get(key)
    if not assets:
        raise RuntimeError(f"没有适用于 {key} 的官方预编译包")
    PRIVATE_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    staging_parent = PRIVATE_RUNTIME_ROOT / ".staging"
    staging_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-", dir=staging_parent) as temp:
        payload = Path(temp) / "payload"
        payload.mkdir()
        for asset in assets:
            _extract(_download(asset, offline), payload)
        server = _find_server(payload)
        libraries = _library_dirs(payload)
        _validate_runtime(server, backend, libraries)
        detached = Path(temp).parent / f"activate-{os.getpid()}"
        if detached.exists():
            shutil.rmtree(detached)
        os.replace(payload, detached)
        return _activate(detached, detached / server.relative_to(payload), [detached / path.relative_to(payload) for path in libraries], backend, "official-release", force)


def _install_cuda_source(force: bool, jobs: int) -> dict[str, str]:
    missing = [tool for tool in ("git", "cmake", "c++", "nvcc") if not shutil.which(tool)]
    if missing:
        raise RuntimeError("CUDA 源码构建缺少工具: " + ", ".join(missing))
    PRIVATE_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="source-", dir=PRIVATE_RUNTIME_ROOT) as temp:
        source = Path(temp) / "llama.cpp"
        subprocess.run(["git", "clone", "--filter=blob:none", "--branch", LLAMA_CPP_TAG, "https://github.com/ggml-org/llama.cpp.git", str(source)], check=True)
        commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        if commit != LLAMA_CPP_COMMIT:
            raise RuntimeError(f"源码提交校验失败: {commit}")
        build = source / "build"
        subprocess.run(["cmake", "-S", str(source), "-B", str(build), "-DGGML_CUDA=ON", "-DGGML_NATIVE=OFF", "-DCMAKE_BUILD_TYPE=Release"], check=True)
        subprocess.run(["cmake", "--build", str(build), "--config", "Release", "--target", "llama-server", "-j", str(jobs)], check=True)
        server = _find_server(build / "bin")
        payload = Path(temp) / "payload"
        shutil.copytree(server.parent, payload)
        installed_server = _find_server(payload)
        libraries = _library_dirs(payload)
        _validate_runtime(installed_server, "cuda", libraries)
        detached = Path(temp).parent / f"activate-{os.getpid()}"
        if detached.exists():
            shutil.rmtree(detached)
        os.replace(payload, detached)
        return _activate(detached, detached / installed_server.relative_to(payload), [detached / path.relative_to(payload) for path in libraries], "cuda", "pinned-source", force)


def install_runtime(backend: str, offline: bool, force: bool, dry_run: bool, jobs: int) -> dict[str, str]:
    selected = _select_backend(backend)
    system = platform.system().lower()
    if selected == "cuda" and system == "linux":
        method = "pinned-source"
    else:
        method = "official-release"
        _asset_key(selected)
    plan = {"backend": selected, "source": method, "runtime_dir": str(PRIVATE_RUNTIME_ROOT), "tag": LLAMA_CPP_TAG}
    if dry_run:
        return plan
    if (PRIVATE_RUNTIME_ROOT / "installed").exists() and not force:
        raise RuntimeError(f"私有运行时已存在: {PRIVATE_RUNTIME_ROOT / 'installed'}；如需替换请加 --force")
    if selected == "cuda" and system == "linux":
        if offline:
            raise RuntimeError("Linux/WSL CUDA 使用固定源码构建，当前不支持 --offline")
        return _install_cuda_source(force, jobs)
    return _install_prebuilt(selected, offline, force)


def main() -> int:
    parser = argparse.ArgumentParser(description="llama.cpp setup helper for ComfyUI LLM Mini")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Inspect build tools, llama-server, CUDA, and the configured model directory.")
    install_parser = subparsers.add_parser("print-install", help="Print official llama.cpp build commands without executing them.")
    install_parser.add_argument("--backend", choices=["auto", "cuda", "cpu"], default="auto")
    install_parser.add_argument("--shell", choices=["auto", "bash", "powershell"], default="auto")
    install_parser.add_argument("--ref", default="master", help="Git ref to check out (default: master).")
    runtime_parser = subparsers.add_parser("install-runtime", help="Explicitly install a verified private llama.cpp runtime inside this plugin.")
    runtime_parser.add_argument("--backend", choices=["auto", "cuda", "vulkan", "metal", "cpu"], default="auto")
    runtime_parser.add_argument("--offline", action="store_true", help="Use only an already verified release archive cache.")
    runtime_parser.add_argument("--force", action="store_true", help="Atomically replace an existing private runtime.")
    runtime_parser.add_argument("--dry-run", action="store_true", help="Print the selected backend and method without downloading or changing files.")
    runtime_parser.add_argument("--jobs", type=int, default=max(1, min(16, os.cpu_count() or 1)))
    args = parser.parse_args()

    if args.command == "check":
        print(json.dumps(environment_check(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "install-runtime":
        if args.jobs < 1 or args.jobs > 128:
            parser.error("--jobs must be between 1 and 128")
        try:
            result = install_runtime(args.backend, args.offline, args.force, args.dry_run, args.jobs)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    result = install_help(args.backend, args.shell, args.ref)
    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    print(f"# backend={result['backend']} shell={result['shell']} ref={result['ref']}")
    for command in result["commands"]:
        print(command)
    print("\n# Explicit private runtime install (runs only when you execute it)")
    for command in result["private_install_commands"]:
        print(command)
    print("\n# LLM Mini config.ini example")
    for line in result["config_examples"]:
        print(line)
    print(f"\n# {result['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
