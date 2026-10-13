"""Central mutable state for a CODETYPE run."""

from __future__ import annotations

import time
from collections.abc import Callable

from game.constants import (
    COMBO_MILESTONES,
    DIFFICULTY_EASY,
    MODE_CAMPAIGN,
    STARTING_LIVES,
)
from game.player import Player
from game.scoring import ScoreBreakdown, Scoring
from game.wpm import WpmTracker


class GameState:
    def __init__(
        self,
        mode: str = MODE_CAMPAIGN,
        player_name: str = "PLAYER",
        starting_lives: int = STARTING_LIVES,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.mode = mode
        self.player_name = player_name
        self.player = Player(starting_lives)
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.wave_number = 1
        self.current_difficulty = DIFFICULTY_EASY
        self.waves_completed = 0
        self.enemies_destroyed = 0
        self.mistakes = 0
        self.correct_characters = 0
        self.total_characters = 0
        self.current_wpm = 0.0
        self.best_wpm = 0.0
        self.bosses_destroyed = 0
        self._pending_milestone = 0
        self._clock = clock or time.monotonic
        self._typing_started_at: float | None = None
        self._scoring = Scoring()
        self._wpm = WpmTracker(clock=self._clock)

    @property
    def accuracy(self) -> float:
        if self.total_characters <= 0:
            return 100.0
        return max(0.0, min(100.0, self.correct_characters / self.total_characters * 100))

    @property
    def average_wpm(self) -> float:
        if self._typing_started_at is None or self.correct_characters <= 0:
            return 0.0
        minutes = max(0.0, (self._clock() - self._typing_started_at) / 60.0)
        if minutes <= 0:
            return 0.0
        return self.correct_characters / 5.0 / minutes

    @property
    def is_game_over(self) -> bool:
        return not self.player.alive

    def record_attempt(self, correct_delta: int, total_delta: int) -> None:
        if total_delta > 0 and self._typing_started_at is None:
            self._typing_started_at = self._clock()
        self.correct_characters = max(0, self.correct_characters + correct_delta)
        self.total_characters = max(0, self.total_characters + total_delta)
        self._wpm.sample(self.correct_characters)
        self.current_wpm = self._wpm.wpm
        self.best_wpm = max(self.best_wpm, self.current_wpm)

    def tick_wpm(self) -> None:
        """Recompute the rolling WPM as the window slides with no typing."""
        self._wpm.sample(self.correct_characters)
        self.current_wpm = self._wpm.wpm

    def record_mistake(self) -> None:
        self.mistakes += 1
        self.combo = 0

    def record_destroy(
        self,
        text: str,
        difficulty: str,
        wave_number: int,
        wpm: float,
        accuracy: float,
        boss: bool = False,
    ) -> ScoreBreakdown:
        previous_combo = self.combo
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        self.enemies_destroyed += 1
        if boss:
            self.bosses_destroyed += 1
        milestone = self._crossed_milestone(previous_combo, self.combo)
        if milestone:
            self._pending_milestone = milestone
        breakdown = self._scoring.calculate(
            text=text,
            difficulty=difficulty,
            wave_number=wave_number,
            combo=self.combo,
            wpm=wpm,
            accuracy=accuracy,
            boss=boss,
        )
        self.score += breakdown.total
        return breakdown

    def take_combo_milestone(self) -> int:
        """Consume a pending combo milestone; 0 when none is queued."""
        milestone = self._pending_milestone
        self._pending_milestone = 0
        return milestone

    @staticmethod
    def _crossed_milestone(previous: int, current: int) -> int:
        """The milestone just passed by this kill, or 0."""
        for milestone in COMBO_MILESTONES:
            if previous < milestone <= current:
                return milestone
        return 0

    def record_missed_enemy(self, costs_life: bool = True) -> bool:
        """A miss always breaks the combo; only some modes charge a life.

        Endless has no lives, so it calls this with ``costs_life=False``: the
        combo still resets, but the player can never be killed by a miss.
        Returns True when that miss ended the run.
        """
        self.combo = 0
        if not costs_life:
            return False
        return self.player.take_damage()

    def set_wave(self, wave_number: int, difficulty: str) -> None:
        self.wave_number = wave_number
        self.current_difficulty = difficulty

    def record_wave_completed(self) -> None:
        self.waves_completed += 1

    def stats(self) -> dict[str, object]:
        average_wpm = self.average_wpm
        return {
            "player_name": self.player_name,
            "mode": self.mode,
            "score": self.score,
            "wpm": round(average_wpm, 1),
            "current_wpm": round(self.current_wpm, 1),
            "best_wpm": round(self.best_wpm, 1),
            "accuracy": round(self.accuracy, 1),
            "max_combo": self.max_combo,
            "waves": self.waves_completed,
            "enemies": self.enemies_destroyed,
            "bosses": self.bosses_destroyed,
            "mistakes": self.mistakes,
            "lives": self.player.lives,
            "wave": self.wave_number,
            "difficulty": self.current_difficulty,
        }
