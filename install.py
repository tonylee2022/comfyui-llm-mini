"""ComfyUI-Manager 首次安装钩子：尽力安装节点私有 llama.cpp 运行时。"""

from __future__ import annotations

import os

import llama_cpp_setup
from core.llama_cpp import PRIVATE_RUNTIME_ROOT


def main() -> int:
    installed = PRIVATE_RUNTIME_ROOT / "installed"
    if installed.is_dir():
        print(f"[comfyui-llm-mini] llama.cpp 私有运行时已存在，跳过首次安装: {installed}")
        return 0
    try:
        result = llama_cpp_setup.install_runtime(
            "auto",
            offline=False,
            force=False,
            dry_run=False,
            jobs=max(1, min(16, os.cpu_count() or 1)),
        )
        print(f"[comfyui-llm-mini] llama.cpp 私有运行时安装完成: {result.get('executable', '')}")
    except Exception as exc:
        print("[comfyui-llm-mini] llama.cpp 私有运行时自动安装失败，但不会阻止节点安装。")
        print(f"[comfyui-llm-mini] 原因: {exc}")
        print("[comfyui-llm-mini] 请启动 ComfyUI 后，在 Provider Manager 中重试安装。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
