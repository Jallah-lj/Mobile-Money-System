"""Asynchronous event dispatch for transaction integrations.

Transaction events (webhooks, notifications) are delivered on a background
worker thread, so a slow or failing integration can never delay or break a
payment. Every emitted event is still delivered to every listener, and
``wait_idle()`` lets tests (or shutdown hooks) drain the queue.

The worker thread exits after a short idle period and is restarted on demand,
so browser sessions do not leak permanently blocked threads.
"""

import contextlib
import queue
import threading


class EventDispatcher:
    """Delivers (event, payload) to a live list of listeners, off-thread."""

    def __init__(self, listeners: list, async_dispatch: bool = True):
        self._listeners = listeners  # live reference — appends are picked up
        self.async_dispatch = async_dispatch
        self._queue: queue.Queue = queue.Queue()
        self._cond = threading.Condition()
        self._pending = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def emit(self, event: str, payload: dict) -> None:
        """Queue an event for all listeners (or run it inline in sync mode)."""
        if not self.async_dispatch:
            self._run(event, payload)
            return
        with self._cond:
            self._pending += 1
        with self._lock:
            self._queue.put((event, payload))
            self._ensure_worker_locked()

    def _ensure_worker_locked(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._work, daemon=True, name="mms-event-dispatcher")
            self._thread.start()

    def _work(self) -> None:
        while True:
            try:
                event, payload = self._queue.get(timeout=30)
            except queue.Empty:
                # Idle: retire this thread (under the lock, so a concurrent
                # emit() either sees the queued item or restarts a worker).
                with self._lock:
                    if self._queue.empty():
                        self._thread = None
                        return
                continue
            try:
                self._run(event, payload)
            finally:
                with self._cond:
                    self._pending -= 1
                    self._cond.notify_all()

    def _run(self, event: str, payload: dict) -> None:
        for listener in list(self._listeners):
            # A broken listener must never break the transaction or the queue
            with contextlib.suppress(Exception):
                listener(event, payload)

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Block until every queued event has been delivered."""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending == 0, timeout=timeout)
