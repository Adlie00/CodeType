"""Boss enemy implementation for the CODETYPE engine."""

from __future__ import annotations

import math

from game.constants import (
    BOSS_INTRO_SECONDS,
    BOSS_PHASE_BREAKS,
    BOSS_PHASE_COLOURS,
    DIFFICULTY_BOSS,
    ENEMY_BOSS,
    NEON_RED,
)
from game.content import Challenge
from game.enemy import Enemy, panel_height
from game.ui import DESIGN_LAYOUT, Layout


class Boss(Enemy):
    """A long-code enemy with an intro sequence and three damage phases.

    Unlike the shorter types, a boss does not take up a fixed station: it keeps
    descending toward the warning line like any other card. Its snippet is the
    longest in the game, so it relies on two things to stay fair — the tier's
    slow base speed (``ENEMY_BASE_SPEEDS[ENEMY_BOSS]``) and the fairness cap in
    :meth:`Enemy.limit_speed_for`, which bounds it against the typing time of
    its own snippet. Normal spawns pause while one is on the field, so the fight
    is a single, wide, three-phase typing test that only ends when the snippet
    is cleared or it slips past the line.
    """

    def __init__(
        self,
        challenge: Challenge,
        difficulty: str = DIFFICULTY_BOSS,
        column_x: float | None = None,
        station: float | None = None,
        start_y: float | None = None,
        layout: Layout | None = None,
    ) -> None:
        super().__init__(
            challenge=challenge,
            difficulty=DIFFICULTY_BOSS if difficulty == DIFFICULTY_BOSS else difficulty,
            enemy_type=ENEMY_BOSS,
            column_x=column_x,
            station=station,
            start_y=start_y,
            layout=layout,
        )
        geo = DESIGN_LAYOUT if layout is None else layout
        self.width = geo.enemy_width + geo.boss_width_bonus
        self.height = max(self.height, panel_height(challenge.text, geo))
        # A boss card is wider, so its lane band is narrower: the lane is
        # re-resolved against the wider card.
        self._place_in_lane(column_x)
        self.x = self.column_x
        self.phase = 1
        self.intro_timer = BOSS_INTRO_SECONDS
        self.intro_active = start_y is None

    @property
    def phase_label(self) -> str:
        return f"PHASE {self.phase}"

    def begin_intro(self) -> None:
        """Re-arm the arrival banner and park the boss above the play field."""
        self.intro_active = True
        self.intro_timer = BOSS_INTRO_SECONDS
        self.y = -float(self.height)

    @property
    def phase_colour(self) -> tuple[int, int, int]:
        return BOSS_PHASE_COLOURS[min(self.phase - 1, len(BOSS_PHASE_COLOURS) - 1)]

    @property
    def display_colour(self) -> tuple[int, int, int]:
        return NEON_RED if self.intro_active else self.phase_colour

    def rebase(self, layout: Layout) -> None:
        """Re-derive boss geometry and keep the lane under the card.

        A boss overrides the base rebase because it is wider than a normal card
        and the lane band depends on the card width, so the lane is re-resolved
        after the new width is known. Descent is left to the base class: the
        position scales with the layout, and the caller re-applies the speed cap.
        """
        super().rebase(layout)
        self.width = layout.enemy_width + layout.boss_width_bonus
        self.height = max(self.height, panel_height(self.text, layout))
        self._place_in_lane()
        self.x = self.column_x

    def update(self, dt: float, danger_line: float) -> None:
        step = max(0.0, dt)
        if self.intro_active:
            self.intro_timer = max(0.0, self.intro_timer - step)
            self.age += step
            if self.intro_timer <= 0.0:
                self.intro_active = False
            return
        super().update(step, danger_line)
        self._update_phase()

    def _update_phase(self) -> None:
        remaining = self.health_ratio
        phase = 1
        for index, threshold in enumerate(BOSS_PHASE_BREAKS, start=2):
            if remaining <= threshold:
                phase = index
        self.phase = phase

    def warning_intensity(self) -> float:
        """Pulse strength while the intro banner is running."""
        if not self.intro_active:
            return 0.0
        remaining = self.intro_timer / BOSS_INTRO_SECONDS if BOSS_INTRO_SECONDS else 0.0
        return (0.5 + 0.5 * math.sin(self.age * 12.0)) * remaining
