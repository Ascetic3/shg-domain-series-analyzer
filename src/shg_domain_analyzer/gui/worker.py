from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..export import execute_series
from ..models import SeriesConfig


class AnalysisWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, config: SeriesConfig) -> None:
        super().__init__()
        self.config = config
        self._cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            outcome = execute_series(
                self.config,
                progress_callback=lambda current, total, filename: self.progress.emit(current, total, filename),
                cancel_check=self._cancel_event.is_set,
            )
            self.finished.emit(outcome)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @Slot()
    def cancel(self) -> None:
        self._cancel_event.set()

