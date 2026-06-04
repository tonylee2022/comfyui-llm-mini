from __future__ import annotations

from comfy_api.latest import IO

from ..core.config import resolve_provider
from ..providers.xai import xai_video, xai_video_edit, xai_video_extend, xai_video_reference
from ..core.status import StatusUpdater, get_unique_id


class XAIVideoNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideo",
            display_name="xAI Video",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video", "grok-imagine-video-1.5-preview"], default="grok-imagine-video"),
                IO.Combo.Input("aspect_ratio", options=["auto", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"], default="auto"),
                IO.Combo.Input("resolution", options=["720p", "480p"], default="720p"),
                IO.Int.Input("duration", default=6, min=1, max=15, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
                IO.Image.Input("image", optional=True),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, duration, seed, image=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Generating (xAI Video)") as updater:
            info = resolve_provider("xai")
            api_key = info.get("api_key", "")
            res = xai_video(prompt, model_name, aspect_ratio, resolution, duration, seed, api_key, "", image, status_updater=updater)
            return (res[0],)


class XAIVideoReferenceNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoReference",
            display_name="xAI Multi-Reference Video",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Combo.Input("aspect_ratio", options=["auto", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16"], default="auto"),
                IO.Combo.Input("resolution", options=["720p", "480p"], default="720p"),
                IO.Int.Input("duration", default=6, min=1, max=10, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
                IO.Autogrow.Input(
                    "images",
                    template=IO.Autogrow.TemplateNames(
                        IO.Image.Input("image", optional=True),
                        names=[f"image_{i}" for i in range(1, 8)],
                        min=0,
                    ),
                    tooltip="Reference images (up to 7). Add image inputs dynamically as needed. Use @Image1, @Image2, etc. in your prompt to refer to them.",
                ),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, aspect_ratio, resolution, duration, seed, images=None, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        try:
            with StatusUpdater(node_id, "Generating (xAI Multi-Reference Video)") as updater:
                info = resolve_provider("xai")
                api_key = info.get("api_key", "")
                refs = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
                if isinstance(images, dict):
                    refs = [t for t in images.values() if t is not None]
                refs = refs[:7]
                res = xai_video_reference(prompt, model_name, aspect_ratio, resolution, duration, seed, api_key, "", refs, status_updater=updater)
                return (res[0],)
        except Exception as exc:
            raise RuntimeError(f"LLM Mini xAI video reference request failed: {exc}")


class XAIVideoEditNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoEdit",
            display_name="xAI Video Edit",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Video.Input("video"),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, video, seed, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Editing (xAI Video)") as updater:
            info = resolve_provider("xai")
            api_key = info.get("api_key", "")
            res = xai_video_edit(prompt, model_name, video, seed, api_key, "", status_updater=updater)
            return (res[0],)


class XAIVideoExtendNode(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="LLMMiniXAIVideoExtend",
            display_name="xAI Video Extend",
            category="ComfyUI LLM Mini/Video/xAI",
            inputs=[
                IO.String.Input("prompt", multiline=True, default=""),
                IO.Combo.Input("model_name", options=["grok-imagine-video"], default="grok-imagine-video"),
                IO.Video.Input("video"),
                IO.Int.Input("duration", default=8, min=2, max=10, step=1),
                IO.Int.Input("seed", default=0, min=0, max=2147483647, step=1, tooltip="Cache and re-execution control only; not sent to xAI."),
            ],
            outputs=[
                IO.Video.Output("video"),
            ],
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def execute(cls, prompt, model_name, video, duration, seed, unique_id=None):
        node_id = get_unique_id(cls, unique_id)
        with StatusUpdater(node_id, "Extending (xAI Video)") as updater:
            info = resolve_provider("xai")
            api_key = info.get("api_key", "")
            res = xai_video_extend(prompt, model_name, video, duration, seed, api_key, "", status_updater=updater)
            return (res[0],)
