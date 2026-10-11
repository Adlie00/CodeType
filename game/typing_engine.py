"""Pure character validation and typing metrics for CODETYPE."""

from __future__ import annotations

import time
from collections.abc import Callable


class TypingEngine:
    def __init__(
        self,
        target: str,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not target:
            raise ValueError("A typing target cannot be empty")
        self.target = target
        self.index = 0
        self.correct_characters = 0
        self.total_characters = 0
        self.mistakes = 0
        self._clock = clock or time.monotonic
        self._started_at: float | None = None

    @property
    def completed(self) -> bool:
        return self.index >= len(self.target)

    @property
    def progress(self) -> float:
        return self.index / len(self.target)

    @property
    def typed_text(self) -> str:
        return self.target[: self.index]

    @property
    def remaining_text(self) -> str:
        return self.target[self.index :]

    @property
    def current_character(self) -> str | None:
        if self.completed:
            return None
        return self.target[self.index]

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._started_at)

    @property
    def wpm(self) -> float:
        minutes = self.elapsed_seconds / 60
        if minutes <= 0:
            return 0.0
        return self.correct_characters / 5 / minutes

    @property
    def accuracy(self) -> float:
        if self.total_characters <= 0:
            return 100.0
        return max(0.0, min(100.0, self.correct_characters / self.total_characters * 100))

    def handle_character(self, character: str) -> bool:
        if self.completed or len(character) != 1:
            return False
        self._start()
        self.total_characters += 1
        if character == self.target[self.index]:
            self.index += 1
            self.correct_characters += 1
            return True
        self.mistakes += 1
        return False

    def backspace(self) -> bool:
        if self.index <= 0:
            return False
        self._start()
        self.index -= 1
        self.correct_characters = max(0, self.correct_characters - 1)
        self.total_characters = max(0, self.total_characters - 1)
        return True

    def _start(self) -> None:
        if self._started_at is None:
            self._started_at = self._clock()
