from __future__ import annotations

import requests

from comfy_api.latest import IO

from ...core.config import resolve_provider
from ...core.http_logging import log_http_response
from ...core.interrupt import check_interrupted
from ...core.media import cleanup_upload_temp_file, download_video_to_comfy, get_video_path_from_input, tensor_to_data_uri
from ...core.status import StatusUpdater, get_unique_id
from ...core.xai import _parse_xai_error, delete_xai_file, poll_video, upload_xai_file, xai_credentials
from ._shared import image_tensors_from_input


def submit_video(payload: dict, endpoint: str, api_key: str, base_url: str, status_updater=None):
    check_interrupted()
    key, base = xai_credentials(api_key, base_url)
    if not key:
        raise RuntimeError("No xAI API key or OAuth token found.")
    url = base + endpoint
    response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(_parse_xai_error(response))
    request_id = response.json().get("request_id")
    if not request_id:
        raise RuntimeError(f"xAI video response did not include request_id: {response.text}")
    video_url = poll_video(request_id, base, key, status_updater=status_updater)
    video_output, _ = download_video_to_comfy(video_url)
    return video_output, video_url


def xai_video(prompt: str, model: str, aspect_ratio: str, resolution: str, duration: int, seed: int, api_key: str, base_url: str, image=None, status_updater=None):
    check_interrupted()
    payload = {"model": model, "prompt": prompt, "duration": duration, "resolution": resolution}
    if aspect_ratio != "auto":
        payload["aspect_ratio"] = aspect_ratio
    if image is not None:
        if status_updater:
            status_updater.update_status("Uploading image 1/1")
        payload["image"] = {"url": tensor_to_data_uri(image)}
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/generations", api_key, base_url, status_updater=status_updater)


def xai_video_reference(prompt: str, model: str, aspect_ratio: str, resolution: str, duration: int, seed: int, api_key: str, base_url: str, images: list, status_updater=None):
    check_interrupted()
    valid_images = [img for img in images if img is not None]
    expanded_images = []
    for img in valid_images:
        if hasattr(img, "shape") and len(img.shape) == 4 and img.shape[0] > 1:
            for b in range(img.shape[0]):
                expanded_images.append(img[b : b + 1])
        else:
            expanded_images.append(img)

    if len(expanded_images) > 7:
        raise RuntimeError("Reference video generation supports up to 7 reference images.")
    total_imgs = len(expanded_images)

    refs = []
    for i, img in enumerate(expanded_images):
        if status_updater:
            status_updater.update_status(f"Uploading image {i + 1}/{total_imgs}")
        refs.append({"url": tensor_to_data_uri(img)})
    if not refs:
        raise RuntimeError("Reference video generation requires at least one image.")
    payload = {"model": model, "prompt": prompt, "duration": duration, "resolution": resolution, "reference_images": refs}
    if aspect_ratio != "auto":
        payload["aspect_ratio"] = aspect_ratio
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/generations", api_key, base_url, status_updater=status_updater)


def xai_video_edit(prompt: str, model: str, video, seed: int, api_key: str, base_url: str, status_updater=None):
    check_interrupted()
    path = get_video_path_from_input(video)
    if not path:
        raise RuntimeError("Could not resolve input video path.")
    key, base = xai_credentials(api_key, base_url)
    if not key:
        raise RuntimeError("No xAI API key or OAuth token found.")

    file_id = None
    try:
        if status_updater:
            status_updater.update_status("Uploading video")
        file_id = upload_xai_file(path, key, base)

        payload = {
            "model": model,
            "video": {"file_id": file_id},
            "prompt": prompt,
        }
        if status_updater:
            status_updater.update_status("Generating")

        url = base + "videos/edits"
        response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
        log_http_response("POST", url, response)
        if response.status_code != 200:
            raise RuntimeError(_parse_xai_error(response))
        request_id = response.json().get("request_id")
        if not request_id:
            raise RuntimeError(f"xAI video response did not include request_id: {response.text}")

        video_url = poll_video(request_id, base, key, status_updater=status_updater)
        video_output, _ = download_video_to_comfy(video_url)
        return video_output, video_url
    finally:
        if file_id:
            delete_xai_file(file_id, key, base)
        cleanup_upload_temp_file(path)


def xai_video_extend(prompt: str, model: str, video, duration: int, seed: int, api_key: str, base_url: str, status_updater=None):
    check_interrupted()
    path = get_video_path_from_input(video)
    if not path:
        raise RuntimeError("Could not resolve input video path.")
    key, base = xai_credentials(api_key, base_url)
    if not key:
        raise RuntimeError("No xAI API key or OAuth token found.")

    file_id = None
    try:
        if status_updater:
            status_updater.update_status("Uploading video")
        file_id = upload_xai_file(path, key, base)

        payload = {
            "model": model,
            "video": {"file_id": file_id},
            "prompt": prompt,
            "duration": duration,
        }
        if status_updater:
            status_updater.update_status("Generating")

        url = base + "videos/extensions"
        response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
        log_http_response("POST", url, response)
        if response.status_code != 200:
            raise RuntimeError(_parse_xai_error(response))
        request_id = response.json().get("request_id")
        if not request_id:
            raise RuntimeError(f"xAI video response did not include request_id: {response.text}")

        video_url = poll_video(request_id, base, key, status_updater=status_updater)
        video_output, _ = download_video_to_comfy(video_url)
        return video_output, video_url
    finally:
        if file_id:
            delete_xai_file(file_id, key, base)
        cleanup_upload_temp_file(path)


class XAIVideoNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideo",
            display_name="xAI Video Generation",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video", "grok-imagine-video-1.5-preview"], default="grok-imagine-video"),
                IO.Combo.Input("aspect_ratio", options=["auto", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"], default="auto"),
                IO.Combo.Input("resolution", options=["720p", "480p"], default="720p"),
                IO.Int.Input("duration", default=6, min=1, max=15, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
                IO.Image.Input("image", optional=True),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, duration, seed, image=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Generating (xAI Video Generation)") as updater:
            info = resolve_provider("xai")
            api_key = info.get("api_key", "")
            res = xai_video(prompt, model_name, aspect_ratio, resolution, duration, seed, api_key, "", image, status_updater=updater)
            return (res[0],)


class XAIVideoReferenceNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoReference",
            display_name="xAI Video Reference",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Combo.Input("aspect_ratio", options=["auto", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"], default="auto"),
                IO.Combo.Input("resolution", options=["720p", "480p"], default="720p"),
                IO.Int.Input("duration", default=6, min=1, max=10, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 8)],
                        min=0,
                    ),
                    tooltip="Reference images (up to 7). Add image inputs dynamically as needed. Use @Image1, @Image2, etc. in your prompt to refer to them.",
                ),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, duration, seed, images=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, "Generating (xAI Video Reference)") as updater:
                info = resolve_provider("xai")
                api_key = info.get("api_key", "")
                refs = image_tensors_from_input(images)
                res = xai_video_reference(prompt, model_name, aspect_ratio, resolution, duration, seed, api_key, "", refs, status_updater=updater)
                return (res[0],)
        except Exception as exc:
            raise RuntimeError(f"LLM Mini xAI video reference request failed: {exc}")


class XAIVideoEditNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoEdit",
            display_name="xAI Video Edit",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Video.Input("video"),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, video, seed, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Editing (xAI Video Edit)") as updater:
            info = resolve_provider("xai")
            api_key = info.get("api_key", "")
            res = xai_video_edit(prompt, model_name, video, seed, api_key, "", status_updater=updater)
            return (res[0],)


class XAIVideoExtendNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoExtend",
            display_name="xAI Video Extension",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Video.Input("video"),
                IO.Int.Input("duration", default=8, min=2, max=10, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, video, duration, seed, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Extending (xAI Video Extension)") as updater:
            info = resolve_provider("xai")
            api_key = info.get("api_key", "")
            res = xai_video_extend(prompt, model_name, video, duration, seed, api_key, "", status_updater=updater)
            return (res[0],)


NODE_CLASS_MAPPINGS = {
    "LLMMiniXAIVideo": XAIVideoNode,
    "LLMMiniXAIVideoEdit": XAIVideoEditNode,
    "LLMMiniXAIVideoReference": XAIVideoReferenceNode,
    "LLMMiniXAIVideoExtend": XAIVideoExtendNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniXAIVideo": "xAI Video Generation",
    "LLMMiniXAIVideoEdit": "xAI Video Edit",
    "LLMMiniXAIVideoReference": "xAI Video Reference",
    "LLMMiniXAIVideoExtend": "xAI Video Extension",
}
