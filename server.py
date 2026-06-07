from __future__ import annotations

import asyncio
import time
import logging

logger = logging.getLogger("LLMMini")

from .core.config import has_api_or_oauth_credentials, has_provider_credentials, load_providers, provider_credential_status, resolve_provider, validate_provider_id
from .core.persona import persona_path
from .providers.openai_compatible import list_models

_REGISTERED = False


def _provider_payload() -> list[dict]:
    providers = load_providers()
    payload = []
    for provider_id, info in providers.items():
        resolved = resolve_provider(provider_id)
        has_key = has_provider_credentials(provider_id, resolved)
        chat_available = bool(info.get("supports_chat")) and has_api_or_oauth_credentials(provider_id, resolved)
        payload.append(
            {
                "id": provider_id,
                "display_name": info.get("display_name", provider_id),
                "has_credentials": has_key,
                "chat_available": chat_available,
                "supports_chat": bool(info.get("supports_chat")),
                "supports_image": bool(info.get("supports_image")),
                "supports_video": bool(info.get("supports_video")),
                "default_models": info.get("default_models", []),
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
        logger.warning(f"PromptServer unavailable, route registration skipped: {exc}")
        return

    def route_error(exc: Exception, **payload):
        payload["error"] = str(exc)
        return web.json_response(payload, status=400 if isinstance(exc, ValueError) else 500)

    def json_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @PromptServer.instance.routes.post("/llm-mini/providers")
    async def providers_route(request):
        return web.json_response({"providers": _provider_payload()})

    @PromptServer.instance.routes.post("/llm-mini/models")
    async def models_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", "openai"))
            resolved = resolve_provider(provider)
            api_key = resolved.get("api_key", "")
            models = await asyncio.to_thread(list_models, provider, api_key, "")
            return web.json_response(
                {
                    "provider": provider,
                    "models": models,
                    "has_credentials": has_provider_credentials(provider, resolved),
                }
            )
        except Exception as exc:
            return route_error(exc, models=[])

    @PromptServer.instance.routes.get("/llm-mini/config/get")
    async def get_config_route(request):
        try:
            provider = validate_provider_id(request.query.get("provider", "openai"))
            resolved = resolve_provider(provider)
            credential_status = provider_credential_status(provider, resolved)
            has_key = has_provider_credentials(provider, resolved)
            return web.json_response({
                "provider": provider,
                "base_url": resolved.get("base_url", ""),
                "backend": resolved.get("backend", "openai_compatible"),
                "has_key": has_key,
                "credential_status": credential_status,
                "supports_chat": bool(resolved.get("supports_chat")),
                "supports_image": bool(resolved.get("supports_image")),
                "supports_video": bool(resolved.get("supports_video")),
            })
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/config/save")
    async def save_config_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", ""))
            original_provider_raw = str(data.get("original_provider", "") or "").strip()
            original_provider = validate_provider_id(original_provider_raw) if original_provider_raw else provider
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
            
            api_key = data.get("api_key", "").strip()
            base_url = data.get("base_url", "").strip()
            supports_chat = json_bool(data.get("supports_chat"), True)
            supports_image = json_bool(data.get("supports_image"), False)
            supports_video = json_bool(data.get("supports_video"), False)
            backend = str(data.get("backend", "") or "").strip() or None
            
            from .core.config import rename_provider_config, save_provider_config
            if original_provider != provider:
                await asyncio.to_thread(rename_provider_config, original_provider, provider)
            await asyncio.to_thread(save_provider_config, provider, api_key, base_url, supports_chat, supports_image, supports_video, backend)
            
            try:
                resolved = resolve_provider(provider)
                models = await asyncio.to_thread(list_models, provider, resolved.get("api_key", ""), "")
            except Exception:
                models = []
                
            return web.json_response({
                "success": True,
                "models": models
            })
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/config/delete")
    async def delete_config_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", ""))
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
                
            from .core.config import delete_provider_config
            await asyncio.to_thread(delete_provider_config, provider)
            return web.json_response({"success": True})
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/config/save-default-models")
    async def save_default_models_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", ""))
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
            default_models = data.get("default_models", [])
            if not isinstance(default_models, list):
                return web.json_response({"error": "default_models must be a list"}, status=400)
            from .core.config import save_provider_default_models
            await asyncio.to_thread(save_provider_default_models, provider, default_models)
            return web.json_response({"success": True})
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/oauth/start")
    async def oauth_start_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", ""))
            flow = data.get("flow", "browser").strip()
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
                
            from .core.oauth import start_async_oauth_flow
            res = await asyncio.to_thread(start_async_oauth_flow, provider, flow)
            return web.json_response({
                "success": True,
                "status": res.get("status"),
                "user_code": res.get("user_code"),
                "verification_uri": res.get("verification_uri"),
                "expires_in": res.get("expires_in")
            })
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.get("/llm-mini/oauth/status")
    async def oauth_status_route(request):
        try:
            provider = validate_provider_id(request.query.get("provider", ""))
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
                
            from .core.oauth import get_oauth_state
            state = get_oauth_state(provider)
            
            elapsed = time.time() - state.get("start_time", time.time())
            expires_in = max(0, int(state.get("expires_in", 300) - elapsed))
            
            models = []
            if state.get("status") == "success":
                try:
                    resolved = resolve_provider(provider)
                    models = await asyncio.to_thread(list_models, provider, resolved.get("api_key", ""), "")
                except Exception:
                    pass
                    
            return web.json_response({
                "status": state.get("status"),
                "error": state.get("error"),
                "expires_in": expires_in,
                "models": models
            })
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/oauth/cancel")
    async def oauth_cancel_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", ""))
            if not provider:
                return web.json_response({"error": "Provider and Code cannot be empty"}, status=400)
            from .core.oauth import cancel_oauth_flow
            await asyncio.to_thread(cancel_oauth_flow, provider)
            return web.json_response({"success": True})
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/oauth/submit-code")
    async def oauth_submit_code_route(request):
        try:
            data = await request.json()
            provider = validate_provider_id(data.get("provider", ""))
            code = data.get("code", "").strip()
            if not provider or not code:
                return web.json_response({"error": "Provider and Code cannot be empty"}, status=400)
            
            from .core.oauth import exchange_manual_code
            await asyncio.to_thread(exchange_manual_code, provider, code)
            return web.json_response({"success": True})
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/persona/get")
    async def get_persona_route(request):
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            if not name:
                return web.json_response({"content": ""})
            path = persona_path(name)
            if not path.exists():
                return web.json_response({"content": ""})
            content = path.read_text(encoding="utf-8")
            return web.json_response({"name": name, "content": content})
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/persona/save")
    async def save_persona_route(request):
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            content = data.get("content", "")
            if not name:
                return web.json_response({"error": "Persona name cannot be empty"}, status=400)
            from .core.config import PERSONA_DIR, persona_files
            PERSONA_DIR.mkdir(exist_ok=True)
            path = persona_path(name)
            path.write_text(content, encoding="utf-8")
            return web.json_response({"success": True, "personas": persona_files()})
        except Exception as exc:
            return route_error(exc)

    @PromptServer.instance.routes.post("/llm-mini/persona/delete")
    async def delete_persona_route(request):
        try:
            data = await request.json()
            name = data.get("name", "").strip()
            if not name:
                return web.json_response({"error": "Persona name cannot be empty"}, status=400)
            from .core.config import persona_files
            path = persona_path(name)
            if path.exists():
                path.unlink()
            return web.json_response({"success": True, "personas": persona_files()})
        except Exception as exc:
            return route_error(exc)

    _REGISTERED = True
