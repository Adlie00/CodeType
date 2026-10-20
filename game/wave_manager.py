"""Configuration-driven campaign, competition, and endless wave management."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from game.constants import (
    DIFFICULTY_BOSS,
    DIFFICULTY_ORDER,
    ENEMY_BOSS,
    ENEMY_COLUMNS,
    ENEMY_LENGTH_BIAS,
    ENEMY_NORMAL,
    ENDLESS_BOSS_EVERY,
    MIN_SPAWN_INTERVAL,
    MODE_ARCADE,
    MODE_CAMPAIGN,
    MODE_COMPETITION,
    MODE_WARMUP,
    SPAWN_PACING_CPS,
)
from game.boss import Boss
from game.content import Challenge, ContentError, ContentRepository, WaveConfig
from game.difficulty import (
    DifficultyProfile,
    difficulty_for_endless,
    difficulty_for_progress,
    get_profile,
    shift_progression,
)
from game.enemy import Enemy
from game.ui import DESIGN_LAYOUT, Layout

# Two stations within half a lane's pitch count as the same lane, so a card is
# never dropped on top of another even though a boss card is wider than a normal
# one and its band is therefore a little narrower.
_LANE_TOLERANCE = 0.5 / max(1, ENEMY_COLUMNS - 1)


@dataclass(frozen=True)
class SpawnOrder:
    challenge: Challenge
    difficulty: str
    enemy_type: str
    is_boss: bool = False


class WaveManager:
    def __init__(
        self,
        content: ContentRepository,
        mode: str = MODE_CAMPAIGN,
        layout: Layout | None = None,
        difficulty: str | None = None,
    ) -> None:
        self._content = content
        self._mode = mode
        # Everything the manager spawns is sized and positioned against this
        # layout, so the field keeps its proportions on any display.
        self._layout = layout
        # The tier picked in the menu: the floor for every wave spawned this run.
        self._start_difficulty: str | None = None
        if difficulty is not None:
            normalized = str(difficulty).upper()
            if normalized not in DIFFICULTY_ORDER:
                raise ValueError(f"Unknown difficulty: {difficulty}")
            self._start_difficulty = normalized
        # Competition plays the campaign; only endless is unbounded.
        self._is_campaign = mode in (MODE_CAMPAIGN, MODE_COMPETITION)
        self._campaign_waves = content.available_waves
        if not self._campaign_waves:
            raise ContentError("No complete campaign wave data is available")
        # Endless-family waves are generated, so they roll a fresh language every
        # wave instead of inheriting HTML from the campaign's opener. The ladder
        # covers every shipped language, so it doubles as both the pool and the
        # source of the display names.
        self._languages = tuple(dict.fromkeys(w.language for w in self._campaign_waves))
        self._language_names = {w.language: w.display_name for w in self._campaign_waves}
        self._endless_enemy_count = self._campaign_waves[0].enemy_count
        self._wave_index = 0
        self._endless_wave_number = 1
        self._endless_bosses = 0
        self._queue: list[SpawnOrder] = []
        self._spawn_index = 0
        self._spawn_timer = 0.0
        self._current_wave = self._initial_wave()
        self._prepare_wave()

    def rebind_layout(self, layout: Layout) -> None:
        """Adopt a new display layout, e.g. after the window was resized.

        Enemies already in the air are rebased by the caller; this keeps
        everything spawned from here on sized against the current layout.
        """
        self._layout = layout

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def start_difficulty(self) -> str:
        """The tier the run begins on, EASY when nothing was configured."""
        return self._start_difficulty or DIFFICULTY_ORDER[0]

    @property
    def is_campaign(self) -> bool:
        return self._is_campaign

    @property
    def _mode_suffix(self) -> str:
        """The label endless-family modes stamp on their generated wave names."""
        if self._mode == MODE_WARMUP:
            return "WARMUP"
        if self._mode == MODE_ARCADE:
            return "ARCADE"
        return "ENDLESS"

    @property
    def current_wave(self) -> WaveConfig:
        return self._current_wave

    @property
    def wave_number(self) -> int:
        if self._is_campaign:
            return self._current_wave.wave_number
        return self._endless_wave_number

    @property
    def total_waves(self) -> int:
        return len(self._campaign_waves)

    @property
    def language_name(self) -> str:
        return self._current_wave.display_name

    @property
    def current_difficulty(self) -> str:
        if self._queue:
            return self._queue[0].difficulty
        return self._current_wave.difficulty_progression[-1]

    @property
    def remaining_enemies(self) -> int:
        return len(self._queue)

    @property
    def boss_queued(self) -> bool:
        return any(order.is_boss for order in self._queue)

    def update(
        self,
        dt: float,
        active_enemies: int,
        blocked: bool = False,
        total_kills: int = 0,
        occupied: Sequence[float] = (),
    ) -> list[Enemy]:
        """Pop the next spawn order, or nothing while ``blocked``.

        ``occupied`` is the lane stations already taken on the field, so a new
        card is dropped in a lane nothing else is sitting in.
        """
        self._spawn_timer -= max(0.0, dt)
        if not self._is_campaign:
            self._queue_endless_boss(total_kills)
        profile = get_profile(self.current_difficulty)
        interval = self._spawn_interval(profile)
        spawned: list[Enemy] = []
        taken = list(occupied)

        while (
            not blocked
            and self._queue
            and self._spawn_timer <= 0
            and active_enemies + len(spawned) < profile.max_active
        ):
            order = self._queue.pop(0)
            enemy = self._build_enemy(order, taken)
            taken.append(enemy.station)
            spawned.append(enemy)
            self._spawn_index += 1
            self._spawn_timer += interval
        return spawned

    def is_wave_complete(self, active_enemies: list[Enemy]) -> bool:
        # A boss mid-intro is still part of this wave. Excluding it let the wave
        # advance during the 2.2s arrival, orphaning the boss into the next wave
        # and allowing a final-wave victory to be declared while it was still
        # on screen.
        if self._queue:
            return False
        return not any(enemy.alive for enemy in active_enemies)

    def advance(self, total_kills: int = 0) -> bool:
        if self._is_campaign:
            if self._wave_index + 1 >= len(self._campaign_waves):
                return False
            self._wave_index += 1
            self._current_wave = self._campaign_waves[self._wave_index]
            self._prepare_wave()
            return True

        self._endless_wave_number += 1
        self._current_wave = self._endless_wave(
            self._endless_wave_number, self._random_language()
        )
        self._prepare_wave()
        return True

    def _queue_endless_boss(self, total_kills: int) -> None:
        """Insert a boss the moment the 20-kill threshold is crossed.

        Deciding this at wave boundaries would drift: endless waves hold 12
        enemies, so a boss every 20 kills actually landed on 24, 48 and so on.
        """
        if any(order.is_boss for order in self._queue):
            return
        if (max(0, total_kills) // ENDLESS_BOSS_EVERY) <= self._endless_bosses:
            return
        self._endless_bosses += 1
        self._queue.insert(0, self._boss_order())

    def _build_enemy(
        self, order: SpawnOrder, occupied: Sequence[float] = ()
    ) -> Enemy:
        station = self._free_station(occupied)
        if order.is_boss:
            return Boss(
                challenge=order.challenge,
                difficulty=order.difficulty,
                station=station,
                layout=self._layout,
            )
        return Enemy(
            challenge=order.challenge,
            difficulty=order.difficulty,
            enemy_type=order.enemy_type,
            station=station,
            layout=self._layout,
        )

    def _free_station(self, occupied: Sequence[float]) -> float:
        """Pick a random lane that nothing on the field already holds.

        Every lane filled only happens when the field is at its concurrency
        limit, in which case the next spawn waits; falling back to any lane keeps
        the call total rather than raising on a crowded field.
        """
        layout = self._layout if self._layout is not None else DESIGN_LAYOUT
        lanes = layout.lane_stations()
        free = [
            lane
            for lane in lanes
            if not any(abs(lane - taken) <= _LANE_TOLERANCE for taken in occupied)
        ]
        return random.choice(free if free else list(lanes))

    def _initial_wave(self) -> WaveConfig:
        if self._is_campaign:
            return self._campaign_waves[0]
        return self._endless_wave(1, self._random_language())

    def _random_language(self) -> str:
        """Pick the language for a generated endless-family wave."""
        return random.choice(self._languages)

    def _endless_wave(self, wave_number: int, language: str) -> WaveConfig:
        """Build one generated wave for the chosen language.

        Only the language is rolled per wave; difficulty, enemy count and pace
        follow the endless schedule exactly as before.
        """
        name = self._language_names.get(language, language.upper())
        return WaveConfig(
            wave_number=wave_number,
            language=language,
            display_name=f"{name} {self._mode_suffix}",
            difficulty_progression=(
                difficulty_for_endless(wave_number, self._start_difficulty),
            ),
            enemy_count=self._endless_enemy_count,
            boss_wave=False,
            boss_language=None,
            spawn_interval=self._content.endless_base_interval,
            description=f"{self._mode_suffix.title()} challenge",
        )

    def _prepare_wave(self) -> None:
        progression = self._current_wave.difficulty_progression
        if self._is_campaign:
            difficulties = shift_progression(progression, self._start_difficulty)
        else:
            difficulties = (
                difficulty_for_endless(self._endless_wave_number, self._start_difficulty),
            )

        self._queue = []
        for index in range(self._current_wave.enemy_count):
            difficulty = (
                difficulty_for_progress(difficulties, index, self._current_wave.enemy_count)
                if len(difficulties) > 1
                else difficulties[0]
            )
            enemy_type = self._enemy_type(difficulty, index)
            challenge = self._challenge_for(difficulty, enemy_type, index)
            self._queue.append(SpawnOrder(challenge, difficulty, enemy_type))

        if self._current_wave.boss_wave:
            self._queue.append(self._boss_order())

        self._spawn_index = 0
        self._spawn_timer = 0.0

    def _boss_order(self) -> SpawnOrder:
        language = self._current_wave.boss_language or self._current_wave.language
        try:
            challenge = self._content.get_challenges(language, DIFFICULTY_BOSS)[0]
        except ContentError:
            # No dedicated BOSS content: reuse the longest available snippet so
            # a configured boss wave still spawns a boss instead of crashing.
            challenge = self._fallback_pool(DIFFICULTY_ORDER[-1])[0]
        return SpawnOrder(challenge, DIFFICULTY_BOSS, ENEMY_BOSS, is_boss=True)

    def _challenge_for(
        self,
        difficulty: str,
        enemy_type: str,
        index: int,
    ) -> Challenge:
        bias = ENEMY_LENGTH_BIAS.get(enemy_type, 0.5)
        try:
            pool = self._content.get_challenges_by_length(
                self._current_wave.language, difficulty, bias
            )
        except ContentError:
            pool = self._fallback_pool(difficulty)
        return pool[index % len(pool)]

    def _fallback_pool(self, difficulty: str) -> tuple[Challenge, ...]:
        for fallback in reversed(DIFFICULTY_ORDER):
            try:
                return self._content.get_challenges(
                    self._current_wave.language, fallback
                )
            except ContentError:
                continue
        raise ContentError(
            f"No challenges available for language {self._current_wave.language}"
        )

    @staticmethod
    def _enemy_type(difficulty: str, index: int) -> str:
        """Pick an enemy type from the difficulty's declared roster."""
        roster = get_profile(difficulty).enemy_types
        if not roster:
            return ENEMY_NORMAL
        if index == 0:
            return ENEMY_NORMAL
        return roster[index % len(roster)]

    def _spawn_interval(self, profile: DifficultyProfile) -> float:
        """Seconds before the next enemy, floored by the time it takes to type it.

        The wave config sets the *minimum* pace. A snippet needs at least its own
        typing time, otherwise the queue outruns the player and enemies are
        guaranteed to reach the danger line.
        """
        if self._is_campaign:
            base = self._current_wave.spawn_interval * profile.spawn_multiplier
        else:
            decay = self._content.endless_interval_decay
            interval = self._content.endless_base_interval * (
                decay ** max(0, self._endless_wave_number - 1)
            )
            base = max(self._content.endless_min_interval, interval) * profile.spawn_multiplier
        return max(MIN_SPAWN_INTERVAL, base, self._typing_floor())

    def _typing_floor(self) -> float:
        """Reference time to type the next queued snippet.

        Bosses are exempt: a boss gets its own generous fall time from the speed
        cap, and it halts new spawns anyway, so delaying its arrival would just
        stall the wave.
        """
        if not self._queue or self._queue[0].is_boss:
            return 0.0
        return self._queue[0].challenge.length / SPAWN_PACING_CPS
