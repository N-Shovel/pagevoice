"""Run slow engine work off the UI thread (SPEC M4: the UI never blocks).

    run_task(fn, on_done=..., on_failed=..., on_progress=...)

fn runs on a worker thread and gets one argument, report(value), which delivers value to
on_progress. Every callback runs on the UI thread: the relay object lives there, so Qt
queues the worker's signals to it.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

_running: set["_Relay"] = set()  # keeps relays alive until their task ends


class _Relay(QObject):
    progress = Signal(object)
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, on_done, on_failed, on_progress) -> None:
        super().__init__()
        self._on_done, self._on_failed, self._on_progress = on_done, on_failed, on_progress
        self.progress.connect(self._progress)
        self.done.connect(self._done)
        self.failed.connect(self._failed)

    @Slot(object)
    def _progress(self, value) -> None:
        if self._on_progress:
            self._on_progress(value)

    @Slot(object)
    def _done(self, value) -> None:
        _running.discard(self)
        if self._on_done:
            self._on_done(value)

    @Slot(object)
    def _failed(self, exc) -> None:
        _running.discard(self)
        if self._on_failed:
            self._on_failed(exc)
        else:
            raise exc


class _Runnable(QRunnable):
    def __init__(self, fn, relay: _Relay) -> None:
        super().__init__()
        self.fn, self.relay = fn, relay

    def run(self) -> None:
        try:
            result = self.fn(self.relay.progress.emit)
        except BaseException as exc:  # handed to the UI thread, never lost
            self.relay.failed.emit(exc)
        else:
            self.relay.done.emit(result)


def run_task(
    fn: Callable[[Callable[[Any], None]], Any],
    *,
    on_done: Callable[[Any], None] | None = None,
    on_failed: Callable[[BaseException], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
) -> None:
    relay = _Relay(on_done, on_failed, on_progress)
    _running.add(relay)
    QThreadPool.globalInstance().start(_Runnable(fn, relay))


def busy() -> bool:
    return bool(_running)


def wait_for_all(msecs: int = 10000) -> bool:
    """At quit: give running tasks time to stop (they're asked to first)."""
    return QThreadPool.globalInstance().waitForDone(msecs)
