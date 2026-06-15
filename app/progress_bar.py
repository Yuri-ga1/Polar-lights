from __future__ import annotations

import sys
from threading import Lock
from typing import TextIO


class ProgressBar:
    """Консольный индикатор выполнения для операций с известным объёмом."""

    def __init__(
        self,
        total: int,
        current: int = 0,
        *,
        width: int = 30,
        description: str = "",
        stream: TextIO | None = None,
        auto_render: bool = True,
    ) -> None:
        if total <= 0:
            raise ValueError("total должен быть больше нуля")
        if width <= 0:
            raise ValueError("width должен быть больше нуля")

        self.total = total
        self.width = width
        self.description = description.strip()
        self.stream = stream or sys.stdout
        self._lock = Lock()
        self._current = 0
        self._finished = False
        self._closed = False

        self._set_current(current)
        if auto_render:
            self.render()

    @property
    def current(self) -> int:
        return self._current

    @property
    def percentage(self) -> int:
        return int(self._current * 100 / self.total)

    @property
    def is_finished(self) -> bool:
        return self._finished

    def update(self, current: int) -> None:
        """Устанавливает текущее значение и перерисовывает индикатор."""
        with self._lock:
            self._set_current(current)
            self._render_unlocked()

    def advance(self, amount: int = 1) -> None:
        """Увеличивает текущее значение на ``amount``."""
        if amount < 0:
            raise ValueError("amount не может быть отрицательным")
        with self._lock:
            self._set_current(min(self.total, self._current + amount))
            self._render_unlocked()

    def finish(self) -> None:
        """Завершает индикатор, доводя его до 100%."""
        self.update(self.total)

    def close(self) -> None:
        """Завершает строку вывода, не изменяя текущее значение."""
        with self._lock:
            if not self._closed:
                self.stream.write("\n")
                self.stream.flush()
                self._closed = True

    def render(self) -> None:
        """Выводит текущее состояние без изменения значения."""
        with self._lock:
            self._render_unlocked()

    def _set_current(self, current: int) -> None:
        if not 0 <= current <= self.total:
            raise ValueError("current должен находиться в диапазоне от 0 до total")
        self._current = current

    def _render_unlocked(self) -> None:
        self._closed = False
        completed_width = self._current * self.width // self.total
        bar = "#" * completed_width + "-" * (self.width - completed_width)
        prefix = f"{self.description} " if self.description else ""
        line = (
            f"\r{prefix}[{bar}] "
            f"{self.percentage}% {self._current}/{self.total}"
        )

        self.stream.write(line)
        if self._current == self.total and not self._finished:
            self.stream.write("\n")
            self._finished = True
            self._closed = True
        self.stream.flush()
