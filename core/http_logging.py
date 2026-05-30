from __future__ import annotations

import logging


def log_http_response(method: str, url: str, response) -> None:
    reason = getattr(response, "reason", "") or ""
    status_code = getattr(response, "status_code", "")
    logging.getLogger("httpx").info(
        'HTTP Request: %s %s "HTTP/1.1 %s%s"',
        method.upper(),
        url,
        status_code,
        f" {reason}" if reason else "",
    )
