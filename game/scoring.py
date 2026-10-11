"""Transparent score calculation for CODETYPE.

    total = (base + wave + speed + accuracy) x difficulty x combo x boss
"""

from __future__ import annotations

from dataclasses import dataclass

from game.constants import (
    ACCURACY_BONUS_RATE,
    BASE_SCORE_PER_CHAR,
    BOSS_MULTIPLIER,
    COMBO_MULTIPLIER_CAP,
    COMBO_MULTIPLIER_STEP,
    PERFECT_ACCURACY_BONUS,
    SPEED_BONUS_PER_WPM,
    SPEED_BONUS_THRESHOLD,
    WAVE_BONUS_PER_WAVE,
)
from game.difficulty import score_multiplier


@dataclass(frozen=True)
class ScoreBreakdown:
    base: int
    wave: int
    speed: int
    accuracy: int
    subtotal: int
    difficulty_mult: float
    combo_mult: float
    boss_mult: float
    total: int


class Scoring:
    def calculate(
        self,
        text: str,
        difficulty: str,
        wave_number: int,
        combo: int,
        wpm: float,
        accuracy: float,
        boss: bool = False,
    ) -> ScoreBreakdown:
        character_count = max(1, len(text))
        base = character_count * BASE_SCORE_PER_CHAR
        wave_bonus = max(0, wave_number) * WAVE_BONUS_PER_WAVE
        speed_bonus = int(
            max(0.0, min(2500.0, (wpm - SPEED_BONUS_THRESHOLD))) * SPEED_BONUS_PER_WPM
        )

        safe_accuracy = max(0.0, min(100.0, accuracy))
        if safe_accuracy >= 100.0:
            accuracy_bonus = PERFECT_ACCURACY_BONUS
        else:
            accuracy_bonus = int(round(base * safe_accuracy / 100.0 * ACCURACY_BONUS_RATE))

        subtotal = base + wave_bonus + speed_bonus + accuracy_bonus

        difficulty_mult = score_multiplier(difficulty)
        combo_mult = min(
            COMBO_MULTIPLIER_CAP,
            1.0 + max(0, combo - 1) * COMBO_MULTIPLIER_STEP,
        )
        boss_mult = BOSS_MULTIPLIER if boss else 1.0

        total = int(round(subtotal * difficulty_mult * combo_mult * boss_mult))
        return ScoreBreakdown(
            base=base,
            wave=wave_bonus,
            speed=speed_bonus,
            accuracy=accuracy_bonus,
            subtotal=subtotal,
            difficulty_mult=difficulty_mult,
            combo_mult=combo_mult,
            boss_mult=boss_mult,
            total=total,
        )

    def score(
        self,
        text: str,
        difficulty: str,
        wave_number: int,
        combo: int,
        wpm: float,
        accuracy: float,
        boss: bool = False,
    ) -> int:
        return self.calculate(
            text,
            difficulty,
            wave_number,
            combo,
            wpm,
            accuracy,
            boss,
        ).total
