from __future__ import annotations

import configparser
import json
import logging

logger = logging.getLogger("LLMMini")
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PACKAGE_DIR / "config.ini"
PROVIDERS_PATH = PACKAGE_DIR / "config" / "providers.json"
PERSONA_DIR = PACKAGE_DIR / "persona"
TEMP_DIR = PACKAGE_DIR / "temp"
PROVIDER_ID_PATTERN = re.compile(r"^[^\W_][\w.-]{0,63}$", re.UNICODE)
CHAT_BACKENDS = {"openai_compatible", "anthropic", "gemini", "xai", "codex"}
_CONFIG_LOCK = threading.RLock()
_catalog_cache = None
_ini_cache = None
_providers_cache = None

# (credential source constants removed)

DEFAULT_OPENAI_COMPATIBLE = {
    "display_name": "",
    "base_url": "",
    "models_endpoint": "models",
    "auth_type": "api_key",
    "env_key_names": [],
    "default_models": [],
    "supports_chat": True,
    "supports_image": False,
    "supports_video": False,
    "backend": "openai_compatible",
}


def load_ini() -> configparser.ConfigParser:
    global _ini_cache
    with _CONFIG_LOCK:
        if _ini_cache is None:
            config = configparser.ConfigParser()
            if CONFIG_PATH.exists():
                try:
                    if os.name != "nt":
                        import stat
                        current_mode = stat.S_IMODE(CONFIG_PATH.stat().st_mode)
                        if current_mode != 0o600:
                            os.chmod(CONFIG_PATH, 0o600)
                except OSError:
                    pass
                config.read(CONFIG_PATH, encoding="utf-8")
            _ini_cache = config
        return _ini_cache


def save_ini(config: configparser.ConfigParser) -> None:
    global _ini_cache, _providers_cache
    with _CONFIG_LOCK:
        _ini_cache = None
        _providers_cache = None
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=CONFIG_PATH.parent,
                prefix=f".{CONFIG_PATH.name}.",
                suffix=".tmp",
                delete=False,
            ) as f:
                config.write(f)
                f.flush()
                os.fsync(f.fileno())
                temp_path = Path(f.name)
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, CONFIG_PATH)
            try:
                os.chmod(CONFIG_PATH, 0o600)
            except OSError:
                pass
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()


@contextmanager
def config_lock():
    with _CONFIG_LOCK:
        yield


def validate_provider_id(provider_id: str) -> str:
    provider_id = str(provider_id or "").strip()
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError("Provider ID must start with a Chinese character, letter, or number and contain only Chinese characters, letters, numbers, dots, underscores, or hyphens (maximum 64 characters).")
    return provider_id


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace("\n", ",").split(",") if item.strip()]


def _get_bool(config: configparser.ConfigParser, section: str, option: str, default: bool) -> bool:
    if not config.has_option(section, option):
        return default
    return config.getboolean(section, option, fallback=default)


def load_provider_catalog() -> dict[str, dict[str, Any]]:
    global _catalog_cache
    with _CONFIG_LOCK:
        if _catalog_cache is None:
            with PROVIDERS_PATH.open("r", encoding="utf-8") as f:
                _catalog_cache = json.load(f)
        return _catalog_cache


def configured_provider_ids() -> list[str]:
    config = load_ini()
    provider_ids = []
    for section in config.sections():
        if not section.startswith("provider."):
            continue
        provider_id = section.removeprefix("provider.").strip()
        if PROVIDER_ID_PATTERN.fullmatch(provider_id):
            provider_ids.append(provider_id)
    return provider_ids


def _merge_provider(provider_id: str, catalog: dict[str, dict[str, Any]], config: configparser.ConfigParser) -> dict[str, Any]:
    section = f"provider.{provider_id}"
    existing = dict(catalog.get(provider_id, DEFAULT_OPENAI_COMPATIBLE))
    if not existing.get("display_name"):
        existing["display_name"] = provider_id
    configured_models = _split_list(config.get(section, "default_models", fallback=""))
    configured_model = config.get(section, "default_model", fallback="").strip()
    base_models = configured_models if config.has_option(section, "default_models") else list(existing.get("default_models", []))
    if configured_model and configured_model not in base_models:
        base_models.insert(0, configured_model)
    if not base_models:
        base_models = ["click Refresh Models"]
    info = {
        "display_name": config.get(section, "display_name", fallback=existing.get("display_name", provider_id)),
        "base_url": config.get(section, "base_url", fallback=existing.get("base_url", "")),
        "models_endpoint": existing.get("models_endpoint", "models"),
        "auth_type": config.get(section, "auth_type", fallback=existing.get("auth_type", "api_key")),
        "env_key_names": existing.get("env_key_names", []),
        "default_models": base_models,
        "supports_chat": _get_bool(config, section, "supports_chat", existing.get("supports_chat", True)),
        "supports_image": _get_bool(config, section, "supports_image", existing.get("supports_image", False)),
        "supports_video": _get_bool(config, section, "supports_video", existing.get("supports_video", False)),
        "backend": config.get(section, "backend", fallback=existing.get("backend", "openai_compatible")),
    }
    if config.has_section(section):
        for option in config.options(section):
            if option not in info:
                info[option] = config.get(section, option)
    return info


def load_providers() -> dict[str, dict[str, Any]]:
    global _providers_cache
    with _CONFIG_LOCK:
        if _providers_cache is None:
            catalog = load_provider_catalog()
            config = load_ini()
            providers: dict[str, dict[str, Any]] = {}
            for section in config.sections():
                if not section.startswith("provider."):
                    continue
                provider_id = section.removeprefix("provider.").strip()
                if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
                    logger.warning(f"Skipping invalid provider section: {section}")
                    continue
                providers[provider_id] = _merge_provider(provider_id, catalog, config)
            _providers_cache = providers
        return _providers_cache


def provider_names() -> list[str]:
    names = list(load_providers().keys())
    return names or ["openai"]


def chat_provider_names() -> list[str]:
    names = []
    for provider_id, info in load_providers().items():
        if not info.get("supports_chat", True):
            continue
        resolved = resolve_provider(provider_id)
        if has_api_or_oauth_credentials(provider_id, resolved):
            names.append(provider_id)
    return names


# (credential_sources_for_provider removed)


def normalize_base_url(base_url: str) -> str:
    base_url = (base_url or "").strip()
    if not base_url:
        return base_url
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url


def is_placeholder_secret(value: str) -> bool:
    value = (value or "").strip()
    return value.lower() in {"sk-xxxxx", "sk-xxxx", "placeholder", "your-api-key"}


def is_oauth_marker(value: str) -> bool:
    return (value or "").strip().lower() in {"oauth", "xai_oauth", "codex_oauth"}


# (credential_input removed)


def resolve_provider(provider: str, node_api_key: str = "", node_base_url: str = "") -> dict[str, Any]:
    provider = validate_provider_id(provider)
    catalog = load_provider_catalog()
    config = load_ini()
    if provider in configured_provider_ids():
        info = _merge_provider(provider, catalog, config)
    elif provider in catalog:
        info = dict(catalog[provider])
    else:
        info = dict(DEFAULT_OPENAI_COMPATIBLE)
        info["display_name"] = provider

    section = f"provider.{provider}"
    section_key = config.get(section, "api_key", fallback="").strip() if config.has_section(section) else ""
    section_base = config.get(section, "base_url", fallback="").strip() if config.has_section(section) else ""

    env_key = ""
    for name in info.get("env_key_names", []):
        env_key = os.environ.get(name, "")
        if env_key:
            break

    node_api_key = (node_api_key or "").strip()
    if is_placeholder_secret(node_api_key):
        node_api_key = ""
    if node_api_key:
        api_key = node_api_key
        config_base = section_base
    elif section_key and not is_placeholder_secret(section_key):
        api_key = section_key
        config_base = section_base
    else:
        api_key = env_key.strip()
        config_base = section_base

    # 若未找到任何 API Key，且该提供商支持 OAuth，我们自动采用 OAuth
    if not api_key and provider in {"xai", "codex"}:
        api_key = f"{provider}_oauth"

    base_url = normalize_base_url((node_base_url or "").strip() or config_base or info.get("base_url", ""))

    info.update({"id": provider, "api_key": api_key, "base_url": base_url})
    return info


def has_provider_credentials(provider: str, resolved: dict[str, Any] | None = None) -> bool:
    resolved = resolved or resolve_provider(provider)
    if resolved.get("auth_type") == "none":
        return True

    api_key = str(resolved.get("api_key", "") or "").strip()
    if not api_key or is_placeholder_secret(api_key):
        return False
    if is_oauth_marker(api_key):
        from .oauth import get_oauth_token

        oauth_provider = provider
        if api_key == "xai_oauth":
            oauth_provider = "xai"
        elif api_key == "codex_oauth":
            oauth_provider = "codex"
        return bool(get_oauth_token(oauth_provider))
    return True


def has_api_or_oauth_credentials(provider: str, resolved: dict[str, Any] | None = None) -> bool:
    resolved = resolved or resolve_provider(provider)
    if resolved.get("auth_type") == "none":
        return True
    return has_provider_credentials(provider, resolved)


def provider_credential_status(provider: str, resolved: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = validate_provider_id(provider)
    resolved = resolved or resolve_provider(provider)
    auth_type = str(resolved.get("auth_type", "") or "")

    status = {
        "api_key_configured": False,
        "api_key_source": "none",
        "oauth_supported": provider in {"xai", "codex"},
        "oauth_configured": False,
        "configured": False,
        "no_credentials_required": auth_type == "none",
    }

    if status["no_credentials_required"]:
        status["configured"] = True
        return status

    config = load_ini()
    section = f"provider.{provider}"
    section_key = config.get(section, "api_key", fallback="").strip() if config.has_section(section) else ""
    if section_key and not is_placeholder_secret(section_key) and not is_oauth_marker(section_key):
        status["api_key_configured"] = True
        status["api_key_source"] = "config"
    else:
        for name in resolved.get("env_key_names", []):
            env_key = os.environ.get(name, "").strip()
            if env_key and not is_placeholder_secret(env_key):
                status["api_key_configured"] = True
                status["api_key_source"] = "env"
                break

    if status["oauth_supported"]:
        from .oauth import get_oauth_token

        status["oauth_configured"] = bool(get_oauth_token(provider))

    status["configured"] = bool(status["api_key_configured"] or status["oauth_configured"])
    return status


def persona_files() -> list[str]:
    PERSONA_DIR.mkdir(exist_ok=True)
    names = sorted(p.stem for p in PERSONA_DIR.glob("*.txt"))
    return names or [""]


def validate_chat_backend(backend: str) -> str:
    backend = str(backend or "").strip()
    if backend not in CHAT_BACKENDS:
        raise ValueError(f"Chat backend must be one of: {', '.join(sorted(CHAT_BACKENDS))}.")
    return backend


def save_provider_config(
    provider_id: str,
    api_key: str,
    base_url: str,
    supports_chat: bool | None = None,
    supports_image: bool | None = None,
    supports_video: bool | None = None,
    backend: str | None = None,
) -> None:
    provider_id = validate_provider_id(provider_id)
    with _CONFIG_LOCK:
        config = load_ini()
        section = f"provider.{provider_id}"
        if not config.has_section(section):
            config.add_section(section)

        api_key_clean = (api_key or "").strip()
        if api_key_clean and not api_key_clean.startswith("[") and not api_key_clean.endswith("]"):
            config[section]["api_key"] = api_key_clean

        if base_url is not None:
            config[section]["base_url"] = base_url.strip()
        if supports_chat is not None:
            config[section]["supports_chat"] = "true" if supports_chat else "false"
        if supports_image is not None:
            config[section]["supports_image"] = "true" if supports_image else "false"
        if supports_video is not None:
            config[section]["supports_video"] = "true" if supports_video else "false"
        if backend is not None:
            config[section]["backend"] = validate_chat_backend(backend)
        save_ini(config)


def rename_provider_config(old_provider_id: str, new_provider_id: str) -> None:
    old_provider_id = validate_provider_id(old_provider_id)
    new_provider_id = validate_provider_id(new_provider_id)
    if old_provider_id == new_provider_id:
        return

    with _CONFIG_LOCK:
        config = load_ini()
        catalog = load_provider_catalog()
        if old_provider_id in catalog:
            raise ValueError("Built-in providers cannot be renamed.")
        if new_provider_id in catalog:
            raise ValueError("Provider ID already exists as a built-in provider.")

        old_section = f"provider.{old_provider_id}"
        new_section = f"provider.{new_provider_id}"
        if not config.has_section(old_section):
            raise ValueError(f"Provider '{old_provider_id}' does not exist.")
        if config.has_section(new_section):
            raise ValueError(f"Provider '{new_provider_id}' already exists.")

        config.add_section(new_section)
        for key, value in config.items(old_section):
            config.set(new_section, key, value)
        config.remove_section(old_section)

        old_oauth_section = f"{old_provider_id}_oauth"
        new_oauth_section = f"{new_provider_id}_oauth"
        if config.has_section(old_oauth_section):
            if config.has_section(new_oauth_section):
                raise ValueError(f"OAuth config for '{new_provider_id}' already exists.")
            config.add_section(new_oauth_section)
            for key, value in config.items(old_oauth_section):
                config.set(new_oauth_section, key, value)
            config.remove_section(old_oauth_section)

        save_ini(config)


def delete_provider_config(provider_id: str) -> None:
    provider_id = validate_provider_id(provider_id)
    with _CONFIG_LOCK:
        config = load_ini()
        catalog = load_provider_catalog()
        section = f"provider.{provider_id}"
        changed = False

        # 判定是否属于内置的主流提供商
        is_built_in = provider_id in catalog

        if config.has_section(section):
            if is_built_in:
                # 默认内置的主流提供商不彻底删除配置段，仅清除 api_key 选项，以便保留其在界面的下拉菜单里
                if config.has_option(section, "api_key"):
                    config.remove_option(section, "api_key")
                    changed = True
            else:
                # 用户自定义添加的提供商，则彻底删除该配置段
                config.remove_section(section)
                changed = True

        # 同步擦除该提供商的 OAuth 授权凭据缓存段，防止数据残留
        oauth_section = f"{provider_id}_oauth"
        if config.has_section(oauth_section):
            config.remove_section(oauth_section)
            changed = True

        if changed:
            save_ini(config)


def save_provider_default_models(provider_id: str, default_models: list[str]) -> None:
    provider_id = validate_provider_id(provider_id)
    with _CONFIG_LOCK:
        config = load_ini()
        section = f"provider.{provider_id}"
        if not config.has_section(section):
            config.add_section(section)

        models = [m.strip() for m in default_models if m and m.strip()]
        if models:
            config[section]["default_models"] = ",".join(models)
            current_default = config.get(section, "default_model", fallback="").strip()
            if not current_default or current_default not in models:
                config[section]["default_model"] = models[0]
        else:
            if config.has_option(section, "default_models"):
                config.remove_option(section, "default_models")
            if config.has_option(section, "default_model"):
                config.remove_option(section, "default_model")

        save_ini(config)
