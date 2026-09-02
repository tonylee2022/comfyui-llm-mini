from __future__ import annotations

from uuid import uuid4

from comfy_api.latest import IO
from ..core.config import chat_provider_names, resolve_provider
from ..core.persona import load_persona_text
from ..providers.openai_compatible import ApiChatClient
from ..core.status import StatusUpdater, get_unique_id


LOCAL_UNLOAD_POLICIES = ["after_run", "keep_warm", "idle"]


def _chat_fingerprint(is_locked=True):
    return "locked" if is_locked else uuid4().hex


TRANSLATION_SOURCE_LANGUAGES = [
    "Auto detect",
    "Chinese",
    "English",
    "Japanese",
    "Korean",
    "French",
    "German",
    "Spanish",
    "Portuguese",
    "Italian",
    "Russian",
    "Arabic",
    "Thai",
    "Vietnamese",
]
TRANSLATION_TARGET_LANGUAGES = TRANSLATION_SOURCE_LANGUAGES[1:]
TRANSLATION_TONES = [
    "Preserve original",
    "Natural",
    "Formal",
    "Conversational",
    "Professional",
    "Concise",
    "Literary",
]
TRANSLATION_SYSTEM_PROMPT = """你是一个翻译专家，请将我的输入从 {source_language} 翻译成 {target_language}，语气为 {tone}，语气程度为 {tone_degree}。
语气程度最大为 10，最小为 0。数字越大，目标语气越明显；当语气程度为 0 时，尽量保持原文语气，当语气程度为 10 时，强烈体现目标语气。
如果 {source_language} 和 {target_language} 相同，也要根据语气要求调整文本，而不是直接返回原内容。
不要复述原文或输出解释、标题及其他无关内容，只返回翻译后的内容。输入包含 Markdown、HTML 或其他排版格式时，必须保留原格式。

处理 Markdown 和 HTML 时遵守以下规则：
1. 保留 Markdown 结构和排版。
2. Markdown 超链接的 `[]` 中可见文字必须翻译，`()` 中的链接地址必须保持原样。
3. 保留 HTML 标签、属性和结构；翻译页面中可见的文字，不得翻译链接地址或标签属性值。
"""


def _render_translation_prompt(
    source_language: str,
    target_language: str,
    tone: str,
    tone_degree: int,
) -> str:
    return TRANSLATION_SYSTEM_PROMPT.format(
        source_language=source_language,
        target_language=target_language,
        tone=tone,
        tone_degree=max(0, min(10, int(tone_degree))),
    )


class ApiChatNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        providers = chat_provider_names()
        default_provider = providers[0] if providers else ""
        default_models = (resolve_provider(default_provider).get("default_models") or [""]) if default_provider else [""]
        return IO.Schema(
            node_id="LLMMiniApiChat",
            display_name="API Chat",
            category="ComfyUI LLM Mini/Chat",
            inputs=[
                IO.String.Input("system_prompt_input", optional=True, force_input=True),
                IO.String.Input("history_json", optional=True, force_input=True),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 17)],
                        min=0,
                    ),
                    optional=True,
                    tooltip="Optional reference images. Add image inputs dynamically as needed.",
                ),
                IO.Video.Input(
                    "video",
                    optional=True,
                    tooltip="Optional video input for a llama.cpp model that advertises video support.",
                ),
                IO.Combo.Input("provider", options=providers, default=default_provider),
                IO.Combo.Input("model_name", options=default_models, default=default_models[0]),
                IO.String.Input("system_prompt", multiline=True, default=""),
                IO.String.Input("user_prompt", multiline=True, default=""),
                IO.Float.Input("temperature", default=0.7, min=0.0, max=2.0, step=0.1),
                IO.Int.Input("max_tokens", default=2048, min=1, max=128000, step=128),
                IO.Boolean.Input("is_locked", default=True),
                IO.Combo.Input(
                    "local_unload_policy",
                    options=LOCAL_UNLOAD_POLICIES,
                    default="after_run",
                    tooltip="llama.cpp only. Unload after execution, keep the model resident, or unload it after the configured idle period.",
                ),
                IO.Boolean.Input(
                    "retain_images_in_history",
                    default=False,
                    tooltip="Keep Base64 image data in history_json. Disabled by default to avoid very large workflow data.",
                ),

                IO.Combo.Input("thinking_level", options=["auto", "disabled", "low", "medium", "high"], default="auto"),
                IO.String.Input("image_url", optional=True),
                IO.Boolean.Input("stream", default=False),
            ],
            outputs=[
                IO.String.Output("assistant_response"),
                IO.String.Output("history_json"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def validate_inputs(cls, model_name=None, **kwargs):
        return True

    @classmethod
    def fingerprint_inputs(cls, is_locked=True, **kwargs):
        return _chat_fingerprint(is_locked)

    @classmethod
    def execute(cls, system_prompt_input="", history_json="", images=None, video=None, provider=None, model_name=None, system_prompt="", user_prompt="", temperature=0.7, max_tokens=2048, is_locked=True, local_unload_policy="after_run", retain_images_in_history=False, thinking_level="auto", image_url="", stream=False, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, f"Chatting ({provider})"):
                info = resolve_provider(provider)
                final_system = (system_prompt or "") + ("\n" + system_prompt_input if system_prompt_input else "")
                model_name = model_name if model_name != "click Refresh Models" else (info.get("default_models") or [""])[0]
                client = ApiChatClient(provider=provider, model_name=model_name, api_key=info.get("api_key", ""), base_url=info.get("base_url", ""))
                
                # Gather image tensors from images Autogrow dict/list/tuple
                image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
                if isinstance(images, dict):
                    image_tensors = [t for t in images.values() if t is not None]
                
                # Expand any batched image tensors
                expanded_images = []
                for img in image_tensors:
                    if hasattr(img, "shape") and len(img.shape) == 4 and img.shape[0] > 1:
                        for b in range(img.shape[0]):
                            expanded_images.append(img[b : b + 1])
                    else:
                        expanded_images.append(img)
                
                # Filter out None and keep only valid image tensors
                valid_images = [img for img in expanded_images if img is not None]
                
                res = client.send(
                    user_prompt=user_prompt,
                    system_prompt=final_system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    history_json=history_json,
                    image=valid_images if valid_images else None,
                    image_url=image_url,
                    video=video,
                    stream=stream,
                    thinking_level=thinking_level,
                    retain_images_in_history=retain_images_in_history,
                    local_unload_policy=local_unload_policy,
                )
                return (res[0], res[1])
        except Exception as exc:
            raise RuntimeError(f"LLM Mini API request failed: {exc}")


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


class TranslationNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        providers = chat_provider_names()
        default_provider = providers[0] if providers else ""
        default_models = (resolve_provider(default_provider).get("default_models") or [""]) if default_provider else [""]
        return IO.Schema(
            node_id="LLMMiniTranslation",
            display_name="Translation",
            category="ComfyUI LLM Mini/Translation",
            inputs=[
                IO.String.Input("text", multiline=True, default=""),
                IO.Combo.Input("source_language", options=TRANSLATION_SOURCE_LANGUAGES, default=TRANSLATION_SOURCE_LANGUAGES[0]),
                IO.Combo.Input("target_language", options=TRANSLATION_TARGET_LANGUAGES, default="Chinese"),
                IO.Combo.Input("tone", options=TRANSLATION_TONES, default=TRANSLATION_TONES[0]),
                IO.Int.Input("tone_degree", default=0, min=0, max=10, step=1),
                IO.Combo.Input("provider", options=providers, default=default_provider),
                IO.Combo.Input("model_name", options=default_models, default=default_models[0]),
                IO.Boolean.Input("is_locked", default=True),
                IO.Combo.Input(
                    "local_unload_policy",
                    options=LOCAL_UNLOAD_POLICIES,
                    default="after_run",
                    tooltip="llama.cpp only. Inherit the provider default or override model unloading for this workflow.",
                ),
            ],
            outputs=[IO.String.Output("text")],
            hidden=[IO.Hidden.unique_id],
        )

    @classmethod
    def validate_inputs(cls, model_name=None, **kwargs):
        return True

    @classmethod
    def fingerprint_inputs(cls, is_locked=True, **kwargs):
        return _chat_fingerprint(is_locked)

    @classmethod
    def execute(
        cls,
        text,
        source_language,
        target_language,
        tone,
        tone_degree,
        provider,
        model_name,
        is_locked=True,
        local_unload_policy="after_run",
        unique_id=None,
    ):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, f"Translating ({provider})"):
                info = resolve_provider(provider)
                selected_model = model_name if model_name != "click Refresh Models" else (info.get("default_models") or [""])[0]
                system_prompt = _render_translation_prompt(
                    source_language=source_language,
                    target_language=target_language,
                    tone=tone,
                    tone_degree=tone_degree,
                )
                client = ApiChatClient(
                    provider=provider,
                    model_name=selected_model,
                    api_key=info.get("api_key", ""),
                    base_url=info.get("base_url", ""),
                )
                response, _, _ = client.send(
                    user_prompt=text,
                    system_prompt=system_prompt,
                    temperature=0.2,
                    max_tokens=8192,
                    local_unload_policy=local_unload_policy,
                )
                return IO.NodeOutput(response)
        except Exception as exc:
            raise RuntimeError(f"LLM Mini translation request failed: {exc}")


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
