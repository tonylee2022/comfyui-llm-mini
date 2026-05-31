from __future__ import annotations

import time

import requests

from ..core.config import normalize_base_url, resolve_provider
from ..core.http_logging import log_http_response
from ..core.media import download_video_to_comfy, get_video_path_from_input, image_source_to_tensor, tensor_to_data_uri, video_to_data_uri
from ..core.oauth import get_oauth_token


def xai_credentials(api_key: str = "", base_url: str = "") -> tuple[str, str]:
    api_key = (api_key or "").strip()
    info = resolve_provider("xai", api_key, base_url)
    key = info.get("api_key", "")
    if not key or key == "xai_oauth":
        key = get_oauth_token("xai") or key
    return key, normalize_base_url(info.get("base_url", "https://api.x.ai/v1/"))


def xai_image(prompt: str, model: str, aspect_ratio: str, resolution: str, api_key: str, base_url: str, image_tensors=None, seed: int = None, status_updater=None):
    key, base = xai_credentials(api_key, base_url)
    if not key:
        raise RuntimeError("No xAI API key or OAuth token found.")
    tensors = [t for t in (image_tensors or []) if t is not None]
    url = base + ("images/edits" if tensors else "images/generations")
    payload = {"model": model, "prompt": prompt, "n": 1, "response_format": "url", "aspect_ratio": aspect_ratio, "resolution": resolution}
    if seed is not None:
        payload["seed"] = seed
    if tensors:
        images = []
        total_imgs = len(tensors)
        for i, t in enumerate(tensors):
            if status_updater:
                status_updater.update_status(f"Uploading image {i + 1}/{total_imgs}")
            images.append({"url": tensor_to_data_uri(t), "type": "image_url"})
        if status_updater:
            status_updater.update_status("Generating")
        payload["image" if len(images) == 1 else "images"] = images[0] if len(images) == 1 else images
    response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(f"xAI image error HTTP {response.status_code}: {response.text}")
    image_url = response.json()["data"][0]["url"]
    return image_source_to_tensor(image_url), image_url


def poll_video(request_id: str, base_url: str, api_key: str, status_updater=None) -> str:
    status_url = base_url + f"videos/{request_id}"
    for _ in range(360):
        time.sleep(5)
        response = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        log_http_response("GET", status_url, response)
        if response.status_code != 200:
            continue
        data = response.json()
        status = data.get("status")
        if status_updater and status:
            status_updater.update_status(f"Generating ({status})")
        if status == "done":
            url = data.get("video", {}).get("url")
            if not url:
                raise RuntimeError("xAI video finished without a video URL.")
            return url
        if status in {"failed", "expired"}:
            raise RuntimeError(f"xAI video task {status}: {data.get('error', 'unknown error')}")
    raise TimeoutError("xAI video task timed out.")


def submit_video(payload: dict, endpoint: str, api_key: str, base_url: str, status_updater=None):
    key, base = xai_credentials(api_key, base_url)
    if not key:
        raise RuntimeError("No xAI API key or OAuth token found.")
    url = base + endpoint
    response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(f"xAI video error HTTP {response.status_code}: {response.text}")
    request_id = response.json().get("request_id")
    if not request_id:
        raise RuntimeError(f"xAI video response did not include request_id: {response.text}")
    video_url = poll_video(request_id, base, key, status_updater=status_updater)
    video_output, _ = download_video_to_comfy(video_url)
    return video_output, video_url


def xai_video(prompt: str, model: str, aspect_ratio: str, resolution: str, duration: int, seed: int, api_key: str, base_url: str, image=None, status_updater=None):
    payload = {"model": "grok-imagine-video" if model == "grok-imagine-video-beta" else model, "prompt": prompt, "duration": duration, "resolution": resolution, "seed": seed}
    if aspect_ratio != "auto":
        payload["aspect_ratio"] = aspect_ratio
    if image is not None:
        if status_updater:
            status_updater.update_status("Uploading image 1/1")
        payload["image"] = {"url": tensor_to_data_uri(image), "type": "image_url"}
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/generations", api_key, base_url, status_updater=status_updater)


def xai_video_reference(prompt: str, model: str, aspect_ratio: str, resolution: str, duration: int, seed: int, api_key: str, base_url: str, images: list, status_updater=None):
    valid_images = [img for img in images if img is not None]
    
    # Expand any batched image tensors
    expanded_images = []
    for img in valid_images:
        if hasattr(img, "shape") and len(img.shape) == 4 and img.shape[0] > 1:
            for b in range(img.shape[0]):
                expanded_images.append(img[b : b + 1])
        else:
            expanded_images.append(img)
            
    # Truncate to maximum 7 images (API limit)
    expanded_images = expanded_images[:7]
    total_imgs = len(expanded_images)
    
    refs = []
    for i, img in enumerate(expanded_images):
        if status_updater:
            status_updater.update_status(f"Uploading image {i + 1}/{total_imgs}")
        refs.append({"url": tensor_to_data_uri(img)})
    if not refs:
        raise RuntimeError("Reference video generation requires at least one image.")
    payload = {"model": "grok-imagine-video" if model == "grok-imagine-video-beta" else model, "prompt": prompt, "duration": duration, "resolution": resolution, "seed": seed, "reference_images": refs}
    if aspect_ratio != "auto":
        payload["aspect_ratio"] = aspect_ratio
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/generations", api_key, base_url, status_updater=status_updater)


def xai_video_edit(prompt: str, model: str, video, seed: int, api_key: str, base_url: str, status_updater=None):
    path = get_video_path_from_input(video)
    if not path:
        raise RuntimeError("Could not resolve input video path.")
    if status_updater:
        status_updater.update_status("Uploading video")
    payload = {"model": "grok-imagine-video" if model == "grok-imagine-video-beta" else model, "video": {"url": video_to_data_uri(path), "type": "video_url"}, "prompt": prompt, "seed": seed}
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/edits", api_key, base_url, status_updater=status_updater)


def xai_video_extend(prompt: str, model: str, video, duration: int, seed: int, api_key: str, base_url: str, status_updater=None):
    path = get_video_path_from_input(video)
    if not path:
        raise RuntimeError("Could not resolve input video path.")
    if status_updater:
        status_updater.update_status("Uploading video")
    payload = {"model": "grok-imagine-video" if model == "grok-imagine-video-beta" else model, "video": {"url": video_to_data_uri(path), "type": "video_url"}, "prompt": prompt, "duration": duration, "seed": seed}
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/extensions", api_key, base_url, status_updater=status_updater)
