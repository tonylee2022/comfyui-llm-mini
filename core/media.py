from __future__ import annotations

import base64
import io
import os
import threading
import logging

logger = logging.getLogger("LLMMini")
from pathlib import Path
from uuid import uuid4


_OWNED_UPLOAD_TEMP_FILES: set[str] = set()
_OWNED_UPLOAD_TEMP_LOCK = threading.RLock()


def _register_upload_temp_file(path: Path) -> None:
    with _OWNED_UPLOAD_TEMP_LOCK:
        _OWNED_UPLOAD_TEMP_FILES.add(str(path.resolve()))


def tensor_to_data_uri(image_tensor) -> str:
    import torch
    import numpy as np
    from PIL import Image

    # 自动对图像进行下采样，避免生成庞大的 base64 数据导致连接超时
    image_tensor = downscale_image_tensor(image_tensor)

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


def transcode_to_h264_mp4(input_path: str) -> str:
    import subprocess
    import tempfile
    from pathlib import Path

    # 只要是 mp4 格式，直接返回，免去任何转码逻辑
    if input_path.lower().endswith(".mp4"):
        return input_path

    # 默认检测
    has_audio = False
    is_h264_mp4 = False
    try:
        import av
        with av.open(input_path) as container:
            if len(container.streams.audio) > 0:
                has_audio = True
            if len(container.streams.video) > 0:
                v_stream = container.streams.video[0]
                codec = v_stream.codec.name
                fmt = container.format.name
                # 判断是否已经是标准 H.264 MP4 格式
                if codec in {"h264", "libx264"} and any(x in fmt.lower() for x in {"mp4", "mov", "m4v"}):
                    is_h264_mp4 = True
    except Exception:
        # 备用 ffprobe 检测
        try:
            cmd_probe = ["ffprobe", "-show_streams", "-loglevel", "error", input_path]
            res_probe = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output = res_probe.stdout
            if "codec_name=h264" in output:
                # 简单通过文件名后缀判断容器
                if input_path.lower().endswith((".mp4", ".mov", ".m4v")):
                    is_h264_mp4 = True
            if "codec_type=audio" in output:
                has_audio = True
        except Exception:
            pass

    # 如果本身就是 H.264 编码的 MP4，则无需重编码，直接返回原始路径
    if is_h264_mp4:
        return input_path

    try:
        import folder_paths
        out_dir = Path(folder_paths.get_temp_directory())
    except Exception:
        out_dir = Path(tempfile.gettempdir())

    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"llm-mini-video-transcoded-{uuid4().hex}.mp4"
    _register_upload_temp_file(output_path)

    # ffmpeg 重新转码为标准 H.264 MP4 格式，去除 "-r 25" 以保持原视频帧率，避免 PTS 错误导致 API 报错
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vcodec", "libx264",
        "-pix_fmt", "yuv420p",
    ]
    if has_audio:
        cmd += ["-acodec", "aac"]
    else:
        cmd += ["-an"]

    cmd += [str(output_path)]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return str(output_path)
    except Exception as e:
        logger.error(f"ffmpeg transcoding failed, falling back to original: {e}")
        cleanup_upload_temp_file(str(output_path))
        return input_path


def get_video_path_from_input(video_input) -> str | None:
    if isinstance(video_input, str):
        return transcode_to_h264_mp4(video_input) if os.path.exists(video_input) else video_input

    raw_path = None

    # 优先尝试使用 save_to 方法
    if hasattr(video_input, "save_to"):
        path = None
        try:
            import folder_paths
            from io import BytesIO

            out_dir = Path(folder_paths.get_temp_directory())
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"llm-mini-video-input-{uuid4().hex}.mp4"
            _register_upload_temp_file(path)

            try:
                from comfy_api.latest import Types
                fmt = Types.VideoContainer.MP4
                cod = Types.VideoCodec.H264
            except Exception:
                fmt = "mp4"
                cod = "h264"

            video_bytes_io = BytesIO()
            video_input.save_to(video_bytes_io, format=fmt, codec=cod)
            video_bytes_io.seek(0)

            with open(path, "wb") as f:
                f.write(video_bytes_io.read())
            raw_path = str(path)
        except Exception as e:
            cleanup_upload_temp_file(str(path) if path else None)
            logger.error(f"Failed to save video via save_to: {e}")

    # 尝试 get_stream_source 方法
    if not raw_path and hasattr(video_input, "get_stream_source"):
        source = video_input.get_stream_source()
        if isinstance(source, str):
            raw_path = source
        elif hasattr(source, "read"):
            path = None
            try:
                source.seek(0)
                import folder_paths

                out_dir = Path(folder_paths.get_temp_directory())
                out_dir.mkdir(parents=True, exist_ok=True)
                path = out_dir / f"llm-mini-video-input-{uuid4().hex}.mp4"
                _register_upload_temp_file(path)
                path.write_bytes(source.read())
                raw_path = str(path)
            except Exception:
                cleanup_upload_temp_file(str(path) if path else None)

    # 尝试字典配置格式 (如从 Load Video 节点传入)
    if not raw_path and isinstance(video_input, dict) and video_input.get("video"):
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
            raw_path = os.path.join(base, subfolder, filename)
        except Exception:
            pass

    if raw_path and os.path.exists(raw_path):
        return transcode_to_h264_mp4(raw_path)

    return raw_path


def cleanup_upload_temp_file(path: str | None) -> None:
    if not path:
        return
    candidate = Path(path)
    resolved = str(candidate.resolve())
    with _OWNED_UPLOAD_TEMP_LOCK:
        if resolved not in _OWNED_UPLOAD_TEMP_FILES:
            return
        _OWNED_UPLOAD_TEMP_FILES.remove(resolved)
    try:
        candidate.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(f"Failed to remove upload temp file {candidate}: {exc}")


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
    filename = f"llm-mini-video-{uuid4().hex}.mp4"
    path = out_dir / filename
    path.write_bytes(response.content)
    try:
        from comfy_api.latest import InputImpl

        return InputImpl.VideoFromFile(str(path)), str(path)
    except Exception:
        return {"video": [{"filename": filename, "subfolder": "", "type": folder_type}]}, str(path)


def cleanup_legacy_temp_files() -> None:
    import time
    try:
        import tempfile
        try:
            import folder_paths
            out_dir = Path(folder_paths.get_temp_directory())
        except Exception:
            out_dir = Path(tempfile.gettempdir())
        
        dirs_to_check = [out_dir]
        pkg_video_temp = Path(__file__).resolve().parents[1] / "video_temp"
        if pkg_video_temp.exists():
            dirs_to_check.append(pkg_video_temp)
            
        now = time.time()
        for d in dirs_to_check:
            if not d.exists():
                continue
            for p in d.glob("llm-mini-video-*"):
                try:
                    if p.is_file() and (now - p.stat().st_mtime > 7200):
                        p.unlink(missing_ok=True)
                except OSError as e:
                    logger.debug(f"Failed to auto-clean legacy temp file {p}: {e}")
    except Exception as e:
        logger.debug(f"Auto-cleanup failed: {e}")


threading.Thread(target=cleanup_legacy_temp_files, daemon=True).start()
