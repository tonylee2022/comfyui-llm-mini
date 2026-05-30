from __future__ import annotations

import asyncio

from .core.config import credential_input, credential_sources_for_provider, load_providers, resolve_provider
from .providers.openai_compatible import list_models

_REGISTERED = False


def _provider_payload() -> list[dict]:
    providers = load_providers()
    payload = []
    for provider_id, info in providers.items():
        resolved = resolve_provider(provider_id)
        has_key = bool(resolved.get("api_key")) or info.get("auth_type") == "none"
        payload.append(
            {
                "id": provider_id,
                "display_name": info.get("display_name", provider_id),
                "has_credentials": has_key,
                "supports_chat": bool(info.get("supports_chat")),
                "supports_image": bool(info.get("supports_image")),
                "supports_video": bool(info.get("supports_video")),
                "default_models": info.get("default_models", []),
                "credential_sources": credential_sources_for_provider(provider_id),
            }
        )
    return payload


def register_routes() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as exc:
        print(f"[LLM Mini] PromptServer unavailable, route registration skipped: {exc}")
        return

    @PromptServer.instance.routes.post("/llm-mini/providers")
    async def providers_route(request):
        return web.json_response({"providers": _provider_payload()})

    @PromptServer.instance.routes.post("/llm-mini/models")
    async def models_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "openai")
            credential_source = data.get("credential_source", "")
            api_key = credential_input(provider, credential_source)
            models = await asyncio.to_thread(list_models, provider, api_key, "", credential_source)
            resolved = resolve_provider(provider, api_key, "")
            return web.json_response(
                {
                    "provider": provider,
                    "models": models,
                    "has_credentials": bool(resolved.get("api_key")) or provider == "ollama",
                    "credential_sources": credential_sources_for_provider(provider),
                }
            )
        except Exception as exc:
            return web.json_response({"models": [], "error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/persona/get")
    async def get_persona_route(request):
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            if not name:
                return web.json_response({"content": ""})
            if "/" in name or "\\" in name or ".." in name:
                return web.json_response({"error": "Invalid name"}, status=400)
            from .core.config import PERSONA_DIR
            path = PERSONA_DIR / f"{name}.txt"
            if not path.exists():
                return web.json_response({"content": ""})
            content = path.read_text(encoding="utf-8")
            return web.json_response({"name": name, "content": content})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/persona/save")
    async def save_persona_route(request):
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            content = data.get("content", "")
            if not name:
                return web.json_response({"error": "Persona name cannot be empty"}, status=400)
            if "/" in name or "\\" in name or ".." in name:
                return web.json_response({"error": "Invalid name"}, status=400)
            from .core.config import PERSONA_DIR, persona_files
            PERSONA_DIR.mkdir(exist_ok=True)
            path = PERSONA_DIR / f"{name}.txt"
            path.write_text(content, encoding="utf-8")
            return web.json_response({"success": True, "personas": persona_files()})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/persona/delete")
    async def delete_persona_route(request):
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            if not name:
                return web.json_response({"error": "Persona name cannot be empty"}, status=400)
            if "/" in name or "\\" in name or ".." in name:
                return web.json_response({"error": "Invalid name"}, status=400)
            from .core.config import PERSONA_DIR, persona_files
            path = PERSONA_DIR / f"{name}.txt"
            if path.exists():
                path.unlink()
            return web.json_response({"success": True, "personas": persona_files()})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    _REGISTERED = True
