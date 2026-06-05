from __future__ import annotations

import requests

from comfy_api.latest import IO

from ...core.config import resolve_provider
from ...core.http_logging import log_http_response
from ...core.interrupt import check_interrupted
from ...core.media import tensor_to_data_uri
from ...core.status import StatusUpdater, get_unique_id
from ...core.xai import _parse_xai_error, xai_credentials
from ._shared import error_image, format_error, image_sources_to_batch, image_tensors_from_input


XAI_IMAGE_MODELS = ["grok-imagine-image-quality", "grok-imagine-image"]
XAI_ASPECT_RATIOS = ["auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20"]
XAI_RESOLUTIONS = ["1k", "2k"]
XAI_MIME_TYPES = ["image/png", "image/jpeg"]


def _xai_image_request(endpoint: str, payload: dict, api_key: str, base_url: str):
    check_interrupted()
    key, base = xai_credentials(api_key, base_url)
    if not key:
        raise RuntimeError("No xAI API key or OAuth token found.")
    url = base + endpoint
    check_interrupted()
    response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    log_http_response("POST", url, response)
    check_interrupted()
    if response.status_code != 200:
        raise RuntimeError(_parse_xai_error(response))
    values = [item.get("url") or item.get("b64_json") for item in response.json().get("data", []) if item.get("url") or item.get("b64_json")]
    if not values:
        raise RuntimeError("xAI image response did not contain image data.")
    tensor_batch, sources = image_sources_to_batch(values)
    return tensor_batch, sources[0]


def xai_image_generate(prompt: str, model: str, aspect_ratio: str, resolution: str, mime_type: str, n: int, api_key: str, base_url: str):
    payload = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "response_format": "url",
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "mime_type": mime_type,
    }
    return _xai_image_request("images/generations", payload, api_key, base_url)


def xai_image_edit(prompt: str, model: str, aspect_ratio: str, resolution: str, mime_type: str, n: int, api_key: str, base_url: str, image_tensors=None, status_updater=None):
    tensors = [t for t in (image_tensors or []) if t is not None]
    if not tensors:
        raise RuntimeError("xAI image edit requires at least one source image.")
    if len(tensors) > 3:
        raise RuntimeError("xAI image edit supports up to 3 source images.")
    images = []
    total_imgs = len(tensors)
    for i, t in enumerate(tensors):
        check_interrupted()
        if status_updater:
            status_updater.update_status(f"Uploading image {i + 1}/{total_imgs}")
        images.append({"type": "image_url", "url": tensor_to_data_uri(t)})
    if status_updater:
        status_updater.update_status("Generating")
    payload = {
        "model": model,
        "prompt": prompt,
        "n": n,
        "response_format": "url",
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "mime_type": mime_type,
    }
    payload["image" if len(images) == 1 else "images"] = images[0] if len(images) == 1 else images
    return _xai_image_request("images/edits", payload, api_key, base_url)


class XAIImagineNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIImagine",
            display_name="xAI Imagine",
            category="ComfyUI LLM Mini/Image/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=XAI_IMAGE_MODELS, default="grok-imagine-image-quality"),
                IO.Combo.Input("aspect_ratio", options=XAI_ASPECT_RATIOS, default="1:1"),
                IO.Combo.Input("resolution", options=XAI_RESOLUTIONS, default="1k"),
                IO.Combo.Input("mime_type", options=XAI_MIME_TYPES, default="image/png"),
                IO.Int.Input("n", default=1, min=1, max=10, step=1, tooltip="Number of images to generate."),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Cache and re-execution control only; not sent to xAI."),
            ],
            outputs=[
                IO.Image.Output("image"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, mime_type, n, seed, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        info = resolve_provider("xai")
        api_key = info.get("api_key", "")
        try:
            with StatusUpdater(node_id, "Generating (xAI Imagine)") as updater:
                res = xai_image_generate(prompt, model_name, aspect_ratio, resolution, mime_type, n, api_key, "")
                return (res[0],)
        except Exception as exc:
            format_error("xAI image", exc)
            return (error_image(),)


class XAIImageEditNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIImageEdit",
            display_name="xAI Image Edit",
            category="ComfyUI LLM Mini/Image/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=XAI_IMAGE_MODELS, default="grok-imagine-image-quality"),
                IO.Combo.Input("aspect_ratio", options=XAI_ASPECT_RATIOS, default="1:1"),
                IO.Combo.Input("resolution", options=XAI_RESOLUTIONS, default="1k"),
                IO.Combo.Input("mime_type", options=XAI_MIME_TYPES, default="image/png"),
                IO.Int.Input("n", default=1, min=1, max=10, step=1, tooltip="Number of image variations to generate."),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Cache and re-execution control only; not sent to xAI."),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 4)],
                        min=1,
                    ),
                    tooltip="Source images for editing. xAI image editing supports up to 3 source images.",
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
    def execute(cls, prompt, model_name, aspect_ratio, resolution, mime_type, n, seed, images=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        info = resolve_provider("xai")
        api_key = info.get("api_key", "")
        image_tensors = image_tensors_from_input(images)
        try:
            with StatusUpdater(node_id, "Generating (xAI Image Edit)") as updater:
                res = xai_image_edit(prompt, model_name, aspect_ratio, resolution, mime_type, n, api_key, "", image_tensors, status_updater=updater)
                return (res[0],)
        except Exception as exc:
            format_error("xAI image edit", exc)
            return (error_image(),)


NODE_CLASS_MAPPINGS = {
    "LLMMiniXAIImagine": XAIImagineNode,
    "LLMMiniXAIImageEdit": XAIImageEditNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniXAIImagine": "xAI Imagine",
    "LLMMiniXAIImageEdit": "xAI Image Edit",
}
