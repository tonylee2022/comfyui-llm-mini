from __future__ import annotations

from io import BytesIO

from ...core.media import downscale_image_tensor, image_source_to_tensor

DEFAULT_IMAGE_MODEL = "gpt-image-2"


def error_image():
    import torch

    image = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
    image[:, :, :, 0] = 0.85
    image[:, 0:4, :, :] = 1.0
    image[:, -4:, :, :] = 1.0
    image[:, :, 0:4, :] = 1.0
    image[:, :, -4:, :] = 1.0
    return image


def format_error(label: str, exc: Exception) -> str:
    message = f"LLM Mini {label} request failed: {exc}"
    print(f"[LLM Mini] {message}", flush=True)
    return message


def image_tensors_from_input(images):
    image_tensors = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
    if isinstance(images, dict):
        image_tensors = [t for t in images.values() if t is not None]
    return image_tensors


def tensor_png_file(image_tensor, name: str = "image.png"):
    from PIL import Image

    scaled = downscale_image_tensor(image_tensor).squeeze()
    arr = (scaled.detach().cpu().numpy() * 255).astype("uint8")
    img = Image.fromarray(arr)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return name, buf, "image/png"


def tensor_mask_png_file(image_tensor, mask, name: str = "mask.png"):
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


def image_source(value: str) -> str:
    if value.startswith("http") or value.startswith("data:image"):
        return value
    return "data:image/png;base64," + value


def image_sources_to_batch(values: list[str]):
    import torch

    sources = [image_source(value) for value in values]
    tensors = [image_source_to_tensor(source) for source in sources]
    return torch.cat(tensors, dim=0), sources


def normalize_image_model(model: str, background: str) -> str:
    image_model = (model or "").strip()
    if "/" in image_model:
        image_model = image_model.rsplit("/", 1)[-1]
    if not image_model or not image_model.startswith("gpt-image-"):
        image_model = DEFAULT_IMAGE_MODEL
    if image_model == "gpt-image-2" and background == "transparent":
        image_model = "gpt-image-1.5"
    return image_model
