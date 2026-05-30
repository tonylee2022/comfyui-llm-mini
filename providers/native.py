from __future__ import annotations

import base64
import json
import shutil
import subprocess


def _history_text(messages: list[dict]) -> str:
    lines = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [str(item.get("text", "")) for item in content if item.get("type") == "text"]
            content = "\n".join(part for part in text_parts if part)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _message_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if item.get("type") == "text").strip()
    return str(content or "")


def _anthropic_message_content(content) -> str | list:
    if isinstance(content, list):
        converted_list = []
        for item in content:
            if item.get("type") == "text":
                converted_list.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                url = item.get("image_url", {}).get("url", "")
                if url.startswith("data:image"):
                    header, encoded = url.split(",", 1)
                    media_type = header.split(";")[0].split(":")[1]
                    converted_list.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": encoded
                        }
                    })
                else:
                    try:
                        import requests
                        res = requests.get(url, timeout=30)
                        if res.status_code == 200:
                            media_type = res.headers.get("content-type", "image/png")
                            encoded = base64.b64encode(res.content).decode("utf-8")
                            converted_list.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": encoded
                                }
                            })
                    except Exception as e:
                        print(f"[LLM Mini] Failed to fetch image for Claude: {e}")
        return converted_list
    return str(content or "")


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    if messages and messages[0].get("role") == "system":
        return str(messages[0].get("content", "")), messages[1:]
    return "", messages


def list_anthropic_models(api_key: str, defaults: list[str]) -> list[str]:
    if not api_key:
        return defaults
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        result = client.models.list()
        models = [model.id for model in result.data if getattr(model, "id", None)]
        merged = list(models)
        for d in defaults:
            if d and d.lower() != "click refresh models" and d not in merged:
                merged.append(d)
        return merged or defaults
    except Exception as exc:
        print(f"[LLM Mini] Claude model list failed: {exc}")
        return defaults


def send_anthropic_chat(api_key: str, model: str, messages: list[dict], temperature: float, max_tokens: int, stream: bool, extra_parameters: dict) -> str:
    if not api_key:
        raise RuntimeError("No Claude API key found for selected provider.")
    from anthropic import Anthropic

    system, body_messages = _split_system(messages)
    converted = []
    for message in body_messages:
        role = message.get("role", "user")
        if role not in {"user", "assistant"}:
            role = "user"
        converted.append({"role": role, "content": _anthropic_message_content(message.get("content", ""))})

    client = Anthropic(api_key=api_key)
    kwargs = {"model": model, "messages": converted, "max_tokens": max_tokens, "temperature": temperature, **extra_parameters}
    if system:
        kwargs["system"] = system
    if stream:
        chunks = []
        with client.messages.stream(**kwargs) as response:
            for text in response.text_stream:
                chunks.append(text)
        return "".join(chunks)
    response = client.messages.create(**kwargs)
    return "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()


def list_gemini_models(api_key: str, credential_source: str, defaults: list[str]) -> list[str]:
    if not api_key:
        return defaults
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        models = []
        for model in client.models.list():
            name = getattr(model, "name", "")
            if name.startswith("models/"):
                name = name.removeprefix("models/")
            if name:
                models.append(name)
        merged = list(models)
        for d in defaults:
            if d and d.lower() != "click refresh models" and d not in merged:
                merged.append(d)
        return merged or defaults
    except Exception as exc:
        print(f"[LLM Mini] Gemini model list failed: {exc}")
        return defaults


def send_gemini_sdk_chat(api_key: str, model: str, messages: list[dict], temperature: float, max_tokens: int, extra_parameters: dict) -> str:
    if not api_key:
        raise RuntimeError("No Gemini API key found for selected provider.")
    from google import genai
    from google.genai import types

    system, body_messages = _split_system(messages)
    contents = []
    for msg in body_messages:
        role = msg.get("role", "user")
        if role == "assistant":
            role = "model"
        parts = []
        content_data = msg.get("content", "")
        if isinstance(content_data, list):
            for item in content_data:
                if item.get("type") == "text":
                    parts.append(types.Part.from_text(text=item.get("text", "")))
                elif item.get("type") == "image_url":
                    url = item.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        header, encoded = url.split(",", 1)
                        mime = header.split(";")[0].split(":")[1]
                        data_bytes = base64.b64decode(encoded)
                        parts.append(types.Part.from_bytes(data=data_bytes, mime_type=mime))
                    else:
                        try:
                            import requests
                            res = requests.get(url, timeout=30)
                            if res.status_code == 200:
                                mime = res.headers.get("content-type", "image/png")
                                parts.append(types.Part.from_bytes(data=res.content, mime_type=mime))
                        except Exception as e:
                            print(f"[LLM Mini] Failed to fetch image for Gemini: {e}")
        else:
            parts.append(types.Part.from_text(text=str(content_data)))
        contents.append(types.Content(role=role, parts=parts))

    config_kwargs = {"temperature": temperature, "max_output_tokens": max_tokens, **extra_parameters}
    if system:
        config_kwargs["system_instruction"] = system
    config = types.GenerateContentConfig(**config_kwargs)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=contents, config=config)
    return getattr(response, "text", "") or ""
