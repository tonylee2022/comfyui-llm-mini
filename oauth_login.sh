#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 0. 检测当前已激活的 Conda 虚拟环境
if [ -n "$CONDA_PREFIX" ] && [ -f "$CONDA_PREFIX/bin/python" ]; then
    echo "[LLM Mini] Detected active Conda environment: $CONDA_DEFAULT_ENV"
    "$CONDA_PREFIX/bin/python" "$SCRIPT_DIR/oauth_login.py" "$@"

# 1. 检测常见于 ComfyUI 根目录下的 venv 虚拟环境
elif [ -f "$SCRIPT_DIR/../../../venv/bin/python" ]; then
    echo "[LLM Mini] Detected ComfyUI venv Python."
    "$SCRIPT_DIR/../../../venv/bin/python" "$SCRIPT_DIR/oauth_login.py" "$@"
# 2. 默认回退使用系统 python3
else
    echo "[LLM Mini] ComfyUI venv Python not found. Using system 'python3'..."
    python3 "$SCRIPT_DIR/oauth_login.py" "$@"
fi
