from __future__ import annotations

import logging


def log_http_response(method: str, url: str, response) -> None:
    reason = getattr(response, "reason", "") or ""
    status_code = getattr(response, "status_code", "")
    logger = logging.getLogger("httpx")
    logger.info(
        'HTTP Request: %s %s "HTTP/1.1 %s%s"',
        method.upper(),
        url,
        status_code,
        f" {reason}" if reason else "",
    )
    if status_code and status_code != 200:
        try:
            body = getattr(response, "text", "")
            if body:
                logger.warning('HTTP Error Response: %s', body)
        except Exception:
            pass
