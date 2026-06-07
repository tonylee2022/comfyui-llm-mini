from __future__ import annotations

from io import BytesIO
import logging

logger = logging.getLogger("LLMMini")

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


def r18_image():
    import torch
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    w, h = 512, 512
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    margin = 40
    circle_color = (220, 20, 60)
    ring_width = 35
    draw.ellipse([margin, margin, w - margin, h - margin], outline=circle_color, width=ring_width)

    font = None
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.otf",
    ]
    for path in font_paths:
        try:
            font = ImageFont.truetype(path, 160)
            break
        except Exception:
            continue

    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

    text = "18+"
    if font:
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except AttributeError:
            text_w, text_h = draw.textsize(text, font=font)
        
        y = (h - text_h) // 2 - 20
        
        try:
            bbox_18 = draw.textbbox((0, 0), "18", font=font)
            w_18 = bbox_18[2] - bbox_18[0]
        except AttributeError:
            w_18, _ = draw.textsize("18", font=font)
            
        draw.text(((w - text_w) // 2, y), "18", fill=(0, 0, 0), font=font)
        draw.text(((w - text_w) // 2 + w_18, y), "+", fill=circle_color, font=font)
    else:
        draw.text((200, 200), "18+", fill=(0, 0, 0))

    sub_font = None
    for path in font_paths:
        try:
            sub_font = ImageFont.truetype(path, 30)
            break
        except Exception:
            continue
            
    if sub_font:
        sub_text = "RESTRICTED"
        try:
            bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
            sw = bbox[2] - bbox[0]
            sh = bbox[3] - bbox[1]
        except AttributeError:
            sw, sh = draw.textsize(sub_text, font=sub_font)
        draw.text(((w - sw) // 2, 360), sub_text, fill=(120, 120, 120), font=sub_font)

    arr = np.array(img).astype(np.float32) / 255.0
    tensor = torch.from_numpy(arr).unsqueeze(0)
    return tensor


def is_safety_error(exc: Exception) -> bool:
    err_msg = str(exc)
    err_msg_lower = err_msg.lower()
    return (
        "image_prohibited_content" in err_msg_lower
        or "safety" in err_msg_lower
        or "moderation" in err_msg_lower
        or "policy" in err_msg_lower
        or "安全政策" in err_msg
        or "安全策略" in err_msg
        or "内容安全" in err_msg
    )



def format_error(label: str, exc: Exception) -> str:
    message = f"LLM Mini {label} request failed: {exc}"
    logger.error(message)
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
