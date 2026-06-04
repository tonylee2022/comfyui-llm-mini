from __future__ import annotations

import asyncio
import time

from .core.config import load_providers, resolve_provider
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
            resolved = resolve_provider(provider)
            api_key = resolved.get("api_key", "")
            models = await asyncio.to_thread(list_models, provider, api_key, "")
            return web.json_response(
                {
                    "provider": provider,
                    "models": models,
                    "has_credentials": bool(resolved.get("api_key")) or provider == "ollama",
                }
            )
        except Exception as exc:
            return web.json_response({"models": [], "error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/llm-mini/config/get")
    async def get_config_route(request):
        try:
            provider = request.query.get("provider", "openai").strip()
            resolved = resolve_provider(provider)
            has_key = False
            api_key = resolved.get("api_key", "")
            if api_key:
                if api_key in {"xai_oauth", "codex_oauth"}:
                    from .core.oauth import get_oauth_token
                    oauth_provider = "xai" if api_key == "xai_oauth" else "codex"
                    token = get_oauth_token(oauth_provider)
                    if token:
                        has_key = True
                elif not api_key.startswith("sk-xxxx"):
                    has_key = True
            return web.json_response({
                "provider": provider,
                "base_url": resolved.get("base_url", ""),
                "has_key": has_key
            })
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/config/save")
    async def save_config_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "").strip()
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
            
            api_key = data.get("api_key", "").strip()
            base_url = data.get("base_url", "").strip()
            
            from .core.config import save_provider_config
            await asyncio.to_thread(save_provider_config, provider, api_key, base_url)
            
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
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/config/delete")
    async def delete_config_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "").strip()
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
                
            from .core.config import delete_provider_config
            await asyncio.to_thread(delete_provider_config, provider)
            return web.json_response({"success": True})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/config/save-default-models")
    async def save_default_models_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "").strip()
            if not provider:
                return web.json_response({"error": "Provider cannot be empty"}, status=400)
            default_models = data.get("default_models", [])
            if not isinstance(default_models, list):
                return web.json_response({"error": "default_models must be a list"}, status=400)
            from .core.config import save_provider_default_models
            await asyncio.to_thread(save_provider_default_models, provider, default_models)
            return web.json_response({"success": True})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/oauth/start")
    async def oauth_start_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "").strip()
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
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/llm-mini/oauth/status")
    async def oauth_status_route(request):
        try:
            provider = request.query.get("provider", "").strip()
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
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/oauth/cancel")
    async def oauth_cancel_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "").strip()
            if not provider:
                return web.json_response({"error": "Provider and Code cannot be empty"}, status=400)
            from .core.oauth import cancel_oauth_flow
            await asyncio.to_thread(cancel_oauth_flow, provider)
            return web.json_response({"success": True})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.post("/llm-mini/oauth/submit-code")
    async def oauth_submit_code_route(request):
        try:
            data = await request.json()
            provider = data.get("provider", "").strip()
            code = data.get("code", "").strip()
            if not provider or not code:
                return web.json_response({"error": "Provider and Code cannot be empty"}, status=400)
            
            from .core.oauth import exchange_manual_code
            await asyncio.to_thread(exchange_manual_code, provider, code)
            return web.json_response({"success": True})
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

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
