from __future__ import annotations

import os
import time

import requests

from ..core.config import normalize_base_url, resolve_provider
from ..core.http_logging import log_http_response
from ..core.media import download_video_to_comfy, get_video_path_from_input, image_source_to_tensor, tensor_to_data_uri
from ..core.oauth import get_oauth_token


ERROR_TRANSLATIONS = {
    "Generated video rejected by content moderation.": "生成的视频因违反内容安全政策被拒绝。",
    "Generated video rejected by content moderation": "生成的视频因违反内容安全政策被拒绝",
    "Video generation failed due to an internal error. Please try again.": "视频生成由于内部服务错误失败，请重试。",
    "Video generation failed due to an internal error. Please try again": "视频生成由于内部服务错误失败，请重试",
    "CONTENT_POLICY_VIOLATION": "违反内容安全政策",
    "Client specified an invalid argument": "客户端提交了不合规的参数",
    "xAI video finished without a video URL.": "视频生成完成，但接口未返回下载链接。",
    "xAI video task timed out.": "视频生成任务超时。",
}


def _get_comfyui_locale() -> str:
    import json
    paths_to_try = []
    try:
        # 尝试从当前文件位置回溯三级去找 ComfyUI 的配置目录
        curr = os.path.dirname(os.path.abspath(__file__))
        p3 = os.path.dirname(os.path.dirname(os.path.dirname(curr)))
        paths_to_try.append(os.path.join(p3, "user", "default", "comfy.settings.json"))
    except Exception:
        pass
    
    try:
        # 尝试从 ComfyUI 运行时的当前工作目录寻找
        paths_to_try.append(os.path.join(os.getcwd(), "user", "default", "comfy.settings.json"))
    except Exception:
        pass
        
    for path in paths_to_try:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    loc = settings.get("Comfy.Locale") or settings.get("AGL.Locale")
                    if loc:
                        return str(loc).lower()
            except Exception:
                pass
    return ""


def _is_chinese_locale() -> bool:
    # 仅检测 ComfyUI 自带的界面语言设置，不受底层操作系统环境变量的影响
    comfy_locale = _get_comfyui_locale()
    return "zh" in comfy_locale


def _translate_xai_message(msg: str) -> str:
    if not msg:
        return msg
    if _is_chinese_locale():
        return ERROR_TRANSLATIONS.get(msg.strip(), msg)
    return msg


def _parse_xai_error(response) -> str:
    err_msg = response.text
    block_reason = None
    try:
        err_data = response.json()
        if isinstance(err_data, dict):
            if "error" in err_data:
                err_val = err_data["error"]
                if isinstance(err_val, dict):
                    err_msg = err_val.get("message") or err_val.get("code") or str(err_val)
                else:
                    err_msg = str(err_val)
                block_reason = err_data.get("block_reason")
            elif "message" in err_data:
                err_msg = err_data["message"]
    except Exception:
        pass

    translated_msg = _translate_xai_message(err_msg)
    if block_reason:
        translated_reason = _translate_xai_message(block_reason)
        err_msg = f"{translated_msg} ({translated_reason})"
    else:
        err_msg = translated_msg
    return err_msg


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
            images.append({"url": tensor_to_data_uri(t)})
        if status_updater:
            status_updater.update_status("Generating")
        payload["image" if len(images) == 1 else "images"] = images[0] if len(images) == 1 else images
    response = requests.post(url, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(_parse_xai_error(response))
    image_url = response.json()["data"][0]["url"]
    return image_source_to_tensor(image_url), image_url


def upload_xai_file(path: str, api_key: str, base_url: str) -> str:
    url = base_url + "files"
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, "video/mp4")}
        data = {"purpose": "assistants"}
        response = requests.post(url, headers={"Authorization": f"Bearer {api_key}"}, files=files, data=data, timeout=90)
        if response.status_code != 200:
            raise RuntimeError(_parse_xai_error(response))
        return response.json()["id"]


def delete_xai_file(file_id: str, api_key: str, base_url: str) -> None:
    url = base_url + f"files/{file_id}"
    try:
        response = requests.delete(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        log_http_response("DELETE", url, response)
    except Exception as e:
        print(f"[LLM Mini] Failed to delete xAI file {file_id}: {e}")


def poll_video(request_id: str, base_url: str, api_key: str, status_updater=None) -> str:
    status_url = base_url + f"videos/{request_id}"
    for _ in range(60):
        time.sleep(5)
        response = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        log_http_response("GET", status_url, response)
        if response.status_code not in {200, 202}:
            raise RuntimeError(_parse_xai_error(response))
        try:
            data = response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to parse JSON response during polling: {e}. Content: {response.text}")
        status = data.get("status")
        progress = data.get("progress")
        if status_updater and status:
            if progress is not None:
                status_updater.update_status(f"Generating ({status} - {progress}%)")
            else:
                status_updater.update_status(f"Generating ({status})")
        if status == "done":
            url = data.get("video", {}).get("url")
            if not url:
                raise RuntimeError("xAI video finished without a video URL.")
            return url
        if status in {"failed", "expired"}:
            err_val = data.get("error", "unknown error")
            if isinstance(err_val, dict):
                err_msg = err_val.get("message") or err_val.get("code") or str(err_val)
            else:
                err_msg = str(err_val)
            raise RuntimeError(_translate_xai_message(err_msg))
    raise TimeoutError("xAI video task timed out.")


def submit_video(payload: dict, endpoint: str, api_key: str, base_url: str, status_updater=None):
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
    payload = {"model": model, "prompt": prompt, "duration": duration, "resolution": resolution, "seed": seed}
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
    payload = {"model": model, "prompt": prompt, "duration": duration, "resolution": resolution, "seed": seed, "reference_images": refs}
    if aspect_ratio != "auto":
        payload["aspect_ratio"] = aspect_ratio
    if status_updater:
        status_updater.update_status("Generating")
    return submit_video(payload, "videos/generations", api_key, base_url, status_updater=status_updater)


def xai_video_edit(prompt: str, model: str, video, seed: int, api_key: str, base_url: str, status_updater=None):
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
            "seed": seed
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


def xai_video_extend(prompt: str, model: str, video, duration: int, seed: int, api_key: str, base_url: str, status_updater=None):
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
            "duration": duration
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
