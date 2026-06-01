from __future__ import annotations

from uuid import uuid4

from comfy_api.latest import IO
from ..core.config import provider_names, resolve_provider
from ..core.persona import load_persona_text
from ..providers.openai_compatible import ApiChatClient
from ..core.status import StatusUpdater, get_unique_id


def _chat_fingerprint(is_locked=True):
    return "locked" if is_locked else uuid4().hex


class ApiChatNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        providers = provider_names()
        return IO.Schema(
            node_id="LLMMiniApiChat",
            display_name="API Chat",
            category="ComfyUI LLM Mini/Chat",
            inputs=[
                IO.String.Input("system_prompt_input", optional=True, force_input=True),
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
                IO.Combo.Input("provider", options=providers, default=providers[0] if providers else ""),
                IO.Combo.Input("model_name", options=["click Refresh Models"], default="click Refresh Models"),
                IO.String.Input("system_prompt", multiline=True, default=""),
                IO.String.Input("user_prompt", multiline=True, default=""),
                IO.Float.Input("temperature", default=0.7, min=0.0, max=2.0, step=0.1),
                IO.Int.Input("max_tokens", default=2048, min=1, max=128000, step=128),
                IO.Boolean.Input("is_locked", default=True),

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
    def execute(cls, system_prompt_input="", images=None, provider=None, model_name=None, system_prompt="", user_prompt="", temperature=0.7, max_tokens=2048, is_locked=True, thinking_level="auto", image_url="", stream=False):
        node_id = get_unique_id(cls)
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
                    history_json="",
                    image=valid_images if valid_images else None,
                    image_url=image_url,
                    stream=stream,
                    thinking_level=thinking_level
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
