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


def _codex_image(api_key: str, model: str, prompt: str, size: str, image_tensors: list):
    from ..core.media import tensor_to_data_uri

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    content = [{"type": "input_text", "text": f"Use the image_generation tool to render: {prompt}. Output format: png."}]
    content = [{"type": "input_image", "image_url": tensor_to_data_uri(t)} for t in image_tensors] + content
    tool = {"type": "image_generation", "output_format": "png"}
    if size != "auto":
        tool["size"] = size
    payload = {"model": "gpt-5.5", "stream": True, "instructions": "You are an image generation assistant.", "input": [{"type": "message", "role": "user", "content": content}], "tools": [tool], "tool_choice": "auto", "store": False}
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
    data_uri = images[0] if images[0].startswith("data:image") else "data:image/png;base64," + images[0]
    return image_source_to_tensor(data_uri), data_uri


def codex_image(prompt: str, model: str, size: str, image_tensors=None):
    api_key, _, _ = resolve_oauth_marker("codex_oauth", "codex", "", model)
    if not api_key:
        raise RuntimeError("No Codex OAuth token found.")
    return _codex_image(api_key, model, prompt, size, image_tensors or [])


def openai_image(prompt: str, model: str, size: str, quality: str, background: str, n: int, seed: int, image_tensors=None, mask=None):
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
        data = {"model": model, "prompt": prompt, "n": str(n), "size": size, "quality": quality, "background": background, "seed": str(seed), "response_format": "url"}
        files = [("image" if len(image_tensors) == 1 else "image[]", _tensor_png_file(t, f"image_{i}.png")) for i, t in enumerate(image_tensors)]
        url = base_url + "images/edits"
        response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
    else:
        payload = {"model": model, "prompt": prompt, "n": n, "size": size, "quality": quality, "background": background, "seed": seed, "response_format": "url"}
        url = base_url + "images/generations"
        response = requests.post(url, headers=headers, json=payload, timeout=120)
    log_http_response("POST", url, response)
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI image error HTTP {response.status_code}: {response.text}")
    urls = [item.get("url") or item.get("b64_json") for item in response.json().get("data", []) if item.get("url") or item.get("b64_json")]
    if not urls:
        raise RuntimeError("Image response did not contain image data.")
    source = urls[0] if urls[0].startswith("http") or urls[0].startswith("data:image") else "data:image/png;base64," + urls[0]
    return image_source_to_tensor(source), source


def google_imagen_generate(prompt: str, model: str, aspect_ratio: str, resolution: str, mime_type: str, seed: int, api_key: str, base_url: str = "", n: int = 1):
    if not api_key:
        raise RuntimeError("No Google API key found. Please configure it in config.ini or environment variables.")
    
    from google import genai
    from google.genai import types
    import numpy as np
    import torch
    from PIL import Image

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["http_options"] = {"base_url": base_url}
    client = genai.Client(**client_kwargs)
    
    real_mime = f"image/{mime_type}" if mime_type in ["jpeg", "png"] else "image/jpeg"
    tensors = []

    if model.startswith("gemini"):
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=resolution
            ),
            seed=seed
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config
        )
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
        config = types.GenerateImagesConfig(
            number_of_images=n,
            aspect_ratio=aspect_ratio,
            output_mime_type=real_mime,
            image_size=mapped_size
        )
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


def google_image_edit(prompt: str, model: str, image_tensors: list, aspect_ratio: str, resolution: str, seed: int, api_key: str, base_url: str = ""):
    if not api_key:
        raise RuntimeError("No Google API key found. Please configure it in config.ini or environment variables.")
    
    from google import genai
    from google.genai import types
    from PIL import Image
    import numpy as np
    import torch
    import io

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["http_options"] = {"base_url": base_url}
    client = genai.Client(**client_kwargs)
    
    contents = []
    for tensor in image_tensors:
        if tensor is None:
            continue
        if len(tensor.shape) == 4:
            single_tensor = tensor[0]
        else:
            single_tensor = tensor
            
        arr = (single_tensor.detach().cpu().numpy() * 255).astype("uint8")
        pil_image = Image.fromarray(arr)
        contents.append(pil_image)
        
    if prompt:
        contents.append(prompt)
        
    if not contents:
        raise RuntimeError("No input provided (neither prompt nor reference images).")
        
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(
            aspect_ratio=aspect_ratio,
            image_size=resolution
        ),
        seed=seed
    )
    
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=config
    )
    
    tensors = []
    for part in response.parts:
        img_data = part.as_image()
        if img_data is not None:
            pil_img = Image.open(io.BytesIO(img_data.image_bytes)).convert("RGB")
            arr = np.array(pil_img).astype(np.float32) / 255.0
            tensors.append(torch.from_numpy(arr).unsqueeze(0))
            
    if not tensors:
        text_desc = getattr(response, "text", "") or "No image returned by the Gemini model."
        raise RuntimeError(f"Google Image Edit failed: {text_desc}")
        
    return torch.cat(tensors, dim=0)
