from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path


def tensor_to_data_uri(image_tensor) -> str:
    import torch
    import numpy as np
    from PIL import Image

    if len(image_tensor.shape) == 3:
        image_tensor = image_tensor.unsqueeze(0)
    arr = 255.0 * image_tensor[0].detach().cpu().numpy()
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def image_source_to_tensor(url_or_data_uri: str):
    import torch
    import numpy as np
    import requests
    from PIL import Image, ImageOps, ImageSequence

    if url_or_data_uri.startswith("data:image"):
        _, encoded = url_or_data_uri.split(",", 1)
        raw = base64.b64decode(encoded)
    else:
        response = requests.get(url_or_data_uri, timeout=60)
        response.raise_for_status()
        raw = response.content
    img = Image.open(io.BytesIO(raw))
    tensors = []
    for frame in ImageSequence.Iterator(img):
        frame = ImageOps.exif_transpose(frame).convert("RGB")
        arr = np.array(frame).astype(np.float32) / 255.0
        tensors.append(torch.from_numpy(arr).unsqueeze(0))
    return torch.cat(tensors, dim=0) if len(tensors) > 1 else tensors[0]


def downscale_image_tensor(image_tensor, max_pixels: int = 2048 * 2048):
    import torch

    if len(image_tensor.shape) == 3:
        image_tensor = image_tensor.unsqueeze(0)
    _, h, w, _ = image_tensor.shape
    if h * w <= max_pixels:
        return image_tensor
    scale = (max_pixels / (h * w)) ** 0.5
    new_h = max(16, int(h * scale) // 16 * 16)
    new_w = max(16, int(w * scale) // 16 * 16)
    temp = image_tensor.permute(0, 3, 1, 2)
    temp = torch.nn.functional.interpolate(temp, size=(new_h, new_w), mode="bilinear", align_corners=False)
    return temp.permute(0, 2, 3, 1)


def video_to_data_uri(video_path: str) -> str:
    with open(video_path, "rb") as f:
        return "data:video/mp4;base64," + base64.b64encode(f.read()).decode("utf-8")


def get_video_path_from_input(video_input) -> str | None:
    if isinstance(video_input, str):
        return video_input
    if hasattr(video_input, "get_stream_source"):
        source = video_input.get_stream_source()
        if isinstance(source, str):
            return source
        if hasattr(source, "read"):
            try:
                source.seek(0)
                import folder_paths

                out_dir = Path(folder_paths.get_temp_directory())
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"llm-mini-video-input-{int(time.time())}.mp4"
                path.write_bytes(source.read())
                return str(path)
            except Exception:
                return None
    if isinstance(video_input, dict) and video_input.get("video"):
        item = video_input["video"][0]
        filename = item.get("filename")
        subfolder = item.get("subfolder", "")
        folder_type = item.get("type", "temp")
        try:
            import folder_paths

            base = {
                "temp": folder_paths.get_temp_directory(),
                "output": folder_paths.get_output_directory(),
                "input": folder_paths.get_input_directory(),
            }.get(folder_type, folder_paths.get_temp_directory())
            return os.path.join(base, subfolder, filename)
        except Exception:
            return None
    return None


def download_video_to_comfy(url: str):
    import requests

    response = requests.get(url, timeout=120)
    response.raise_for_status()
    try:
        import folder_paths

        out_dir = Path(folder_paths.get_temp_directory())
        folder_type = "temp"
    except Exception:
        out_dir = Path(__file__).resolve().parents[1] / "video_temp"
        folder_type = "temp"
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"llm-mini-video-{int(time.time())}.mp4"
    path = out_dir / filename
    path.write_bytes(response.content)
    try:
        from comfy_api.latest import InputImpl

        return InputImpl.VideoFromFile(str(path)), str(path)
    except Exception:
        return {"video": [{"filename": filename, "subfolder": "", "type": folder_type}]}, str(path)
