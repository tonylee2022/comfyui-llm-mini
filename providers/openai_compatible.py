from __future__ import annotations

import json
import re
from dataclasses import dataclass

import requests

from ..core.config import normalize_base_url, resolve_provider
from ..core.http_logging import log_http_response
from ..core.interrupt import check_interrupted
from ..core.media import tensor_to_data_uri
from ..core.oauth import resolve_oauth_marker
from .native import list_anthropic_models, list_gemini_models, send_anthropic_chat, send_gemini_sdk_chat


def normalize_chat_kwargs(kwargs: dict) -> dict:
    normalized = dict(kwargs)
    model_name = str(normalized.get("model", "") or "").strip().lower()
    if model_name.startswith("gpt-5") and "max_completion_tokens" not in normalized and "max_tokens" in normalized:
        normalized["max_completion_tokens"] = normalized.pop("max_tokens")
    return normalized


def _history_without_base64_images(messages: list[dict]) -> list[dict]:
    cleaned_messages = []
    for message in messages:
        cleaned = dict(message)
        content = cleaned.get("content")
        if isinstance(content, list):
            cleaned_content = []
            omitted = False
            for item in content:
                if item.get("type") != "image_url":
                    cleaned_content.append(item)
                    continue
                image_url = item.get("image_url", {})
                url = image_url.get("url", "") if isinstance(image_url, dict) else str(image_url or "")
                if url.startswith("data:"):
                    omitted = True
                else:
                    cleaned_content.append(item)
            if omitted:
                cleaned_content.append({"type": "text", "text": "[Base64 image omitted from history]"})
            cleaned["content"] = cleaned_content
        cleaned_messages.append(cleaned)
    return cleaned_messages




def _codex_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    instructions = "You are a helpful assistant."
    converted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            instructions = str(content)
            continue
        content_list = []
        text_type = "output_text" if role == "assistant" else "input_text"
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    content_list.append({"type": text_type, "text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    image_url = item.get("image_url", {})
                    if isinstance(image_url, dict):
                        image_url = image_url.get("url", "")
                    if image_url:
                        content_list.append({"type": "input_image", "image_url": image_url})
        else:
            content_list.append({"type": text_type, "text": str(content)})
        converted.append({"type": "message", "role": role, "content": content_list})
    return instructions, converted


def call_codex_responses(api_key: str, model: str, messages: list[dict]) -> str:
    check_interrupted()
    instructions, converted = _codex_messages(messages)
    payload = {"model": model, "instructions": instructions, "input": converted, "store": False, "stream": True}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    url = "https://chatgpt.com/backend-api/codex/responses"
    response = requests.post(url, json=payload, headers=headers, stream=True, timeout=120)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(f"Codex Responses error HTTP {response.status_code}: {response.text}")
    chunks = []
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
        if event.get("type") in {"response.output_text.delta", "response.text.delta"}:
            chunks.append(event.get("delta") or event.get("text") or "")
    return "".join(chunks).strip()


def list_models(provider: str, api_key: str = "", base_url: str = "") -> list[str]:
    info = resolve_provider(provider, api_key, base_url)
    backend = info.get("backend", "openai_compatible")
    if backend == "anthropic":
        return list_anthropic_models(info.get("api_key", ""), info.get("default_models", []), base_url=info.get("base_url", ""))
    if backend == "gemini":
        return list_gemini_models(info.get("api_key", ""), info.get("default_models", []), base_url=info.get("base_url", ""))
    api_key, base_url, oauth_provider = resolve_oauth_marker(info.get("api_key", ""), provider, info.get("base_url", ""), "")
    if provider == "codex" or oauth_provider == "codex" or "chatgpt.com" in (base_url or ""):
        return info.get("default_models", [])
    endpoint = info.get("models_endpoint") or ""
    if not endpoint:
        return info.get("default_models", [])
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = normalize_base_url(base_url) + endpoint.lstrip("/")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        log_http_response("GET", url, response)
    except Exception as e:
        raise RuntimeError(f"Failed to connect to provider '{provider}' at {url}. Please check if the service is running. Error: {e}")
    if response.status_code != 200:
        print(f"[LLM Mini] Model list failed for {provider}: HTTP {response.status_code} {response.text}")
        return info.get("default_models", [])
    data = response.json()
    models = [item.get("id") for item in data.get("data", []) if item.get("id")]
    default_models = info.get("default_models", [])
    merged = list(models)
    for m in default_models:
        if m and m.lower() != "click refresh models" and m not in merged:
            merged.append(m)
    return merged or default_models


@dataclass
class ApiChatClient:
    provider: str
    model_name: str
    api_key: str
    base_url: str

    def send(self, user_prompt: str, system_prompt: str, temperature: float, max_tokens: int, history_json: str = "", image=None, image_url: str = "", stream: bool = False, extra_parameters: dict | None = None, thinking_level: str = "auto", retain_images_in_history: bool = False) -> tuple[str, str, str]:
        extra_parameters = (extra_parameters or {}).copy()
        if thinking_level and thinking_level != "auto":
            model_name_lower = self.model_name.lower()
            is_xai = (
                self.provider == "xai" or
                any(x in model_name_lower for x in ["grok", "build-0.1", "4.20", "4.3"])
            )
            is_gpt5 = any(x in model_name_lower for x in ["gpt-5.4", "gpt-5.5", "gpt-5"])
            is_o_series = any(x in model_name_lower for x in ["o1", "o3"])
            
            is_reasoning_model = is_xai or is_gpt5 or is_o_series
            
            if is_reasoning_model:
                disabled_val = "none" if (is_xai or is_gpt5) else "low"
                effort_map = {
                    "disabled": disabled_val,
                    "low": "low",
                    "medium": "medium",
                    "high": "high"
                }
                extra_parameters["reasoning_effort"] = effort_map.get(thinking_level, "medium")
        provider_info = resolve_provider(self.provider, self.api_key, self.base_url)
        backend = provider_info.get("backend", "openai_compatible")
        if backend == "gemini" and thinking_level:
            extra_parameters["thinking_level"] = thinking_level
        api_key, base_url, oauth_provider = resolve_oauth_marker(provider_info.get("api_key", ""), self.provider, provider_info.get("base_url", ""), self.model_name)
        base_url = normalize_base_url(base_url)
        if not api_key and self.provider != "ollama":
            raise RuntimeError("No API key or OAuth token found for selected provider.")
        try:
            messages = json.loads(history_json) if history_json else [{"role": "system", "content": system_prompt}]
        except json.JSONDecodeError:
            messages = [{"role": "system", "content": system_prompt}]
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = system_prompt
        else:
            messages.insert(0, {"role": "system", "content": system_prompt})
        content = user_prompt
        image_items = []
        if image is not None:
            tensors = list(image) if isinstance(image, (list, tuple)) else [image]
            expanded_tensors = []
            for t in tensors:
                if t is not None:
                    if hasattr(t, "shape") and len(t.shape) == 4 and t.shape[0] > 1:
                        for b in range(t.shape[0]):
                            expanded_tensors.append(t[b : b + 1])
                    else:
                        expanded_tensors.append(t)
            image_items.extend({"type": "image_url", "image_url": {"url": tensor_to_data_uri(t)}} for t in expanded_tensors if t is not None)
        clean_url = str(image_url or "").strip()
        if clean_url and (clean_url.startswith("http://") or clean_url.startswith("https://") or clean_url.startswith("data:")):
            image_items.append({"type": "image_url", "image_url": {"url": clean_url}})
        if image_items:
            content = [{"type": "text", "text": user_prompt}, *image_items]
        messages.append({"role": "user", "content": content})
        api_reasoning = ""
        if backend == "anthropic":
            response_text = send_anthropic_chat(api_key, self.model_name, messages, temperature, max_tokens, stream, extra_parameters, base_url=base_url)
        elif backend == "gemini":
            response_text = send_gemini_sdk_chat(api_key, self.model_name, messages, temperature, max_tokens, extra_parameters, base_url=base_url)
        elif "chatgpt.com" in base_url or oauth_provider == "codex":
            response_text = call_codex_responses(api_key, self.model_name, messages)
        else:
            from openai import OpenAI

            client = OpenAI(api_key=api_key or "ollama", base_url=base_url)
            response = client.chat.completions.create(
                **normalize_chat_kwargs({"model": self.model_name, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": stream, **extra_parameters})
            )
            if stream:
                content_chunks = []
                reasoning_chunks = []
                for chunk in response:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        content_chunks.append(delta.content or "")
                        r_content = getattr(delta, "reasoning_content", None)
                        if r_content:
                            reasoning_chunks.append(r_content)
                response_text = "".join(content_chunks)
                api_reasoning = "".join(reasoning_chunks)
            else:
                message = response.choices[0].message
                response_text = message.content or ""
                api_reasoning = getattr(message, "reasoning_content", None) or ""
        reasoning = ""
        if api_reasoning:
            reasoning = api_reasoning.strip()
        else:
            match = re.search(r"<think>(.*?)</think>", response_text, re.DOTALL)
            if match:
                reasoning = match.group(1).strip()
                response_text = response_text.replace(match.group(0), "").strip()
        messages.append({"role": "assistant", "content": response_text})
        output_messages = messages if retain_images_in_history else _history_without_base64_images(messages)
        return response_text, json.dumps(output_messages, ensure_ascii=False, indent=2), reasoning
