"""Rolling words-per-minute tracking over a short window.

The instantaneous rate of a single snippet collapses toward zero between
kills, which reads as a broken HUD. Sampling correct keystrokes over a short
sliding window keeps the displayed WPM meaningful.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from game.constants import WPM_WINDOW_SECONDS, WPM_WORD_LENGTH


class WpmTracker:
    #: Shortest span used as the rate denominator. Without it the first few
    #: samples of a window divide by a fraction of a second and report
    #: thousands of WPM.
    MIN_SPAN_SECONDS = 1.0

    def __init__(
        self,
        window_seconds: float = WPM_WINDOW_SECONDS,
        word_length: int = WPM_WORD_LENGTH,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._window = max(0.5, window_seconds)
        self._word_length = max(1, word_length)
        self._clock = clock or time.monotonic
        self._samples: deque[tuple[float, int]] = deque()
        self._peak = 0.0

    @property
    def wpm(self) -> float:
        if not self._samples:
            return 0.0
        newest_time, newest_chars = self._samples[-1]
        oldest_time, oldest_chars = self._samples[0]
        characters = newest_chars - oldest_chars
        if characters <= 0:
            return 0.0
        seconds = max(newest_time - oldest_time, self.MIN_SPAN_SECONDS)
        return characters / self._word_length / (seconds / 60.0)

    @property
    def peak(self) -> float:
        return max(self._peak, self.wpm)

    def sample(self, correct_characters: int) -> None:
        now = self._clock()
        self._samples.append((now, max(0, correct_characters)))
        cutoff = now - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        self._peak = max(self._peak, self.wpm)

    def reset(self) -> None:
        self._samples.clear()
        self._peak = 0.0
