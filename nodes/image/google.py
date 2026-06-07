from __future__ import annotations

from comfy_api.latest import IO

from ...core.config import resolve_provider
from ...core.interrupt import check_interrupted
from ...core.status import StatusUpdater, get_unique_id
from ._shared import error_image, format_error, image_tensors_from_input


def google_imagen_generate(prompt: str, model: str, aspect_ratio: str, resolution: str, quality: str, seed: int, api_key: str, base_url: str = "", n: int = 1):
    check_interrupted()
    if not api_key:
        raise RuntimeError("No Google API key found. Please configure it in config.ini or environment variables.")

    from google import genai
    from google.genai import types
    import numpy as np
    import torch
    from PIL import Image

    client_kwargs = {"api_key": api_key}
    http_options: dict = {"timeout": 120_000}
    if base_url:
        http_options["base_url"] = base_url
    client_kwargs["http_options"] = http_options
    client = genai.Client(**client_kwargs)

    real_mime = f"image/{quality}" if quality in ["jpeg", "png"] else "image/jpeg"
    tensors = []

    if model.startswith("gemini"):
        image_size_val = None if resolution == "Default" else resolution
        aspect_ratio_val = None if aspect_ratio == "auto" else aspect_ratio

        image_config_kwargs = {}
        if image_size_val:
            image_config_kwargs["image_size"] = image_size_val
        if aspect_ratio_val:
            image_config_kwargs["aspect_ratio"] = aspect_ratio_val

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(**image_config_kwargs) if image_config_kwargs else None,
            seed=seed,
        )
        check_interrupted()
        response = client.models.generate_content(model=model, contents=prompt, config=config)
        check_interrupted()

        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None) or getattr(candidate, "finishReason", None)
            if finish_reason:
                finish_reason_str = str(finish_reason).upper()
                if "IMAGE_PROHIBITED_CONTENT" in finish_reason_str or "SAFETY" in finish_reason_str or "BLOCK" in finish_reason_str:
                    raise RuntimeError(f"Gemini API blocked the request. Reason: {finish_reason}")

        if response.parts:
            for part in response.parts:
                img_data = part.as_image()
                if img_data is not None:
                    import io

                    pil_img = Image.open(io.BytesIO(img_data.image_bytes)).convert("RGB")
                    arr = np.array(pil_img).astype(np.float32) / 255.0
                    tensors.append(torch.from_numpy(arr).unsqueeze(0))
    else:
        if aspect_ratio not in ["1:1", "3:4", "4:3", "9:16", "16:9"]:
            aspect_ratio = "1:1"
        res_map = {"512": "1k", "1K": "1k", "2K": "2k", "4K": "4k"}
        mapped_size = res_map.get(resolution, "1k")
        config_kwargs = {
            "number_of_images": n,
            "aspect_ratio": aspect_ratio,
            "output_mime_type": real_mime,
        }
        if "fast" not in model.lower():
            config_kwargs["image_size"] = mapped_size
        config = types.GenerateImagesConfig(**config_kwargs)
        check_interrupted()
        response = client.models.generate_images(model=model, prompt=prompt, config=config)
        check_interrupted()
        if response.generated_images:
            for gen_img in response.generated_images:
                import io

                pil_img = Image.open(io.BytesIO(gen_img.image.image_bytes)).convert("RGB")
                arr = np.array(pil_img).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(arr).unsqueeze(0))

    if not tensors:
        raise RuntimeError("Google image generation did not return any image data.")
    return torch.cat(tensors, dim=0)


def google_gemini_image_generate(
    prompt: str,
    model: str,
    image_tensors: list | None,
    files: str | None,
    aspect_ratio: str,
    resolution: str | None,
    response_modalities: str,
    seed: int,
    api_key: str,
    base_url: str = "",
    thinking_level: str | None = None,
    system_prompt: str = "",
    status_updater=None,
):
    check_interrupted()
    if not api_key:
        raise RuntimeError("No Google API key found. Please configure it in config.ini or environment variables.")

    from google import genai
    from google.genai import types
    from PIL import Image
    import numpy as np
    import torch
    import io

    client_kwargs = {"api_key": api_key}
    http_options: dict = {"timeout": 300_000}
    if base_url:
        http_options["base_url"] = base_url
    client_kwargs["http_options"] = http_options
    client = genai.Client(**client_kwargs)

    contents = []
    flat_images = []
    if image_tensors:
        for tensor in image_tensors:
            check_interrupted()
            if tensor is None:
                continue
            from ...core.media import downscale_image_tensor

            downscaled = downscale_image_tensor(tensor)
            for i in range(downscaled.shape[0]):
                flat_images.append(downscaled[i])

        if len(flat_images) > 14:
            raise ValueError("The current maximum number of supported reference images is 14.")

        total_imgs = len(flat_images)
        for idx, single_tensor in enumerate(flat_images):
            check_interrupted()
            if status_updater:
                status_updater.update_status(f"Uploading image {idx + 1}/{total_imgs}")
            arr = (single_tensor.detach().cpu().numpy() * 255).astype("uint8")
            pil_image = Image.fromarray(arr)
            contents.append(pil_image)

    if files and isinstance(files, str) and files.strip():
        contents.append(files)

    if prompt:
        if response_modalities != "IMAGE":
            prompt_with_suffix = prompt + " (Also, provide a detailed description of the generated image. 并且请提供生成图像的详细描述。)"
            contents.append(prompt_with_suffix)
        else:
            contents.append(prompt)

    if not contents:
        raise RuntimeError("No input provided (neither prompt, files nor reference images).")

    if status_updater:
        status_updater.update_status("Generating")

    image_config_kwargs = {}
    if resolution and resolution != "Default":
        image_config_kwargs["image_size"] = resolution
    if aspect_ratio and aspect_ratio != "auto":
        image_config_kwargs["aspect_ratio"] = aspect_ratio

    config_kwargs = {
        "response_modalities": ["IMAGE"] if response_modalities == "IMAGE" else ["TEXT", "IMAGE"],
        "seed": seed,
    }
    if image_config_kwargs:
        config_kwargs["image_config"] = types.ImageConfig(**image_config_kwargs)

    if thinking_level:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=thinking_level.lower(),
            include_thoughts=True,
        )

    if response_modalities != "IMAGE":
        additional_sys = "\nSince response_modalities includes TEXT, you MUST also provide a text description of the generated image or answer the query."
        if system_prompt:
            if additional_sys not in system_prompt:
                system_prompt += additional_sys
        else:
            system_prompt = additional_sys

    if system_prompt:
        config_kwargs["system_instruction"] = system_prompt

    config = types.GenerateContentConfig(**config_kwargs)
    check_interrupted()
    response = client.models.generate_content(model=model, contents=contents, config=config)
    check_interrupted()

    tensors = []
    texts = []

    if response.candidates:
        candidate = response.candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None) or getattr(candidate, "finishReason", None)
        if finish_reason:
            finish_reason_str = str(finish_reason).upper()
            if "IMAGE_PROHIBITED_CONTENT" in finish_reason_str or "SAFETY" in finish_reason_str or "BLOCK" in finish_reason_str:
                raise RuntimeError(f"Gemini API blocked the request. Reason: {finish_reason}")

    parts = []
    if response.candidates and len(response.candidates) > 0:
        candidate = response.candidates[0]
        if candidate.content and candidate.content.parts:
            parts = candidate.content.parts
    if not parts and response.parts:
        parts = response.parts

    for part in parts:
        if part.text:
            texts.append(part.text)
        if getattr(part, "thought", False):
            continue

        img_data = None
        try:
            img_data = part.as_image()
        except Exception:
            pass

        if img_data is not None:
            pil_img = Image.open(io.BytesIO(img_data.image_bytes)).convert("RGB")
            arr = np.array(pil_img).astype(np.float32) / 255.0
            tensors.append(torch.from_numpy(arr).unsqueeze(0))

    text_res = "\n".join(texts) if texts else ""

    if tensors:
        final_image = torch.cat(tensors, dim=0)
    else:
        final_image = torch.zeros((1, 1024, 1024, 3), dtype=torch.float32)

    return final_image, text_res


GEMINI_IMAGE_SYS_PROMPT = (
    "You are an expert image-generation engine. You must ALWAYS produce an image.\n"
    "Interpret all user input—regardless of "
    "format, intent, or abstraction—as literal visual directives for image composition.\n"
    "If a prompt is conversational or lacks specific visual details, "
    "you must creatively invent a concrete visual scenario that depicts the concept.\n"
    "Prioritize generating the visual representation above any text, formatting, or conversational requests."
)


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
            format_error("Google Imagen", exc)
            raise exc


class BaseGeminiImageNode(IO.ComfyNode):
    @classmethod
    def execute_gemini_image(
        cls,
        node_name: str,
        status_title: str,
        prompt: str,
        model: str,
        aspect_ratio: str,
        response_modalities: str,
        system_prompt: str,
        seed: int,
        images = None,
        files = None,
        resolution: str | None = None,
        thinking_level: str | None = None,
        unique_id: str | None = None,
    ):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, status_title) as updater:
                info = resolve_provider("google")
                res_image, res_text = google_gemini_image_generate(
                    prompt=prompt,
                    model=model,
                    image_tensors=image_tensors_from_input(images),
                    files=files,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    response_modalities=response_modalities,
                    seed=seed,
                    api_key=info.get("api_key", ""),
                    base_url=info.get("base_url", ""),
                    thinking_level=thinking_level,
                    system_prompt=system_prompt,
                    status_updater=updater,
                )
                return (res_image, res_text)
        except Exception as exc:
            format_error(node_name, exc)
            raise exc


class GoogleGeminiNanoBananaNode(BaseGeminiImageNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleGeminiNanoBanana",
            display_name="Nano Banana",
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model", options=["gemini-2.5-flash-image"], default="gemini-2.5-flash-image"),
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
        return cls.execute_gemini_image(
            node_name="Nano Banana",
            status_title="Generating (Google Gemini)",
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            response_modalities=response_modalities,
            system_prompt=system_prompt,
            seed=seed,
            images=images,
            files=files,
            unique_id=unique_id,
        )


class GoogleGeminiNanoBananaProNode(BaseGeminiImageNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleGeminiNanoBananaPro",
            display_name="Nano Banana Pro",
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model", options=["gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"], default="gemini-3-pro-image-preview"),
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
        return cls.execute_gemini_image(
            node_name="Nano Banana Pro",
            status_title="Generating (Google Gemini Pro)",
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            response_modalities=response_modalities,
            system_prompt=system_prompt,
            seed=seed,
            images=images,
            files=files,
            unique_id=unique_id,
        )


class GoogleGeminiNanoBanana2Node(BaseGeminiImageNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleGeminiNanoBanana2",
            display_name="Nano Banana 2",
            category="ComfyUI LLM Mini/Image/Google",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model", options=["gemini-3.1-flash-image-preview"], default="gemini-3.1-flash-image-preview"),
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
        return cls.execute_gemini_image(
            node_name="Nano Banana 2",
            status_title="Generating (Google Nano Banana 2)",
            prompt=prompt,
            model=model,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            response_modalities=response_modalities,
            thinking_level=thinking_level,
            system_prompt=system_prompt,
            seed=seed,
            images=images,
            files=files,
            unique_id=unique_id,
        )


NODE_CLASS_MAPPINGS = {
    "LLMMiniGoogleImagen": GoogleImagenNode,
    "LLMMiniGoogleGeminiNanoBanana": GoogleGeminiNanoBananaNode,
    "LLMMiniGoogleGeminiNanoBananaPro": GoogleGeminiNanoBananaProNode,
    "LLMMiniGoogleGeminiNanoBanana2": GoogleGeminiNanoBanana2Node,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniGoogleImagen": "Google Imagen",
    "LLMMiniGoogleGeminiNanoBanana": "Nano Banana",
    "LLMMiniGoogleGeminiNanoBananaPro": "Nano Banana Pro",
    "LLMMiniGoogleGeminiNanoBanana2": "Nano Banana 2",
}
