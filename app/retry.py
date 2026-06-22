from __future__ import annotations

from collections.abc import Callable
from time import sleep
from typing import TypeVar

T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    *,
    attempts: int,
    initial_delay_seconds: float,
    backoff_multiplier: float,
    max_delay_seconds: float,
    sleep_func: Callable[[float], None] = sleep,
    non_retryable_exceptions: tuple[type[Exception], ...] = (),
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    delay = initial_delay_seconds
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except non_retryable_exceptions:
            raise
        except Exception:
            if attempt == attempts:
                raise
            if delay > 0:
                sleep_func(min(delay, max_delay_seconds))
            delay *= backoff_multiplier

    raise RuntimeError("unreachable retry state")
