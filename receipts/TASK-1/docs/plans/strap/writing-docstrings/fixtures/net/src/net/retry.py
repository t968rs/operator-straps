"""Retry policy for outbound requests."""
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def backoff_seconds(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    """Doubles ``base`` per attempt, capped at ``cap``."""
    return min(cap, base * 2 ** attempt)


def with_retries(call: Callable[[], T], attempts: int = 3) -> T:
    """Runs ``call`` until it succeeds or ``attempts`` runs are spent.

    Rules:
        only ``ConnectionError`` is retried,
        the wait before each retry is ``backoff_seconds`` of the attempt number
    Returns:
        the first successful result of ``call``
    Raises:
        ConnectionError when the last attempt fails or ``attempts`` is below 1
    """
    for attempt in range(attempts):
        try:
            return call()
        except ConnectionError:
            if attempt == attempts - 1:
                raise
            time.sleep(backoff_seconds(attempt))
    raise ConnectionError("no attempts made")
