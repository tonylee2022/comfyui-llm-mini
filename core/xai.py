from __future__ import annotations

import os
import logging

logger = logging.getLogger("LLMMini")

import requests

from .config import normalize_base_url, resolve_provider
from .http_logging import log_http_response
from .interrupt import check_interrupted, interruptible_sleep
from .oauth import resolve_oauth_marker


ERROR_TRANSLATIONS = {
    "Generated video rejected by content moderation.": "生成的视频因违反内容安全政策被拒绝。",
    "Generated video rejected by content moderation": "生成的视频因违反内容安全政策被拒绝",
    "Generated image rejected by content moderation.": "生成的图像因违反内容安全政策被拒绝。",
    "Generated image rejected by content moderation": "生成的图像因违反内容安全政策被拒绝",
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
        curr = os.path.dirname(os.path.abspath(__file__))
        p3 = os.path.dirname(os.path.dirname(os.path.dirname(curr)))
        paths_to_try.append(os.path.join(p3, "user", "default", "comfy.settings.json"))
    except Exception:
        pass

    try:
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
    key, resolved_base_url, _ = resolve_oauth_marker(
        info.get("api_key", ""),
        "xai",
        info.get("base_url", ""),
        "",
    )
    return key, normalize_base_url(resolved_base_url or "https://api.x.ai/v1/")


def upload_xai_file(path: str, api_key: str, base_url: str) -> str:
    check_interrupted()
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
        logger.error(f"Failed to delete xAI file {file_id}: {e}")


def poll_video(request_id: str, base_url: str, api_key: str, status_updater=None) -> str:
    status_url = base_url + f"videos/{request_id}"
    for _ in range(60):
        interruptible_sleep(5)
        check_interrupted()
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
