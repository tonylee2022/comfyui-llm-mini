from __future__ import annotations

from comfy_api.latest import IO

from ..core.config import CREDENTIAL_SOURCE_API_KEY, credential_input, credential_sources_for_provider, resolve_provider
from ..providers.images import codex_image, openai_image, google_imagen_generate, google_image_edit
from ..providers.xai import xai_image


def _error_image():
    import torch

    image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
    image[:, :, :, 0] = 0.85
    image[:, 0:4, :, :] = 1.0
    image[:, -4:, :, :] = 1.0
    image[:, :, 0:4, :] = 1.0
    image[:, :, -4:, :] = 1.0
    return image


def _format_error(label: str, exc: Exception) -> str:
    message = f"LLM Mini {label} request failed: {exc}"
    print(f"[LLM Mini] {message}", flush=True)
    return message


class OpenAICodexImageNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniOpenAICodexImage",
            display_name="OpenAI/Codex Image",
            category="ComfyUI LLM Mini/Image",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("execution_backend", options=["openai", "codex"], default="openai"),
                IO.Combo.Input("model_name", options=["gpt-image-2", "gpt-image-1.5", "gpt-image-1"], default="gpt-image-2"),
                IO.Combo.Input(
                    "size",
                    options=["auto", "1024x1024", "1024x1536", "1536x1024", "2048x2048", "2048x1152", "1152x2048", "3840x2160", "2160x3840"],
                    default="auto",
                ),
                IO.Combo.Input("quality", options=["low", "medium", "high"], default="low"),
                IO.Combo.Input("background", options=["auto", "opaque", "transparent"], default="auto"),
                IO.Int.Input("n", default=1, min=1, max=8, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 17)],
                        min=0,
                    ),
                    tooltip="Optional reference images. Add image inputs dynamically as needed.",
                ),
                IO.Mask.Input("mask", optional=True),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
        )

    @classmethod
    def execute(cls, prompt, execution_backend, model_name, size, quality, background, n, seed, images=None, mask=None):
        image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
        if isinstance(images, dict):
            image_tensors = [t for t in images.values() if t is not None]
        try:
            if execution_backend == "codex":
                res = codex_image(prompt, model_name, size, image_tensors)
            else:
                res = openai_image(prompt, model_name, size, quality, background, n, seed, image_tensors, mask)
            return (res[0],)
        except Exception as exc:
            _format_error("OpenAI/Codex image", exc)
            return (_error_image(),)


class XAIImagineNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIImagine",
            display_name="xAI Imagine",
            category="ComfyUI LLM Mini/Image",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-image-quality", "grok-imagine-image"], default="grok-imagine-image-quality"),
                IO.Combo.Input("aspect_ratio", options=["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"], default="1:1"),
                IO.Combo.Input("resolution", options=["1k", "2k"], default="1k"),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 17)],
                        min=0,
                    ),
                    tooltip="Optional reference images. Add image inputs dynamically as needed.",
                ),
                IO.Combo.Input("credential_source", options=credential_sources_for_provider("xai"), default=CREDENTIAL_SOURCE_API_KEY),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, seed, images=None, credential_source=CREDENTIAL_SOURCE_API_KEY):
        api_key = credential_input("xai", credential_source)
        image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
        if isinstance(images, dict):
            image_tensors = [t for t in images.values() if t is not None]
        try:
            res = xai_image(prompt, model_name, aspect_ratio, resolution, api_key, "", image_tensors, seed=seed)
            return (res[0],)
        except Exception as exc:
            _format_error("xAI image", exc)
            return (_error_image(),)


class GoogleImagenNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleImagen",
            display_name="Google Imagen",
            category="ComfyUI LLM Mini/Image",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model_name",
                    options=["gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview", "imagen-4.0-generate-001", "imagen-4.0-fast-generate-001", "imagen-4.0-ultra-generate-001"],
                    default="gemini-3.1-flash-image-preview",
                ),
                IO.Combo.Input("aspect_ratio", options=["1:1", "16:9", "9:16", "4:3", "3:4"], default="1:1"),
                IO.Combo.Input("resolution", options=["512", "1K", "2K", "4K"], default="1K"),
                IO.Combo.Input("quality", options=["jpeg", "png"], default="jpeg"),
                IO.Int.Input("n", default=1, min=1, max=4, step=1, tooltip="Only valid for Imagen models."),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
                IO.Combo.Input("credential_source", options=credential_sources_for_provider("google"), default=CREDENTIAL_SOURCE_API_KEY),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, quality, n, seed, credential_source=CREDENTIAL_SOURCE_API_KEY):
        ident = credential_input("google", credential_source)
        info = resolve_provider("google", ident)
        api_key = info.get("api_key", "")
        base_url = info.get("base_url", "")
        try:
            res = google_imagen_generate(prompt, model_name, aspect_ratio, resolution, quality, seed, api_key, base_url=base_url, n=n)
            return (res,)
        except Exception as exc:
            _format_error("Google Imagen", exc)
            return (_error_image(),)


class GoogleImageEditNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleImageEdit",
            display_name="Google Image Edit",
            category="ComfyUI LLM Mini/Image",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model_name",
                    options=["gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"],
                    default="gemini-3.1-flash-image-preview",
                ),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 17)],
                        min=0,
                    ),
                    tooltip="Optional reference images. Add image inputs dynamically as needed.",
                ),
                IO.Combo.Input("aspect_ratio", options=["1:1", "16:9", "9:16", "4:3", "3:4"], default="1:1"),
                IO.Combo.Input("resolution", options=["512", "1K", "2K", "4K"], default="1K"),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
                IO.Combo.Input("credential_source", options=credential_sources_for_provider("google"), default=CREDENTIAL_SOURCE_API_KEY),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, seed, images=None, credential_source=CREDENTIAL_SOURCE_API_KEY):
        ident = credential_input("google", credential_source)
        info = resolve_provider("google", ident)
        api_key = info.get("api_key", "")
        base_url = info.get("base_url", "")
        
        image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
        if isinstance(images, dict):
            image_tensors = [t for t in images.values() if t is not None]
            
        try:
            res = google_image_edit(prompt, model_name, image_tensors, aspect_ratio, resolution, seed, api_key, base_url=base_url)
            return (res,)
        except Exception as exc:
            _format_error("Google Image Edit", exc)
            return (_error_image(),)
