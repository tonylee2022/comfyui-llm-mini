@echo off
setlocal

:: 0. 检测当前已激活的 Conda 虚拟环境
if not "%CONDA_PREFIX%"=="" (
    if exist "%CONDA_PREFIX%\python.exe" (
        echo [LLM Mini] Detected active Conda environment: %CONDA_DEFAULT_ENV%
        "%CONDA_PREFIX%\python.exe" "%~dp0oauth_login.py" %*
        goto end
    )
)

:: 1. 检测 ComfyUI Windows Portable 官方便携版自带的嵌入式 Python
set "EMBEDDED_PYTHON=%~dp0..\..\..\python_embeded\python.exe"
if exist "%EMBEDDED_PYTHON%" (
    echo [LLM Mini] Detected ComfyUI Portable embedded Python.
    "%EMBEDDED_PYTHON%" "%~dp0oauth_login.py" %*
    goto end
)

:: 2. 检测上级目录中常见的 venv 虚拟环境
set "VENV_PYTHON=%~dp0..\..\..\venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    echo [LLM Mini] Detected virtual environment Python.
    "%VENV_PYTHON%" "%~dp0oauth_login.py" %*
    goto end
)

:: 3. 默认回退使用系统 PATH 中的 python
echo [LLM Mini] Embedded/Virtual Python not found. Using system 'python'...
python "%~dp0oauth_login.py" %*

:end
pause
