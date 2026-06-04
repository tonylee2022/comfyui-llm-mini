from __future__ import annotations

import base64
import json
from io import BytesIO

import requests

from ..core.http_logging import log_http_response
from ..core.media import downscale_image_tensor, image_source_to_tensor
from ..core.config import resolve_provider
from ..core.oauth import resolve_oauth_marker


def _tensor_png_file(image_tensor, name: str = "image.png"):
    from PIL import Image

    scaled = downscale_image_tensor(image_tensor).squeeze()
    arr = (scaled.detach().cpu().numpy() * 255).astype("uint8")
    img = Image.fromarray(arr)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return name, buf, "image/png"


def _tensor_mask_png_file(image_tensor, mask, name: str = "mask.png"):
    import numpy as np
    import torch
    from PIL import Image

    scaled = downscale_image_tensor(image_tensor)
    rgb = scaled[0].detach().cpu().numpy()
    mask_tensor = mask.detach().float().cpu() if hasattr(mask, "detach") else torch.as_tensor(mask, dtype=torch.float32)
    if len(mask_tensor.shape) == 4:
        mask_tensor = mask_tensor[0, :, :, 0]
    elif len(mask_tensor.shape) == 3:
        mask_tensor = mask_tensor[0]
    elif len(mask_tensor.shape) != 2:
        raise ValueError("OpenAI image edit mask must be a 2D mask or a batched mask.")
    mask_tensor = mask_tensor.unsqueeze(0).unsqueeze(0)
    mask_tensor = torch.nn.functional.interpolate(mask_tensor, size=rgb.shape[:2], mode="bilinear", align_corners=False)[0, 0]
    alpha = 1.0 - mask_tensor.clamp(0, 1).numpy()
    rgba = np.concatenate([rgb[:, :, :3], alpha[:, :, None]], axis=2)
    img = Image.fromarray((np.clip(rgba, 0, 1) * 255).astype("uint8"), mode="RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return name, buf, "image/png"


def _image_source(value: str) -> str:
    if value.startswith("http") or value.startswith("data:image"):
        return value
    return "data:image/png;base64," + value


def _image_sources_to_batch(values: list[str]):
    import torch

    sources = [_image_source(value) for value in values]
    tensors = [image_source_to_tensor(source) for source in sources]
    return torch.cat(tensors, dim=0), sources


def _codex_image(api_key: str, model: str, prompt: str, size: str, quality: str, background: str, image_tensors: list):
    from ..core.media import tensor_to_data_uri

    if not model or model.startswith("gpt-image-"):
        model = "gpt-5.5"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    content = [{"type": "input_text", "text": f"Use the image_generation tool to render: {prompt}. Output format: png."}]
    content = [{"type": "input_image", "image_url": tensor_to_data_uri(t)} for t in image_tensors] + content
    tool = {"type": "image_generation", "output_format": "png"}
    if size != "auto":
        tool["size"] = size
    if quality != "auto":
        tool["quality"] = quality
    if background != "auto":
        tool["background"] = background
    payload = {"model": model, "stream": True, "instructions": "You are an image generation assistant.", "input": [{"type": "message", "role": "user", "content": content}], "tools": [tool], "tool_choice": "auto", "store": False}
    url = "https://chatgpt.com/backend-api/codex/responses"
    response = requests.post(url, json=payload, headers=headers, stream=True, timeout=180)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(f"Codex image error HTTP {response.status_code}: {response.text}")
    images = []
    for raw in response.iter_lines():
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
        if event.get("type") == "response.output_item.done":
            item = event.get("item", {})
            if item.get("type") == "image_generation_call" and item.get("result"):
                images.append(item["result"])
    if not images:
        raise RuntimeError("Codex image response did not contain image data.")
    tensor_batch, sources = _image_sources_to_batch(images)
    return tensor_batch, sources[0]


def codex_image(prompt: str, model: str, size: str, quality: str, background: str, image_tensors=None):
    api_key, _, _ = resolve_oauth_marker("codex_oauth", "codex", "", model)
    if not api_key:
        raise RuntimeError("No Codex OAuth token found.")
    return _codex_image(api_key, model, prompt, size, quality, background, image_tensors or [])


def openai_image(prompt: str, model: str, size: str, quality: str, background: str, n: int, seed: int, image_tensors=None, mask=None, status_updater=None):
    image_tensors = [t for t in (image_tensors or []) if t is not None]
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
            if status_updater:
                status_updater.update_status(f"Uploading image {i + 1}/{total_imgs}")
            files.append(("image" if total_imgs == 1 else "image[]", _tensor_png_file(t, f"image_{i}.png")))
        if mask is not None:
            files.append(("mask", _tensor_mask_png_file(image_tensors[0], mask)))
        if status_updater:
            status_updater.update_status("Generating")
        url = base_url + "images/edits"
        response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    else:
        payload = {"model": model, "prompt": prompt, "n": n, "size": size, "quality": quality, "background": background}
        url = base_url + "images/generations"
        response = requests.post(url, headers=headers, json=payload, timeout=120)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI image error HTTP {response.status_code}: {response.text}")
    values = [item.get("url") or item.get("b64_json") for item in response.json().get("data", []) if item.get("url") or item.get("b64_json")]
    if not values:
        raise RuntimeError("Image response did not contain image data.")
    tensor_batch, sources = _image_sources_to_batch(values)
    return tensor_batch, sources[0]


def google_imagen_generate(prompt: str, model: str, aspect_ratio: str, resolution: str, quality: str, seed: int, api_key: str, base_url: str = "", n: int = 1):
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
            seed=seed
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config
        )

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
        res_map = {
            "512": "1k",
            "1K": "1k",
            "2K": "2k",
            "4K": "4k"
        }
        mapped_size = res_map.get(resolution, "1k")
        config_kwargs = {
            "number_of_images": n,
            "aspect_ratio": aspect_ratio,
            "output_mime_type": real_mime,
        }
        if "fast" not in model.lower():
            config_kwargs["image_size"] = mapped_size
        config = types.GenerateImagesConfig(**config_kwargs)
        response = client.models.generate_images(
            model=model,
            prompt=prompt,
            config=config
        )
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
    status_updater=None
):
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
    
    # Process reference images
    flat_images = []
    if image_tensors:
        for tensor in image_tensors:
            if tensor is None:
                continue
            from ..core.media import downscale_image_tensor
            downscaled = downscale_image_tensor(tensor)
            for i in range(downscaled.shape[0]):
                flat_images.append(downscaled[i])
                
        if len(flat_images) > 14:
            raise ValueError("The current maximum number of supported reference images is 14.")

        total_imgs = len(flat_images)
        for idx, single_tensor in enumerate(flat_images):
            if status_updater:
                status_updater.update_status(f"Uploading image {idx + 1}/{total_imgs}")
            arr = (single_tensor.detach().cpu().numpy() * 255).astype("uint8")
            pil_image = Image.fromarray(arr)
            contents.append(pil_image)

    # Process files
    if files and isinstance(files, str) and files.strip():
        contents.append(files)

    # Process prompt
    if prompt:
        if response_modalities != "IMAGE":
            # 自动追加提示，让模型必须返回图像描述文本
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
        "seed": seed
    }
    if image_config_kwargs:
        config_kwargs["image_config"] = types.ImageConfig(**image_config_kwargs)
        
    if thinking_level:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=thinking_level.lower(),
            include_thoughts=True
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

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config
    )

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

        # 跳过思维链中间产出的图像（thought=True），仅收集最终输出图像
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
