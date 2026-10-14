"""Enemy movement and per-enemy typing state.

Enemies descend vertically from above the play field. ``y`` is the falling
axis, ``x`` is the display column: a card sits in one of the field's lanes
and stays there, with Special, Fast and Boss drifting sideways.

Every enemy, bosses included, is bounded by :meth:`Enemy.limit_speed_for`, so
none can reach the warning line before its snippet could reasonably be typed.
"""

from __future__ import annotations

import math
import random
from bisect import bisect_right

from game.constants import (
    ENEMY_BASE_SPEEDS,
    ENEMY_BOSS,
    ENEMY_FAST,
    ENEMY_MAX_LINES,
    ENEMY_NORMAL,
    ENEMY_SPECIAL,
    ENEMY_TANK,
    DESCENT_REFERENCE_CPS,
)
from game.content import Challenge
from game.difficulty import get_profile
from game.syntax import TokenStream
from game.typing_engine import TypingEngine
from game.ui import DESIGN_LAYOUT, Layout


def line_bounds(text: str) -> tuple[tuple[int, int], ...]:
    """Half-open character span of every line, newlines excluded.

    ``line_bounds[-1]`` ends at ``len(text)`` rather than at a newline, so the
    last line of a snippet is a span like any other and the renderer never has
    to special-case it.
    """
    bounds = []
    start = 0
    for index, character in enumerate(text):
        if character == "\n":
            bounds.append((start, index))
            start = index + 1
    bounds.append((start, len(text)))
    return tuple(bounds)


def panel_height(text: str, layout: Layout | None = None) -> int:
    """Height needed to show at most ``ENEMY_MAX_LINES`` lines of ``text``."""
    geo = DESIGN_LAYOUT if layout is None else layout
    lines = min(ENEMY_MAX_LINES, max(1, len(text.splitlines())))
    body = (
        geo.enemy_header_height
        + lines * geo.enemy_line_height
        + geo.enemy_footer_height
    )
    return min(geo.enemy_max_height, body)


def base_speed_for(enemy_type: str, difficulty: str) -> float:
    """Nominal descent speed for a type, before any length-based cap."""
    base = ENEMY_BASE_SPEEDS.get(enemy_type, ENEMY_BASE_SPEEDS[ENEMY_NORMAL])
    return base * get_profile(difficulty).speed_multiplier


class Enemy:
    def __init__(
        self,
        challenge: Challenge,
        difficulty: str,
        enemy_type: str = ENEMY_NORMAL,
        column_x: float | None = None,
        station: float | None = None,
        start_y: float | None = None,
        layout: Layout | None = None,
    ) -> None:
        self.challenge = challenge
        self.text = challenge.text
        self.language = challenge.language
        self.difficulty = difficulty
        self.enemy_type = enemy_type
        self.typing = TypingEngine(challenge.text)
        # Tokenised once, here, because the card redraws every frame and the
        # snippet never changes: the text belongs to the immutable challenge, so
        # this stays valid for the enemy's whole life, resize included.
        self.tokens = TokenStream(self.text, self.language)
        # Same reasoning for the line spans: the card shows one line at a time,
        # so this is asked "which line is the cursor on" every single frame.
        self.line_bounds = line_bounds(self.text)
        self.line_starts = [start for start, _ in self.line_bounds]
        # (box, size) of the last code font fit. Invalidated by comparing the
        # box, which is the only thing a resize actually changes.
        self.code_size_cache: tuple[tuple[int, int], int] | None = None
        self.max_health = max(1, challenge.length)
        self.health = self.max_health
        self.layout = DESIGN_LAYOUT if layout is None else layout
        self.width = self.layout.enemy_width
        self.height = panel_height(challenge.text, self.layout)
        self.line_height = self.layout.enemy_line_height
        # The lane is kept as a 0..1 station, not a pixel, so a resize re-derives
        # the same relative position instead of snapping every card to the left.
        self.station = random.random() if station is None else min(1.0, max(0.0, station))
        self.column_x = 0.0
        self._place_in_lane(column_x)
        self.y = -float(self.height) if start_y is None else float(start_y)
        self.x = self.column_x
        self.spawned = start_y is not None
        self.nominal_speed = self.layout.speed(base_speed_for(enemy_type, difficulty))
        self.speed = self.nominal_speed
        self.speed_limited = False
        self.alive = True
        self.escaped = False
        self.flash_timer = 0.0
        self.pulse = 0.0
        self.age = 0.0
        self._jitter_seed = random.uniform(0.0, math.tau)
        self.is_boss = enemy_type == ENEMY_BOSS

    def _place_in_lane(self, column_x: float | None = None) -> None:
        """Resolve this card's lane against the current layout.

        An explicit ``column_x`` wins and is converted back into a station, so an
        enemy positioned by hand still survives a resize in the same place.
        """
        if column_x is None:
            self.column_x = self.layout.column_x(self.width, self.station)
            return
        left, right = self.layout.column_band(self.width)
        self.station = (
            min(1.0, max(0.0, (float(column_x) - left) / (right - left)))
            if right > left
            else 0.0
        )
        self.column_x = float(column_x)

    def line_index_for(self, cursor: int) -> int:
        """Index of the line the typing cursor sits on.

        A cursor parked on the newline that ends a line still belongs to that
        line: the line only changes once the newline itself has been typed,
        which is what makes the card advance on Enter.
        """
        index = bisect_right(self.line_starts, cursor) - 1
        return max(0, min(index, len(self.line_bounds) - 1))

    @property
    def code_height(self) -> int:
        """Vertical room for code lines once header and footer are paid for."""
        footer = self.layout.enemy_header_height + self.layout.enemy_footer_height
        return max(self.line_height, self.height - footer)

    @property
    def health_ratio(self) -> float:
        return max(0.0, min(1.0, self.health / self.max_health))

    @property
    def progress(self) -> float:
        return self.typing.progress

    @property
    def type_label(self) -> str:
        return self.enemy_type.upper()

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def rebase(self, layout: Layout) -> None:
        """Adopt a new display layout mid-flight, e.g. after a window resize.

        An enemy in the air holds pixel geometry and a pixel position that were
        derived from the old surface, so both have to be re-derived or a card
        resized mid-run would be the wrong size and a boss would sit off its
        station. Positions scale by the ratio of the two scales, which keeps the
        enemy's progress down the field and its sway offset proportional. The
        lane is re-derived from the stored station, so a card keeps its place
        across the field rather than snapping back to the left edge.
        """
        old_scale = self.layout.scale
        ratio = layout.scale / old_scale if old_scale else 1.0
        self.x *= ratio
        self.y *= ratio
        self.layout = layout
        self.width = layout.enemy_width
        self.height = panel_height(self.text, layout)
        self.line_height = layout.enemy_line_height
        self._place_in_lane()
        self.nominal_speed = layout.speed(base_speed_for(self.enemy_type, self.difficulty))
        # The old speed was a pixel value derived from the old layout, so it
        # cannot be carried over. The caller re-applies the cap via
        # ``limit_speed_for``, which derives it from ``nominal_speed``.
        self.speed = self.nominal_speed
        self.speed_limited = False

    def limit_speed_for(
        self,
        danger_line: float,
        reference_cps: float = DESCENT_REFERENCE_CPS,
        queue_seconds: float | None = None,
    ) -> None:
        """Cap descent speed so the whole field can be cleared in time.

        Only one enemy is typed at a time, so an enemy must survive not just
        its own typing time but the time to clear everything queued ahead of
        it. Three 70-character HARD enemies need ~21s of typing between them
        but only ~14s of descent, so the queue is unwinnable no matter how
        fast the player is. Dividing the available travel by that total is what
        keeps long code slow and every enemy fair.

        ``queue_seconds`` is the typing time for this enemy *and* everything
        queued ahead of it, which the caller can sum exactly. The fallback
        approximates it as this enemy's own typing time times the tier's
        concurrency, which is only right when the queued snippets are all the
        same length: a short enemy behind a long one would be allowed to arrive
        before the player could possibly have finished the queue, and the life
        would be lost no matter how well it was typed.

        The cap is measured from ``nominal_speed``, not from the current
        ``speed``, so re-applying it after a resize recomputes the cap from the
        new layout instead of ratcheting an already-capped enemy lower.
        """
        travel = max(1.0, danger_line - self.y)
        if queue_seconds is None:
            typing_seconds = max(1.0, len(self.text) / max(0.1, reference_cps))
            queued = max(1, get_profile(self.difficulty).max_active)
            queue_seconds = typing_seconds * queued
        queue_seconds = max(1.0, queue_seconds)
        self.speed = min(self.nominal_speed, travel / queue_seconds)
        self.speed_limited = self.speed < self.nominal_speed

    def type_character(self, character: str) -> str:
        if not self.alive or not character:
            return "ignored"
        correct = self.typing.handle_character(character)
        if correct:
            self.health = max(0, self.max_health - self.typing.index)
            if self.typing.completed:
                self.alive = False
                return "complete"
            return "correct"
        self.flash_timer = 0.18
        return "wrong"

    def undo_character(self) -> bool:
        if not self.alive:
            return False
        if self.typing.backspace():
            self.health = min(self.max_health, self.max_health - self.typing.index)
            return True
        return False

    def update(self, dt: float, danger_line: float) -> None:
        if not self.alive:
            return
        step = max(0.0, dt)
        self.age += step
        self.y += self.speed * step
        self.flash_timer = max(0.0, self.flash_timer - step)
        self._update_sway(step)
        if self.y > danger_line:
            self.escaped = True
            self.alive = False

    def _update_sway(self, dt: float) -> None:
        """Sideways drift per enemy type."""
        if self.enemy_type == ENEMY_SPECIAL:
            self.x = (
                self.column_x
                + math.sin(self.age * 3.1 + self._jitter_seed) * self.layout.enemy_sway_special
            )
        elif self.enemy_type == ENEMY_FAST:
            self.x = (
                self.column_x
                + math.sin(self.age * 21.0 + self._jitter_seed) * self.layout.enemy_sway_fast
            )
        elif self.enemy_type == ENEMY_TANK:
            self.pulse = (math.sin(self.age * 4.0) + 1.0) / 2.0
            self.x = self.column_x
        elif self.enemy_type == ENEMY_BOSS:
            self.x = (
                self.column_x
                + math.sin(self.age * 1.6 + self._jitter_seed) * self.layout.boss_sway
            )
        else:
            self.x = self.column_x

    def destroy(self) -> None:
        self.alive = False
