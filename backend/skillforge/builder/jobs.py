"""Run slow work (model calls, sandbox runs) off the request, so the browser polls instead of waiting."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor


class JobRunner:
    """A small thread pool. With inline=True the work runs at once on the calling thread (used by tests).

    The functions given to `submit` must catch their own errors and record them: a pool swallows exceptions."""

    def __init__(self, inline: bool = False, workers: int = 2) -> None:
        self.inline = inline
        self._pool = None if inline else ThreadPoolExecutor(max_workers=workers, thread_name_prefix="skillforge-job")

    def submit(self, fn: Callable[..., None], *args) -> None:
        if self._pool is None:
            fn(*args)
        else:
            self._pool.submit(fn, *args)

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
