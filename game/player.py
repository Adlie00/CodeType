"""Player state for CODETYPE."""

from __future__ import annotations

from game.constants import MAX_LIVES, STARTING_LIVES


class Player:
    def __init__(self, lives: int = STARTING_LIVES) -> None:
        self._lives = max(0, min(MAX_LIVES, lives))

    @property
    def lives(self) -> int:
        return self._lives

    @property
    def alive(self) -> bool:
        return self._lives > 0

    def take_damage(self, amount: int = 1) -> bool:
        self._lives = max(0, self._lives - max(0, amount))
        return not self.alive

    def add_life(self) -> None:
        self._lives = min(MAX_LIVES, self._lives + 1)
