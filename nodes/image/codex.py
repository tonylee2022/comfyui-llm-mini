from __future__ import annotations

import json
import re
import time
import logging

logger = logging.getLogger("LLMMini")

import requests

from comfy_api.latest import IO

from ...core.http_logging import log_http_response
from ...core.interrupt import check_interrupted, interruptible_sleep
from ...core.oauth import resolve_oauth_marker
from ...core.status import StatusUpdater, get_unique_id
from ._shared import error_image, format_error, image_sources_to_batch, image_tensors_from_input, normalize_image_model


def _append_image_value(images: list[str], value):
    if isinstance(value, str):
        if value and value not in images:
            images.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _append_image_value(images, item)
        return
    if isinstance(value, dict):
        for key in ("result", "b64_json", "image_b64", "image_base64", "partial_image_b64", "url", "image_url"):
            _append_image_value(images, value.get(key))


def _extract_codex_image_values(payload) -> list[str]:
    images: list[str] = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        value_type = value.get("type")
        if value_type == "image_generation_call":
            _append_image_value(images, value.get("result"))
            _append_image_value(images, value.get("output"))
            _append_image_value(images, value.get("image"))
        elif isinstance(value_type, str) and value_type.startswith("response.image_generation_call."):
            _append_image_value(images, value.get("result"))
            _append_image_value(images, value.get("b64_json"))
            _append_image_value(images, value.get("image_b64"))
            _append_image_value(images, value.get("image_base64"))

        for key in ("item", "response", "output", "content", "data"):
            visit(value.get(key))

    visit(payload)
    return images


class _CodexRateLimitError(RuntimeError):
    def __init__(self, error, retry_after: float, is_minute_saturated: bool = False):
        self.error = error
        self.retry_after = retry_after
        self.is_minute_saturated = is_minute_saturated
        super().__init__(f"Codex image rate limit: {error}")


def _rate_limit_info(error, default_seconds: float = 1.0) -> tuple[float, bool]:
    retry_after = None
    if isinstance(error, dict):
        retry_after = error.get("retry_after") or error.get("retry_after_seconds")
        message = str(error.get("message", ""))
    else:
        message = str(error)
    if retry_after is not None:
        try:
            return max(float(retry_after), 0.0), False
        except (TypeError, ValueError):
            pass
    minute_match = re.search(
        r"per\s+min:\s+Limit\s+(\d+),\s+Used\s+(\d+),\s+Requested\s+(\d+)",
        message,
        re.IGNORECASE,
    )
    if minute_match:
        limit, used, requested = (int(value) for value in minute_match.groups())
        if used >= limit or used + requested > limit:
            return 65.0, True
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s|sec|second|seconds)?", message, re.IGNORECASE)
    if match:
        value = float(match.group(1))
        unit = (match.group(2) or "s").lower()
        if unit == "ms":
            value /= 1000.0
        return max(value, 0.0), False
    return default_seconds, False


def _rate_limit_retry_after(error, default_seconds: float = 1.0) -> float:
    return _rate_limit_info(error, default_seconds)[0]


def _is_rate_limit_error(error) -> bool:
    if isinstance(error, dict):
        if error.get("code") == "rate_limit_exceeded":
            return True
        message = str(error.get("message", ""))
    else:
        message = str(error)
    return "rate limit" in message.lower() or "rate_limit_exceeded" in message


def _codex_retry_delay(retry_after: float, attempt: int) -> float:
    backoff = min(2 ** (attempt - 1), 16)
    return max(retry_after, float(backoff))


CODEX_RESPONSES_MODEL = "gpt-5.5"
_CODEX_IMAGE_COOLDOWN_UNTIL = 0.0


def _codex_image_once(api_key: str, image_model: str, prompt: str, size: str, quality: str, background: str, image_tensors: list):
    from ...core.media import tensor_to_data_uri

    check_interrupted()
    image_model = normalize_image_model(image_model, background)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    content = [{"type": "input_text", "text": f"Use the image_generation tool to render: {prompt}. Output format: png."}]
    content = [{"type": "input_image", "image_url": tensor_to_data_uri(t)} for t in image_tensors] + content
    tool = {"type": "image_generation", "model": image_model, "output_format": "png", "action": "edit" if image_tensors else "generate"}
    if size != "auto":
        tool["size"] = size
    if quality != "auto":
        tool["quality"] = quality
    if background != "auto":
        tool["background"] = background
    payload = {"model": CODEX_RESPONSES_MODEL, "stream": True, "instructions": "You are an image generation assistant.", "input": [{"type": "message", "role": "user", "content": content}], "tools": [tool], "tool_choice": {"type": "image_generation"}, "store": False}
    url = "https://chatgpt.com/backend-api/codex/responses"
    response = requests.post(url, json=payload, headers=headers, stream=True, timeout=180)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        if response.status_code == 429:
            try:
                error = response.json().get("error") or response.json()
            except Exception:
                error = response.text
            retry_after = response.headers.get("Retry-After")
            try:
                retry_after_seconds = float(retry_after) if retry_after is not None else _rate_limit_retry_after(error)
            except ValueError:
                retry_after_seconds = _rate_limit_retry_after(error)
            _, is_minute_saturated = _rate_limit_info(error)
            raise _CodexRateLimitError(error, retry_after_seconds, is_minute_saturated)
        raise RuntimeError(f"Codex image error HTTP {response.status_code}: {response.text}")
    images = []
    partial_images = []
    event_types = []
    text_chunks = []
    for raw in response.iter_lines():
        check_interrupted()
        if not raw:
            continue
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            break
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type") or ""
        if event_type and event_type not in event_types:
            event_types.append(event_type)
        if event_type in {"response.output_text.delta", "response.text.delta"}:
            text_chunks.append(event.get("delta") or event.get("text") or "")
        if event_type in {"response.failed", "response.error", "error"}:
            error = event.get("error") or event
            if _is_rate_limit_error(error):
                retry_after, is_minute_saturated = _rate_limit_info(error)
                raise _CodexRateLimitError(error, retry_after, is_minute_saturated)
            raise RuntimeError(f"Codex image error: {error}")
        if _is_rate_limit_error(event):
            retry_after, is_minute_saturated = _rate_limit_info(event)
            raise _CodexRateLimitError(event, retry_after, is_minute_saturated)
        if event_type == "response.image_generation_call.partial_image":
            _append_image_value(partial_images, event.get("partial_image_b64"))
        _append_image_value(images, _extract_codex_image_values(event))
    if not images and partial_images:
        images = partial_images
    if not images:
        details = ", ".join(event_types[:8]) or "no stream events"
        text = "".join(text_chunks).strip()
        if text:
            details += f"; text: {text[:300]}"
        raise RuntimeError(f"Codex image response did not contain image data. Stream events: {details}")
    tensor_batch, sources = image_sources_to_batch(images)
    return tensor_batch, sources[0]


def _codex_image(api_key: str, image_model: str, prompt: str, size: str, quality: str, background: str, image_tensors: list):
    global _CODEX_IMAGE_COOLDOWN_UNTIL

    now = time.time()
    if now < _CODEX_IMAGE_COOLDOWN_UNTIL:
        remaining = int(_CODEX_IMAGE_COOLDOWN_UNTIL - now)
        raise RuntimeError(f"Codex image rate limit cooldown active. Try again in about {remaining}s.")

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        check_interrupted()
        try:
            return _codex_image_once(api_key, image_model, prompt, size, quality, background, image_tensors)
        except _CodexRateLimitError as exc:
            if attempt == max_attempts:
                if exc.is_minute_saturated:
                    _CODEX_IMAGE_COOLDOWN_UNTIL = time.time() + 300
                    raise RuntimeError(f"Codex image rate limit still saturated after waiting {int(exc.retry_after)}s. Local cooldown started for 300s: {exc.error}") from exc
                raise RuntimeError(f"Codex image rate limit exceeded after {max_attempts} attempts: {exc.error}") from exc
            delay = _codex_retry_delay(exc.retry_after, attempt)
            logger.warning(f"Codex image rate limited; retrying in {delay:.2f}s ({attempt}/{max_attempts}).")
            interruptible_sleep(delay)


def codex_image(prompt: str, model: str, size: str, quality: str, background: str, image_tensors=None):
    api_key, _, _ = resolve_oauth_marker("codex_oauth", "codex", "", model)
    if not api_key:
        raise RuntimeError("No Codex OAuth token found.")
    return _codex_image(api_key, model, prompt, size, quality, background, image_tensors or [])


class CodexImageNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniCodexImage",
            display_name="Codex Image",
            category="ComfyUI LLM Mini/Image/OpenAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input(
                    "model_name",
                    options=["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"],
                    default="gpt-image-2",
                    tooltip="GPT Image model for Codex image_generation tool calls. Codex uses gpt-5.5 internally as the Responses main model.",
                ),
                IO.Combo.Input(
                    "size",
                    options=["auto", "1024x1024", "1024x1536", "1536x1024", "2048x2048", "2048x1152", "1152x2048", "3840x2160", "2160x3840"],
                    default="auto",
                ),
                IO.Combo.Input("quality", options=["low", "medium", "high"], default="low"),
                IO.Combo.Input("background", options=["auto", "opaque", "transparent"], default="auto"),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Cache and re-execution control only; not sent to Codex."),
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
    def execute(cls, prompt, model_name, size, quality, background, seed, images=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        image_tensors = image_tensors_from_input(images)
        try:
            with StatusUpdater(node_id, "Generating (Codex)"):
                res = codex_image(prompt, model_name, size, quality, background, image_tensors)
                return (res[0],)
        except Exception as exc:
            format_error("Codex image", exc)
            raise exc


NODE_CLASS_MAPPINGS = {
    "LLMMiniCodexImage": CodexImageNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniCodexImage": "Codex Image",
}
