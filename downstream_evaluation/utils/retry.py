import sys
import time
from typing import Callable

RETRYABLE_CODES = {429, 500, 502, 503, 504}


def with_retry(
    fn: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 10.0,
    **kwargs,
):
    for attempt in range(1, max_retries + 2):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            code = _extract_status_code(e)
            if code not in RETRYABLE_CODES or attempt > max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(
                f"      [Retry {attempt}/{max_retries}] HTTP {code} — retrying in {delay:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code", "http_status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    s = str(exc)
    for code in RETRYABLE_CODES:
        if str(code) in s:
            return code
    return None
