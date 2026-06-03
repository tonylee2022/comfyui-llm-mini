from __future__ import annotations

from comfy_api.latest import IO

from ..core.config import resolve_provider
from ..providers.images import codex_image, openai_image, google_imagen_generate, google_gemini_image_generate
from ..providers.xai import xai_image
from ..core.status import StatusUpdater, get_unique_id


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
            category="ComfyUI LLM Mini/Image/OpenAI",
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
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, execution_backend, model_name, size, quality, background, n, seed, images=None, mask=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
        if isinstance(images, dict):
            image_tensors = [t for t in images.values() if t is not None]
        try:
            with StatusUpdater(node_id, f"Generating ({execution_backend.upper()})") as updater:
                if execution_backend == "codex":
                    res = codex_image(prompt, model_name, size, image_tensors)
                else:
                    res = openai_image(prompt, model_name, size, quality, background, n, seed, image_tensors, mask, status_updater=updater)
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
            category="ComfyUI LLM Mini/Image/xAI",
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
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, seed, images=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        info = resolve_provider("xai")
        api_key = info.get("api_key", "")
        image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
        if isinstance(images, dict):
            image_tensors = [t for t in images.values() if t is not None]
        try:
            with StatusUpdater(node_id, "Generating (xAI Imagine)") as updater:
                res = xai_image(prompt, model_name, aspect_ratio, resolution, api_key, "", image_tensors, seed=seed, status_updater=updater)
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
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model_name",
                    options=["imagen-4.0-generate-001", "imagen-4.0-fast-generate-001", "imagen-4.0-ultra-generate-001"],
                    default="imagen-4.0-generate-001",
                ),
                IO.Combo.Input("aspect_ratio", options=["1:1", "3:4", "4:3", "9:16", "16:9"], default="1:1"),
                IO.Combo.Input("resolution", options=["Default", "512", "1K", "2K"], default="1K"),
                IO.Combo.Input("quality", options=["jpeg", "png"], default="jpeg"),
                IO.Int.Input("n", default=1, min=1, max=4, step=1, tooltip="Only valid for Imagen models."),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, quality, n, seed, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, "Generating (Google Imagen)"):
                info = resolve_provider("google")
                api_key = info.get("api_key", "")
                base_url = info.get("base_url", "")
                res = google_imagen_generate(prompt, model_name, aspect_ratio, resolution, quality, seed, api_key, base_url=base_url, n=n)
                return (res,)
        except Exception as exc:
            _format_error("Google Imagen", exc)
            return (_error_image(),)


GEMINI_IMAGE_SYS_PROMPT = (
    "You are an expert image-generation engine. You must ALWAYS produce an image.\n"
    "Interpret all user input—regardless of "
    "format, intent, or abstraction—as literal visual directives for image composition.\n"
    "If a prompt is conversational or lacks specific visual details, "
    "you must creatively invent a concrete visual scenario that depicts the concept.\n"
    "Prioritize generating the visual representation above any text, formatting, or conversational requests."
)


class GoogleGeminiNanoBananaNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleGeminiNanoBanana",
            display_name="Nano Banana",
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model",
                    options=["gemini-2.5-flash-image"],
                    default="gemini-2.5-flash-image",
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
                IO.String.Input("files", optional=True, tooltip="Optional reference text or files content."),
                IO.Combo.Input("aspect_ratio", options=["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"], default="auto"),
                IO.Combo.Input("response_modalities", options=["IMAGE", "IMAGE+TEXT"], default="IMAGE"),
                IO.String.Input("system_prompt", multiline=True, default=GEMINI_IMAGE_SYS_PROMPT, optional=True),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
            ],
            outputs=[
                IO.Image.Output("image"),
                IO.String.Output("text"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model, aspect_ratio, response_modalities, system_prompt, seed, images=None, files=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, "Generating (Google Gemini)") as updater:
                info = resolve_provider("google")
                api_key = info.get("api_key", "")
                base_url = info.get("base_url", "")
                
                image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
                if isinstance(images, dict):
                    image_tensors = [t for t in images.values() if t is not None]

                res_image, res_text = google_gemini_image_generate(
                    prompt=prompt,
                    model=model,
                    image_tensors=image_tensors,
                    files=files,
                    aspect_ratio=aspect_ratio,
                    resolution=None,
                    response_modalities=response_modalities,
                    seed=seed,
                    api_key=api_key,
                    base_url=base_url,
                    system_prompt=system_prompt,
                    status_updater=updater
                )
                return (res_image, res_text)
        except Exception as exc:
            _format_error("Nano Banana", exc)
            return (_error_image(), str(exc))


class GoogleGeminiNanoBananaProNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleGeminiNanoBananaPro",
            display_name="Nano Banana Pro",
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model",
                    options=["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"],
                    default="gemini-3-pro-image-preview",
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
                IO.String.Input("files", optional=True, tooltip="Optional reference text or files content."),
                IO.Combo.Input("aspect_ratio", options=["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"], default="auto"),
                IO.Combo.Input("resolution", options=["1K", "2K", "4K"], default="1K"),
                IO.Combo.Input("response_modalities", options=["IMAGE+TEXT", "IMAGE"], default="IMAGE+TEXT"),
                IO.String.Input("system_prompt", multiline=True, default=GEMINI_IMAGE_SYS_PROMPT, optional=True),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
            ],
            outputs=[
                IO.Image.Output("image"),
                IO.String.Output("text"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model, aspect_ratio, resolution, response_modalities, system_prompt, seed, images=None, files=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, "Generating (Google Gemini Pro)") as updater:
                info = resolve_provider("google")
                api_key = info.get("api_key", "")
                base_url = info.get("base_url", "")

                image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
                if isinstance(images, dict):
                    image_tensors = [t for t in images.values() if t is not None]

                res_image, res_text = google_gemini_image_generate(
                    prompt=prompt,
                    model=model,
                    files=files,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    response_modalities=response_modalities,
                    seed=seed,
                    api_key=api_key,
                    base_url=base_url,
                    system_prompt=system_prompt,
                    status_updater=updater
                )
                return (res_image, res_text)
        except Exception as exc:
            _format_error("Nano Banana Pro", exc)
            return (_error_image(), str(exc))


class GoogleGeminiNanoBanana2Node(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleGeminiNanoBanana2",
            display_name="Nano Banana 2",
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model",
                    options=["gemini-3.1-flash-image-preview"],
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
                IO.String.Input("files", optional=True, tooltip="Optional reference text or files content."),
                IO.Combo.Input("aspect_ratio", options=["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"], default="auto"),
                IO.Combo.Input("resolution", options=["1K", "2K", "4K"], default="1K"),
                IO.Combo.Input("response_modalities", options=["IMAGE", "IMAGE+TEXT"], default="IMAGE"),
                IO.Combo.Input("thinking_level", options=["MINIMAL", "HIGH"], default="MINIMAL"),
                IO.String.Input("system_prompt", multiline=True, default=GEMINI_IMAGE_SYS_PROMPT, optional=True),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True),
            ],
            outputs=[
                IO.Image.Output("image"),
                IO.String.Output("text"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model, aspect_ratio, resolution, response_modalities, thinking_level, system_prompt, seed, images=None, files=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, "Generating (Google Nano Banana 2)") as updater:
                info = resolve_provider("google")
                api_key = info.get("api_key", "")
                base_url = info.get("base_url", "")

                image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
                if isinstance(images, dict):
                    image_tensors = [t for t in images.values() if t is not None]

                res_image, res_text = google_gemini_image_generate(
                    prompt=prompt,
                    model=model,
                    files=files,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    response_modalities=response_modalities,
                    seed=seed,
                    api_key=api_key,
                    base_url=base_url,
                    thinking_level=thinking_level,
                    system_prompt=system_prompt,
                    status_updater=updater
                )
                return (res_image, res_text)
        except Exception as exc:
            _format_error("Nano Banana 2", exc)
            return (_error_image(), str(exc))
