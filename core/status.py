from __future__ import annotations

import time
import threading
from typing import Any

def get_unique_id(node: Any, unique_id_arg: str | None = None) -> str | None:
    """Helper to retrieve the unique node ID for both standard nodes and IO.ComfyNode."""
    if unique_id_arg is not None:
        return unique_id_arg
    try:
        return node.hidden.unique_id
    except AttributeError:
        pass
    try:
        return getattr(node, "unique_id", None)
    except Exception:
        pass
    return None

class StatusUpdater:
    def __init__(self, node_id: str | None, initial_status: str = "Generating"):
        self.node_id = node_id
        self.initial_status = initial_status
        self.start_time = time.time()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def _run(self) -> None:
        while not self.stop_event.wait(1.0):
            if self.stop_event.is_set():
                break
            elapsed = int(time.time() - self.start_time)
            status_text = f"Status: {self.initial_status}\nTime elapsed: {elapsed}s"
            self._send(status_text)

    def update_status(self, new_status: str) -> None:
        self.initial_status = new_status
        elapsed = int(time.time() - self.start_time)
        self._send(f"Status: {self.initial_status}\nTime elapsed: {elapsed}s")

    def _send(self, text: str) -> None:
        if not self.node_id:
            return
        try:
            from server import PromptServer
            if PromptServer.instance:
                PromptServer.instance.send_progress_text(text, self.node_id)
        except Exception:
            pass

    def __enter__(self) -> StatusUpdater:
        if not self.node_id:
            return self
        self._send(f"Status: {self.initial_status}\nTime elapsed: 0s")
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.thread:
            self.stop_event.set()
            self.thread.join(timeout=1.0)
        if self.node_id:
            if exc_type is not None:
                err_msg = str(exc_val)
                err_msg_lower = err_msg.lower()
                
                is_safety_blocked = (
                    "image_prohibited_content" in err_msg_lower
                    or "safety" in err_msg_lower
                    or "moderation" in err_msg_lower
                    or "policy" in err_msg_lower
                    or "安全政策" in err_msg
                    or "安全策略" in err_msg
                    or "内容安全" in err_msg
                )
                
                first_line = err_msg.split('\n')[0].strip()
                if is_safety_blocked:
                    try:
                        from .xai import _is_chinese_locale
                        is_zh = _is_chinese_locale()
                    except Exception:
                        is_zh = False
                    
                    status_lbl = "Status: 被安全政策拦截" if is_zh else "Status: Blocked (Safety Policy)"
                    self._send(f"{status_lbl}\nError: {first_line[:120]}")
                else:
                    self._send(f"Status: Failed\nError: {first_line[:120]}")
            else:
                elapsed = int(time.time() - self.start_time)
                self._send(f"Status: Completed\nTime elapsed: {elapsed}s")
