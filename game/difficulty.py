"""Difficulty profiles used by the CODETYPE gameplay engine."""

from __future__ import annotations

from dataclasses import dataclass

from game.constants import (
    DIFFICULTY_BOSS,
    DIFFICULTY_EASY,
    DIFFICULTY_EXPERT,
    DIFFICULTY_HARD,
    DIFFICULTY_MEDIUM,
    DIFFICULTY_ORDER,
    DIFFICULTY_MULTIPLIERS,
    ENEMY_BOSS,
    ENEMY_FAST,
    ENEMY_NORMAL,
    ENEMY_SPECIAL,
    ENEMY_TANK,
)


@dataclass(frozen=True)
class DifficultyProfile:
    name: str
    speed_multiplier: float
    spawn_multiplier: float
    max_active: int
    enemy_types: tuple[str, ...]


_PROFILES: dict[str, DifficultyProfile] = {
    DIFFICULTY_EASY: DifficultyProfile(
        name=DIFFICULTY_EASY,
        speed_multiplier=0.8,
        spawn_multiplier=1.2,
        max_active=2,
        enemy_types=(ENEMY_NORMAL, ENEMY_NORMAL, ENEMY_FAST),
    ),
    DIFFICULTY_MEDIUM: DifficultyProfile(
        name=DIFFICULTY_MEDIUM,
        speed_multiplier=1.0,
        spawn_multiplier=1.0,
        max_active=2,
        enemy_types=(ENEMY_NORMAL, ENEMY_FAST, ENEMY_NORMAL, ENEMY_TANK),
    ),
    DIFFICULTY_HARD: DifficultyProfile(
        name=DIFFICULTY_HARD,
        speed_multiplier=1.25,
        spawn_multiplier=0.8,
        max_active=2,
        enemy_types=(ENEMY_FAST, ENEMY_NORMAL, ENEMY_TANK, ENEMY_SPECIAL),
    ),
    DIFFICULTY_EXPERT: DifficultyProfile(
        name=DIFFICULTY_EXPERT,
        speed_multiplier=1.55,
        spawn_multiplier=0.65,
        max_active=3,
        enemy_types=(ENEMY_FAST, ENEMY_TANK, ENEMY_NORMAL, ENEMY_SPECIAL),
    ),
    DIFFICULTY_BOSS: DifficultyProfile(
        name=DIFFICULTY_BOSS,
        speed_multiplier=1.4,
        spawn_multiplier=1.0,
        max_active=1,
        enemy_types=(ENEMY_BOSS,),
    ),
}


def get_profile(name: str) -> DifficultyProfile:
    try:
        return _PROFILES[name.upper()]
    except KeyError as exc:
        raise ValueError(f"Unknown difficulty: {name}") from exc


def difficulty_for_progress(
    progression: tuple[str, ...],
    completed: int,
    total: int,
) -> str:
    if not progression:
        raise ValueError("A difficulty progression cannot be empty")
    if total <= 0:
        return progression[0]
    position = min(len(progression) - 1, int(completed * len(progression) / total))
    return progression[position]


def tier_index(name: str | None) -> int:
    """Position of a difficulty in ``DIFFICULTY_ORDER``; 0 when unset."""
    if not name:
        return 0
    normalized = str(name).upper()
    return DIFFICULTY_ORDER.index(normalized) if normalized in DIFFICULTY_ORDER else 0


def shift_progression(
    progression: tuple[str, ...],
    start: str | None = None,
) -> tuple[str, ...]:
    """Lift a wave's tiers so none sits below the chosen start, keeping the ramp."""
    offset = tier_index(start)
    if not progression or not offset:
        return tuple(progression)
    top = len(DIFFICULTY_ORDER) - 1
    return tuple(
        DIFFICULTY_ORDER[min(top, tier_index(tier) + offset)] for tier in progression
    )


def difficulty_for_endless(wave_number: int, start: str | None = None) -> str:
    index = tier_index(start) + max(0, wave_number - 1)
    return DIFFICULTY_ORDER[min(len(DIFFICULTY_ORDER) - 1, index)]


def score_multiplier(name: str) -> float:
    normalized = name.upper()
    return DIFFICULTY_MULTIPLIERS.get(normalized, DIFFICULTY_MULTIPLIERS[DIFFICULTY_EXPERT])
