from __future__ import annotations

import os
import time
import tempfile
import logging
from pathlib import Path
from uuid import uuid4

import torch
from PIL import Image
import numpy as np

from comfy_api.latest import IO
from ...core.config import resolve_provider
from ...core.status import StatusUpdater, get_unique_id
from ...core.interrupt import check_interrupted
from ...core.media import downscale_image_tensor

logger = logging.getLogger("LLMMini")

MODELS_MAP = {
    "veo-2.0-generate-001": "veo-2.0-generate-001",
    "veo-3.1-generate-preview": "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview": "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview": "veo-3.1-lite-generate-preview",
    "veo-3.0-generate-001": "veo-3.0-generate-001",
    "veo-3.0-fast-generate-001": "veo-3.0-fast-generate-001",
}


def save_tensor_to_temp_png(image_tensor) -> str:
    # 强制等比缩放到最大 2048 x 2048 像素以内
    image_tensor = downscale_image_tensor(image_tensor)
    if len(image_tensor.shape) == 3:
        image_tensor = image_tensor.unsqueeze(0)
    arr = 255.0 * image_tensor[0].detach().cpu().numpy()
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    
    # 存储到临时文件
    temp_dir = tempfile.gettempdir()
    temp_path = os.path.join(temp_dir, f"llm_mini_google_video_input_{uuid4().hex}.png")
    img.save(temp_path, format="PNG")
    return temp_path


def google_video_generate_core(
    prompt: str,
    model: str,
    aspect_ratio: str,
    resolution: str,
    duration_seconds: int,
    enhance_prompt: bool,
    api_key: str,
    base_url: str = "",
    negative_prompt: str = "",
    person_generation: str = "ALLOW",
    generate_audio: bool = False,
    seed: int = 0,
    first_frame_image=None,
    last_frame_image=None,
    status_updater=None,
):
    check_interrupted()
    if not api_key:
        raise RuntimeError("No Google API key found for provider.")

    from google import genai
    from google.genai import types

    # 初始化 google-genai 客户端
    client_kwargs = {"api_key": api_key}
    http_options: dict = {"timeout": 180_000}
    if base_url:
        http_options["base_url"] = base_url
    client_kwargs["http_options"] = http_options
    client = genai.Client(**client_kwargs)

    uploaded_files = []
    temp_paths = []
    
    first_frame_input = None
    last_frame_input = None

    try:
        # 1. 准备起始参考图
        if first_frame_image is not None:
            try:
                temp_path = save_tensor_to_temp_png(first_frame_image)
                temp_paths.append(temp_path)
                with open(temp_path, "rb") as f:
                    bytes_data = f.read()
                first_frame_input = types.Image(
                    image_bytes=bytes_data,
                    mime_type="image/png"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to prepare starting frame: {e}")

        # 2. 准备结束参考图
        if last_frame_image is not None:
            try:
                temp_path = save_tensor_to_temp_png(last_frame_image)
                temp_paths.append(temp_path)
                with open(temp_path, "rb") as f:
                    bytes_data = f.read()
                last_frame_input = types.Image(
                    image_bytes=bytes_data,
                    mime_type="image/png"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to prepare ending frame: {e}")

        # 3. 构造视频生成配置
        person_gen_mode = "allow_adult" if person_generation == "ALLOW" else "dont_allow"
        
        config_args = {
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration_seconds,
            "person_generation": person_gen_mode,
        }
        
        # 根据模型版本设置 enhance_prompt 参数
        if "veo-2.0" in model:
            config_args["enhance_prompt"] = enhance_prompt
        else:
            # veo-3.0 和 veo-3.1 在 Gemini API 下均不支持 enhance_prompt 参数，在此彻底不传入
            pass

        if "veo-2.0" not in model:
            config_args["resolution"] = resolution
            if generate_audio:
                config_args["generate_audio"] = True

        if negative_prompt:
            config_args["negative_prompt"] = negative_prompt
            
        if last_frame_input is not None:
            config_args["last_frame"] = last_frame_input

        config = types.GenerateVideosConfig(**config_args)

        # 4. 发起生成请求
        if status_updater:
            status_updater.update_status("Generating")
        
        check_interrupted()
        operation = client.models.generate_videos(
            model=model,
            prompt=prompt,
            image=first_frame_input,
            config=config,
        )

        # 5. 轮询等待视频生成完成
        while not operation.done:
            check_interrupted()
            time.sleep(5)
            check_interrupted()
            operation = client.operations.get(operation)

        if operation.error:
            raise RuntimeError(f"Google Veo generation failed: {operation.error}")

        # 6. 获取视频输出并下载
        if not operation.response:
            raise RuntimeError(f"Google Veo operation completed but response is empty. Operation state: {operation}")
        
        # 检查是否由于 Responsible AI (RAI) 被安全过滤
        filtered_count = getattr(operation.response, "rai_media_filtered_count", 0) or 0
        if filtered_count > 0:
            reasons = getattr(operation.response, "rai_media_filtered_reasons", []) or []
            reason_msg = f": {reasons[0]}" if reasons else ""
            raise RuntimeError(
                f"Google Veo generation blocked by Responsible AI safety filters{reason_msg} "
                f"({filtered_count} video(s) filtered)."
            )
        
        generated_videos = operation.response.generated_videos
        if not generated_videos:
            raise RuntimeError(f"Google Veo did not return any videos. Response payload: {operation.response}")
            
        generated_video = generated_videos[0]
        
        try:
            import folder_paths
            out_dir = Path(folder_paths.get_temp_directory())
            folder_type = "temp"
        except Exception:
            out_dir = Path(__file__).resolve().parents[2] / "video_temp"
            folder_type = "temp"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"llm-mini-video-{uuid4().hex}.mp4"
        video_path = out_dir / filename

        if status_updater:
            status_updater.update_status("Downloading video")
            
        client.files.download(file=generated_video.video)
        generated_video.video.save(str(video_path))

        try:
            from comfy_api.latest import InputImpl
            video_output = InputImpl.VideoFromFile(str(video_path))
        except Exception:
            video_output = {"video": [{"filename": filename, "subfolder": "", "type": folder_type}]}

        return video_output, str(video_path)

    finally:
        # 7. 清理本地和 Google 端的临时文件
        for p in temp_paths:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        for uf in uploaded_files:
            try:
                client.files.delete(name=uf.name)
            except Exception as e:
                logger.error(f"Failed to delete Google temp uploaded file {uf.name}: {e}")


class VeoVideoGenerationNode(IO.ComfyNode):
    """Generates videos from text prompts using Google's Veo 2 API."""

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleVeo2Video",
            display_name="Google Veo 2 Video Generation",
            category="ComfyUI LLM Mini/Video/Google",
            description="Generates videos from text prompts using Google's Veo 2 API",
            inputs=[
                IO.String.Input("prompt", multiline=True, default="", tooltip="Text description of the video"),
                IO.String.Input("negative_prompt", multiline=True, default="", tooltip="Negative text prompt to guide what to avoid in the video"),
                IO.Combo.Input("aspect_ratio", options=["16:9", "9:16"], default="16:9", tooltip="Aspect ratio of the output video"),
                IO.Int.Input("duration_seconds", default=5, min=5, max=8, step=1, tooltip="Duration of the output video in seconds"),
                IO.Boolean.Input("enhance_prompt", default=True, tooltip="Whether to enhance the prompt with AI assistance", optional=True),
                IO.Combo.Input("person_generation", options=["ALLOW", "BLOCK"], default="ALLOW", tooltip="Whether to allow generating people in the video", optional=True),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Seed for video generation (0 for random)", optional=True),
                IO.Image.Input("image", optional=True, tooltip="Optional reference image to guide video generation"),
                IO.Combo.Input("model", options=["veo-2.0-generate-001"], default="veo-2.0-generate-001", tooltip="Veo 2 model to use for video generation", optional=True),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        negative_prompt="",
        aspect_ratio="16:9",
        duration_seconds=5,
        enhance_prompt=True,
        person_generation="ALLOW",
        seed=0,
        image=None,
        model="veo-2.0-generate-001",
        unique_id=None,
    ):
        model_id = MODELS_MAP[model]
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Generating (Google Veo 2 Video)") as updater:
            info = resolve_provider("google")
            api_key = info.get("api_key", "")
            base_url = info.get("base_url", "")
            res = google_video_generate_core(
                prompt=prompt,
                model=model_id,
                aspect_ratio=aspect_ratio,
                resolution="720p", # Veo 2.0 默认且固定为 720p 视频输出
                duration_seconds=duration_seconds,
                enhance_prompt=enhance_prompt,
                api_key=api_key,
                base_url=base_url,
                negative_prompt=negative_prompt,
                person_generation=person_generation,
                generate_audio=False,
                seed=seed,
                first_frame_image=image,
                status_updater=updater,
            )
            return (res[0],)


class Veo3VideoGenerationNode(IO.ComfyNode):
    """Generates videos from text prompts using Google's Veo 3 API."""

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleVeo3Video",
            display_name="Google Veo 3 Video Generation",
            category="ComfyUI LLM Mini/Video/Google",
            description="Generates videos from text prompts using Google's Veo 3 API",
            inputs=[
                IO.String.Input("prompt", multiline=True, default="", tooltip="Text description of the video"),
                IO.String.Input("negative_prompt", multiline=True, default="", tooltip="Negative text prompt to guide what to avoid in the video"),
                IO.Combo.Input("aspect_ratio", options=["16:9", "9:16"], default="16:9", tooltip="Aspect ratio of the output video"),
                IO.Combo.Input("resolution", options=["720p", "1080p", "4k"], default="720p", tooltip="Output video resolution. 4K is not available for veo-3.1-lite and veo-3.0 models.", optional=True),
                IO.Int.Input("duration_seconds", default=8, min=4, max=8, step=2, tooltip="Duration of the output video in seconds", optional=True),
                IO.Combo.Input("person_generation", options=["ALLOW", "BLOCK"], default="ALLOW", tooltip="Whether to allow generating people in the video", optional=True),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Seed for video generation (0 for random)", optional=True),
                IO.Image.Input("image", optional=True, tooltip="Optional reference image to guide video generation"),
                IO.Combo.Input("model", options=[
                    "veo-3.1-generate-preview",
                    "veo-3.1-fast-generate-preview",
                    "veo-3.1-lite-generate-preview",
                    "veo-3.0-generate-001",
                    "veo-3.0-fast-generate-001",
                ], default="veo-3.0-generate-001", tooltip="Veo 3 model to use for video generation", optional=True),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        negative_prompt="",
        aspect_ratio="16:9",
        resolution="720p",
        duration_seconds=8,
        person_generation="ALLOW",
        seed=0,
        image=None,
        model="veo-3.0-generate-001",
        unique_id=None,
    ):
        if resolution == "4k" and ("lite" in model or "3.0" in model):
            raise Exception("4K resolution is not supported by the veo-3.1-lite or veo-3.0 models.")

        model_id = MODELS_MAP[model]
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Generating (Google Veo 3 Video)") as updater:
            info = resolve_provider("google")
            api_key = info.get("api_key", "")
            base_url = info.get("base_url", "")
            res = google_video_generate_core(
                prompt=prompt,
                model=model_id,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration,
                enhance_prompt=True,
                api_key=api_key,
                base_url=base_url,
                negative_prompt=negative_prompt,
                person_generation=person_generation,
                generate_audio=False,
                seed=seed,
                first_frame_image=image,
                status_updater=updater,
            )
            return (res[0],)


class Veo3FirstLastFrameNode(IO.ComfyNode):
    """Generate video using prompt and first and last frames."""

    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniGoogleVeo3FirstLastFrame",
            display_name="Google Veo 3 First-Last-Frame",
            category="ComfyUI LLM Mini/Video/Google",
            description="Generate video using prompt and first and last frames.",
            inputs=[
                IO.String.Input("prompt", multiline=True, default="", tooltip="Text description of the video"),
                IO.String.Input("negative_prompt", multiline=True, default="", tooltip="Negative text prompt to guide what to avoid in the video"),
                IO.Combo.Input("resolution", options=["720p", "1080p", "4k"], default="720p"),
                IO.Combo.Input("aspect_ratio", options=["16:9", "9:16"], default="16:9", tooltip="Aspect ratio of the output video"),
                IO.Int.Input("duration_seconds", default=8, min=4, max=8, step=2, tooltip="Duration of the output video in seconds"),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, control_after_generate=True, tooltip="Seed for video generation"),
                IO.Image.Input("start_image", tooltip="Start frame image"),
                IO.Image.Input("end_image", tooltip="End frame image"),
                IO.Combo.Input("model", options=["veo-3.1-generate-preview", "veo-3.1-fast-generate-preview", "veo-3.1-lite-generate-preview"], default="veo-3.1-generate-preview"),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(
        cls,
        prompt,
        negative_prompt,
        resolution,
        aspect_ratio,
        duration_seconds,
        seed,
        start_image,
        end_image,
        model,
        unique_id=None,
    ):
        if "lite" in model and resolution == "4k":
            raise Exception("4K resolution is not supported by the veo-3.1-lite model.")

        model_id = MODELS_MAP[model]
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Generating (Google Veo 3 First-Last-Frame)") as updater:
            info = resolve_provider("google")
            api_key = info.get("api_key", "")
            base_url = info.get("base_url", "")
            res = google_video_generate_core(
                prompt=prompt,
                model=model_id,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                duration_seconds=duration_seconds,
                enhance_prompt=True,
                api_key=api_key,
                base_url=base_url,
                negative_prompt=negative_prompt,
                person_generation="ALLOW",
                generate_audio=False,
                seed=seed,
                first_frame_image=start_image,
                last_frame_image=end_image,
                status_updater=updater,
            )
            return (res[0],)


NODE_CLASS_MAPPINGS = {
    "LLMMiniGoogleVeo2Video": VeoVideoGenerationNode,
    "LLMMiniGoogleVeo3Video": Veo3VideoGenerationNode,
    "LLMMiniGoogleVeo3FirstLastFrame": Veo3FirstLastFrameNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LLMMiniGoogleVeo2Video": "Google Veo 2 Video Generation",
    "LLMMiniGoogleVeo3Video": "Google Veo 3 Video Generation",
    "LLMMiniGoogleVeo3FirstLastFrame": "Google Veo 3 First-Last-Frame",
}
