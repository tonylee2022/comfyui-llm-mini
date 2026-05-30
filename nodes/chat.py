from __future__ import annotations

from uuid import uuid4

from ..core.config import CREDENTIAL_SOURCE_API_KEY, CREDENTIAL_SOURCES, credential_input, provider_names, resolve_provider
from ..core.persona import load_persona_text
from ..providers.openai_compatible import ApiChatClient


def _chat_fingerprint(is_locked=True):
    return "locked" if is_locked else uuid4().hex


class ApiChatNode:
    @classmethod
    def INPUT_TYPES(cls):
        providers = provider_names()
        return {
            "required": {
                "provider": (providers, {"default": providers[0]}),
                "model_name": (["click Refresh Models"], {"default": "click Refresh Models"}),
                "system_prompt": ("STRING", {"multiline": True, "default": ""}),
                "user_prompt": ("STRING", {"multiline": True, "default": ""}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1}),
                "max_tokens": ("INT", {"default": 2048, "min": 1, "max": 128000, "step": 128}),
            },
            "optional": {
                "is_locked": ("BOOLEAN", {"default": True}),
                "credential_source": (CREDENTIAL_SOURCES, {"default": CREDENTIAL_SOURCE_API_KEY}),
                "system_prompt_input": ("STRING", {"forceInput": True}),
                "image": ("IMAGE", {"forceInput": True}),
                "image_url": ("STRING", {"forceInput": True}),
                "stream": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("assistant_response", "history_json")
    FUNCTION = "chat"
    CATEGORY = "ComfyUI LLM Mini/Chat"

    @classmethod
    def VALIDATE_INPUTS(cls, model_name=None, credential_source=None):
        return True

    @classmethod
    def IS_CHANGED(cls, is_locked=True, **kwargs):
        return _chat_fingerprint(is_locked)

    def chat(self, provider, model_name, system_prompt, user_prompt, temperature, max_tokens, is_locked=True, credential_source=CREDENTIAL_SOURCE_API_KEY, system_prompt_input="", history_json="", image=None, image_url="", stream=False, extra_parameters=None):
        api_key = credential_input(provider, credential_source)
        info = resolve_provider(provider, api_key)
        final_system = (system_prompt or "") + ("\n" + system_prompt_input if system_prompt_input else "")
        model_name = model_name if model_name != "click Refresh Models" else (info.get("default_models") or [""])[0]
        client = ApiChatClient(provider=provider, model_name=model_name, api_key=info.get("api_key", ""), base_url=info.get("base_url", ""), credential_source=credential_source)
        try:
            res = client.send(user_prompt, final_system, temperature, max_tokens, history_json, image, image_url, stream, extra_parameters)
            return (res[0], res[1])
        except Exception as exc:
            return (f"LLM Mini API request failed: {exc}", history_json or "")


class PersonaNode:
    @classmethod
    def INPUT_TYPES(cls):
        from ..core.config import persona_files

        return {"required": {"persona_name": (persona_files(), {"default": persona_files()[0]})}, "optional": {"text": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("system_prompt_input",)
    FUNCTION = "load"
    CATEGORY = "ComfyUI LLM Mini/Persona"

    def load(self, persona_name, text=None):
        return (load_persona_text(persona_name, text),)


class PersonaManagerNode:
    @classmethod
    def INPUT_TYPES(cls):
        from ..core.config import persona_files
        files = persona_files()
        return {
            "required": {
                "persona_name": (files, {"default": files[0] if files else ""}),
                "new_name": ("STRING", {"default": ""}),
                "content": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("system_prompt_input",)
    FUNCTION = "output_content"
    CATEGORY = "ComfyUI LLM Mini/Persona"

    def output_content(self, persona_name, new_name, content):
        return (content,)
