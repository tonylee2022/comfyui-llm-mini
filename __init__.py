"""ComfyUI LLM Mini custom nodes."""

import logging

class VideoPollFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # 过滤掉 xAI 视频状态轮询的 GET 请求日志，保留其他所有日志（如 POST 提交生成请求）
        if "GET https://api.x.ai/v1/videos/" in msg:
            return False
        return True

# 保留正常的 INFO 级别请求日志，但过滤高频的视频状态轮询日志
httpx_logger = logging.getLogger("httpx")
httpcore_logger = logging.getLogger("httpcore")

httpx_logger.setLevel(logging.INFO)
httpcore_logger.setLevel(logging.INFO)

httpx_logger.addFilter(VideoPollFilter())
httpcore_logger.addFilter(VideoPollFilter())

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .server import register_routes

register_routes()

WEB_DIRECTORY = "./web/js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
