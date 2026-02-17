from __future__ import annotations

import time
from typing import Any, Callable, Tuple


def time_call(fn: Callable[..., Any], *args, **kwargs) -> Tuple[Any, float]:
    """
    Measure wall-clock latency of a call in milliseconds.

    Returns:
        (result, elapsed_ms)
    """
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return result, elapsed_ms

