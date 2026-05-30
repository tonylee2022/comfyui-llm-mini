from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PACKAGE_DIR / "config.ini"
PROVIDERS_PATH = PACKAGE_DIR / "config" / "providers.json"
PERSONA_DIR = PACKAGE_DIR / "persona"
TEMP_DIR = PACKAGE_DIR / "temp"

CREDENTIAL_SOURCE_API_KEY = "api key"
CREDENTIAL_SOURCE_OAUTH = "oauth"
CREDENTIAL_SOURCES = [CREDENTIAL_SOURCE_API_KEY, CREDENTIAL_SOURCE_OAUTH]

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
    config = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        config.read(CONFIG_PATH, encoding="utf-8")
    return config


def save_ini(config: configparser.ConfigParser) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        config.write(f)


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace("\n", ",").split(",") if item.strip()]


def _get_bool(config: configparser.ConfigParser, section: str, option: str, default: bool) -> bool:
    if not config.has_option(section, option):
        return default
    return config.getboolean(section, option, fallback=default)


def load_provider_catalog() -> dict[str, dict[str, Any]]:
    with PROVIDERS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def configured_provider_ids() -> list[str]:
    config = load_ini()
    return [section.removeprefix("provider.").strip() for section in config.sections() if section.startswith("provider.") and section.removeprefix("provider.").strip()]


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
        "supports_chat": existing.get("supports_chat", True),
        "supports_image": existing.get("supports_image", False),
        "supports_video": existing.get("supports_video", False),
        "backend": config.get(section, "backend", fallback=existing.get("backend", "openai_compatible")),
    }
    return info


def load_providers() -> dict[str, dict[str, Any]]:
    catalog = load_provider_catalog()

    config = load_ini()
    providers: dict[str, dict[str, Any]] = {}
    for section in config.sections():
        if not section.startswith("provider."):
            continue
        provider_id = section.removeprefix("provider.").strip()
        if not provider_id:
            continue
        providers[provider_id] = _merge_provider(provider_id, catalog, config)
    return providers


def provider_names() -> list[str]:
    names = [provider_id for provider_id, info in load_providers().items() if info.get("supports_chat", True)]
    return names or ["openai"]


def credential_sources_for_provider(provider: str) -> list[str]:
    backend = resolve_provider(provider).get("backend", "openai_compatible")
    if provider == "codex" or backend == "codex":
        sources = [CREDENTIAL_SOURCE_OAUTH]
    elif backend == "xai" or provider == "xai":
        sources = [CREDENTIAL_SOURCE_API_KEY, CREDENTIAL_SOURCE_OAUTH]
    elif provider == "google" or backend == "gemini":
        sources = [CREDENTIAL_SOURCE_API_KEY]
    else:
        sources = [CREDENTIAL_SOURCE_API_KEY]
    configured = load_ini().get(f"provider.{provider}", "credential_source", fallback="").strip().lower()
    if configured in sources:
        sources.remove(configured)
        sources.insert(0, configured)
    return sources


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


def credential_input(provider: str, credential_source: str = "") -> str:
    source = (credential_source or CREDENTIAL_SOURCE_API_KEY).strip().lower()
    if source not in credential_sources_for_provider(provider):
        source = CREDENTIAL_SOURCE_API_KEY
    if source == CREDENTIAL_SOURCE_OAUTH:
        if provider == "xai":
            return "xai_oauth"
        if provider == "codex":
            return "codex_oauth"
        return "oauth"
    return ""


def resolve_provider(provider: str, node_api_key: str = "", node_base_url: str = "") -> dict[str, Any]:
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
    base_url = normalize_base_url((node_base_url or "").strip() or config_base or info.get("base_url", ""))

    info.update({"id": provider, "api_key": api_key, "base_url": base_url})
    return info


def persona_files() -> list[str]:
    PERSONA_DIR.mkdir(exist_ok=True)
    names = sorted(p.stem for p in PERSONA_DIR.glob("*.txt"))
    return names or [""]
