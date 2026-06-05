from __future__ import annotations

import requests

from comfy_api.latest import IO

from ...core.config import resolve_provider
from ...core.http_logging import log_http_response
from ...core.interrupt import check_interrupted
from ...core.status import StatusUpdater, get_unique_id
from ._shared import error_image, format_error, image_sources_to_batch, image_tensors_from_input, normalize_image_model, tensor_mask_png_file, tensor_png_file


def openai_image(prompt: str, model: str, size: str, quality: str, background: str, n: int, seed: int, image_tensors=None, mask=None, status_updater=None):
    check_interrupted()
    image_tensors = [t for t in (image_tensors or []) if t is not None]
    model = normalize_image_model(model, background)
    info = resolve_provider("openai")
    api_key = info.get("api_key", "")
    base_url = info.get("base_url", "")
    if not api_key:
        raise RuntimeError("No OpenAI API key found.")
    if not base_url:
        base_url = "https://api.openai.com/v1/"
    if not base_url.endswith("/"):
        base_url += "/"
    headers = {"Authorization": f"Bearer {api_key}"}
    if image_tensors:
        data = {"model": model, "prompt": prompt, "n": str(n), "size": size, "quality": quality, "background": background}
        files = []
        total_imgs = len(image_tensors)
        for i, t in enumerate(image_tensors):
            check_interrupted()
            if status_updater:
                status_updater.update_status(f"Uploading image {i + 1}/{total_imgs}")
            files.append(("image" if total_imgs == 1 else "image[]", tensor_png_file(t, f"image_{i}.png")))
        if mask is not None:
            files.append(("mask", tensor_mask_png_file(image_tensors[0], mask)))
        if status_updater:
            status_updater.update_status("Generating")
        check_interrupted()
        url = base_url + "images/edits"
        response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    else:
        payload = {"model": model, "prompt": prompt, "n": n, "size": size, "quality": quality, "background": background}
        url = base_url + "images/generations"
        check_interrupted()
        response = requests.post(url, headers=headers, json=payload, timeout=120)
    log_http_response("POST", url, response)
    check_interrupted()
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI image error HTTP {response.status_code}: {response.text}")
    values = [item.get("url") or item.get("b64_json") for item in response.json().get("data", []) if item.get("url") or item.get("b64_json")]
    if not values:
        raise RuntimeError("Image response did not contain image data.")
    tensor_batch, sources = image_sources_to_batch(values)
    return tensor_batch, sources[0]


class OpenAIImageNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniOpenAIImage",
            display_name="OpenAI Image",
            category="ComfyUI LLM Mini/Image/OpenAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model_name",
                    options=["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"],
                    default="gpt-image-2",
                    tooltip="GPT Image model for OpenAI direct image generation and edits.",
                ),
                IO.Combo.Input(
                    "size",
                    options=["auto", "1024x1024", "1024x1536", "1536x1024", "2048x2048", "2048x1152", "1152x2048", "3840x2160", "2160x3840"],
                    default="auto",
                ),
                IO.Combo.Input("quality", options=["low", "medium", "high"], default="low"),
                IO.Combo.Input("background", options=["auto", "opaque", "transparent"], default="auto"),
                IO.Int.Input("n", default=1, min=1, max=8, step=1, tooltip="Number of images to generate."),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Cache and re-execution control only; not sent to OpenAI."),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 17)],
                        min=0,
                    ),
                    tooltip="Optional reference images. Add image inputs dynamically as needed.",
                ),
                IO.Mask.Input("mask", optional=True, tooltip="OpenAI image edit mask. Mask value 1 marks the region to edit."),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, size, quality, background, n, seed, images=None, mask=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        image_tensors = image_tensors_from_input(images)
        try:
            with StatusUpdater(node_id, "Generating (OpenAI)") as updater:
                res = openai_image(prompt, model_name, size, quality, background, n, seed, image_tensors, mask, status_updater=updater)
                return (res[0],)
        except Exception as exc:
            format_error("OpenAI image", exc)
            return (error_image(),)


NODE_CLASS_MAPPINGS = {
    "LLMMiniOpenAIImage": OpenAIImageNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniOpenAIImage": "OpenAI Image",
}
