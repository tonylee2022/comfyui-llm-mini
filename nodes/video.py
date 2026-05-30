from __future__ import annotations

from comfy_api.latest import IO

from ..core.config import CREDENTIAL_SOURCE_API_KEY, credential_input, credential_sources_for_provider
from ..providers.xai import xai_video, xai_video_edit, xai_video_extend, xai_video_reference


class XAIVideoNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model_name": (["grok-imagine-video"], {"default": "grok-imagine-video"}),
                "aspect_ratio": (["auto", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"], {"default": "auto"}),
                "resolution": (["720p", "480p"], {"default": "720p"}),
                "duration": ("INT", {"default": 6, "min": 1, "max": 15, "step": 1}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1}),
            },
            "optional": {
                "image": ("IMAGE",),
                "credential_source": (credential_sources_for_provider("xai"), {"default": CREDENTIAL_SOURCE_API_KEY}),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "generate"
    CATEGORY = "ComfyUI LLM Mini/Video"

    def generate(self, prompt, model_name, aspect_ratio, resolution, duration, seed, image=None, credential_source=CREDENTIAL_SOURCE_API_KEY):
        api_key = credential_input("xai", credential_source)
        res = xai_video(prompt, model_name, aspect_ratio, resolution, duration, seed, api_key, "", image)
        return (res[0],)


class XAIVideoReferenceNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoReference",
            display_name="xAI Multi-Reference Video",
            category="ComfyUI LLM Mini/Video",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Combo.Input("aspect_ratio", options=["auto", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"], default="auto"),
                IO.Combo.Input("resolution", options=["720p", "480p"], default="720p"),
                IO.Int.Input("duration", default=6, min=1, max=15, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 17)],
                        min=0,
                    ),
                    tooltip="Reference images. Add image inputs dynamically as needed.",
                ),
                IO.Combo.Input("credential_source", options=credential_sources_for_provider("xai"), default=CREDENTIAL_SOURCE_API_KEY),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, duration, seed, images=None, credential_source=CREDENTIAL_SOURCE_API_KEY):
        api_key = credential_input("xai", credential_source)
        refs = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
        if isinstance(images, dict):
            refs = [t for t in images.values() if t is not None]
        try:
            res = xai_video_reference(prompt, model_name, aspect_ratio, resolution, duration, seed, api_key, "", refs)
            return IO.NodeOutput(res[0])
        except Exception as exc:
            message = f"LLM Mini xAI video reference request failed: {exc}"
            print(f"[LLM Mini] {message}", flush=True)
            return IO.NodeOutput(None)


class XAIVideoEditNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"prompt": ("STRING", {"multiline": True, "default": ""}), "model_name": (["grok-imagine-video"], {"default": "grok-imagine-video"}), "video": ("VIDEO",), "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1})},
            "optional": {"credential_source": (credential_sources_for_provider("xai"), {"default": CREDENTIAL_SOURCE_API_KEY})},
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "edit"
    CATEGORY = "ComfyUI LLM Mini/Video"

    def edit(self, prompt, model_name, video, seed, credential_source=CREDENTIAL_SOURCE_API_KEY):
        api_key = credential_input("xai", credential_source)
        res = xai_video_edit(prompt, model_name, video, seed, api_key, "")
        return (res[0],)


class XAIVideoExtendNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"prompt": ("STRING", {"multiline": True, "default": ""}), "model_name": (["grok-imagine-video"], {"default": "grok-imagine-video"}), "video": ("VIDEO",), "duration": ("INT", {"default": 8, "min": 2, "max": 10, "step": 1}), "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1})},
            "optional": {"credential_source": (credential_sources_for_provider("xai"), {"default": CREDENTIAL_SOURCE_API_KEY})},
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "extend"
    CATEGORY = "ComfyUI LLM Mini/Video"

    def extend(self, prompt, model_name, video, duration, seed, credential_source=CREDENTIAL_SOURCE_API_KEY):
        api_key = credential_input("xai", credential_source)
        res = xai_video_extend(prompt, model_name, video, duration, seed, api_key, "")
        return (res[0],)
