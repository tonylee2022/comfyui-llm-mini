from __future__ import annotations

import time


def check_interrupted() -> None:
    try:
        import comfy.model_management

        comfy.model_management.throw_exception_if_processing_interrupted()
    except ModuleNotFoundError:
        return


def interruptible_sleep(seconds: float, interval: float = 0.5) -> None:
    deadline = time.time() + max(float(seconds), 0.0)
    while True:
        check_interrupted()
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(interval, remaining))
