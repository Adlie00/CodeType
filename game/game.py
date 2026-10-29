"""Gameplay orchestration and rendering for CODETYPE.

Nothing in this module multiplies a literal by the resolution. Every distance
comes from ``Layout`` and every glyph from ``UI``, both of which are derived
from the surface size, so the field is laid out identically — proportionally —
on a 720p laptop and a 4K monitor.
"""

from __future__ import annotations

import math
import random
import sqlite3

import pygame

from game.audio_manager import (
    SFX_BOSS,
    SFX_COMBO,
    SFX_DESTROY,
    SFX_GAME_OVER,
    SFX_TYPE_CORRECT,
    SFX_TYPE_WRONG,
    SFX_WAVE_CLEAR,
)
from game.constants import (
    ARCADE_BOSS_SECONDS,
    ARCADE_KILL_SECONDS,
    ARCADE_SECONDS,
    CURSOR_COLOUR,
    DARK_BG,
    DESCENT_REFERENCE_CPS,
    ENEMY_COLOURS,
    ENEMY_SPECIAL,
    ENEMY_TANK,
    ERROR_COLOUR,
    GREY,
    HAIRLINE_DIM,
    MODE_ARCADE,
    MODE_COMPETITION,
    MODE_ENDLESS,
    MODE_WARMUP,
    NEON_CYAN,
    NEON_GREEN,
    NEON_ORANGE,
    NEON_PINK,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    REMAINING_COLOUR,
    SURFACE,
    SYNTAX_COLOURS,
    TEXT_BRIGHT,
    TEXT_DIM,
    TYPED_COLOUR,
    WARMUP_SECONDS,
)
from game.content import ContentRepository
from game.effects import EffectsManager
from game.game_state import GameState
from game.input_map import printable_character
from game.ui import UI, Layout, Stage, mix, pulse
from game.wave_manager import WaveManager


# Amplitudes, in design space, so the shake reads the same on every display.
_SHAKE_WRONG = 3.0
_SHAKE_MISS = 4.0
_SHAKE_KILL = 5.0
_SHAKE_BOSS = 9.0
_SHAKE_COMBO = 6.0
_SHAKE_LIFE_LOST = 11.0

# Code-card font bounds, in points. A card shows one line but is sized for up to
# ENEMY_MAX_LINES of them, so a short line gets to be much larger than a long
# one. The floor keeps a cramped card legible; the ceiling stops a one-line
# snippet on a tall card from looking like a headline.
_CODE_SIZE_MIN = 13
_CODE_SIZE_MAX = 34


class Game:
    def __init__(
        self,
        screen: pygame.Surface,
        settings,
        assets,
        audio,
        mode: str,
        player_name: str = "PLAYER",
        content: ContentRepository | None = None,
        difficulty: str | None = None,
        leaderboard=None,
        competition=None,
    ) -> None:
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        # Tournament runs carry the slot they belong to; non-tournament
        # competition runs (and every other mode) leave this as None.
        self._competition = competition
        self._content = content or ContentRepository()
        self._state = GameState(mode=mode, player_name=player_name)
        # Competition plays against a fixed target: the best score already on
        # that mode's board, by someone other than this player. Read once at run
        # start so it never shifts mid-run, and never for the other modes.
        self._rival_name: str | None = None
        self._rival_score: int | None = None
        if mode == MODE_COMPETITION:
            rival = self._competition_rival()
            if rival is not None:
                self._rival_name, self._rival_score = rival
            # A tournament run knows the exact Team to Beat it is chasing, so
            # the bar shows that instead of querying the generic board.
            if competition is not None:
                self._rival_name = getattr(competition, "target_name", "") or None
                self._rival_score = getattr(competition, "target_score", None)

        # Warmup is a timed practice session: no lives, and the clock is the
        # only thing that can end it. At zero the screen drops into competition.
        self._warmup_remaining = WARMUP_SECONDS if mode == MODE_WARMUP else 0.0
        # Arcade is the timed score attack: the clock is again the only thing
        # that can end the run, but this one is recorded, and every kill buys
        # seconds back onto the same clock.
        self._arcade_remaining = ARCADE_SECONDS if mode == MODE_ARCADE else 0.0

        width, height = screen.get_size()
        self._ui = UI(assets, width, height)
        self._layout = Layout(width, height)
        self._stage = Stage(self._ui, star_count=170, horizon_fraction=0.46, scroll=34.0)

        self._wave_manager = WaveManager(
            self._content, mode, layout=self._layout, difficulty=difficulty
        )
        self._state.set_wave(
            self._wave_manager.wave_number, self._wave_manager.current_difficulty
        )
        self._enemies: list = []
        self._effects = EffectsManager(
            typing_effects=bool(getattr(settings, "typing_effects", True)),
            screen_shake=bool(getattr(settings, "screen_shake", True)),
            scale=self._layout.scale,
        )
        self._message = (
            f"WARM UP  //  {int(WARMUP_SECONDS)}s"
            if mode == MODE_WARMUP
            else f"ARCADE  //  {int(ARCADE_SECONDS)}s  //  KILLS ADD TIME"
            if mode == MODE_ARCADE
            else f"WAVE {self._wave_manager.wave_number}  //  {self._wave_manager.language_name}"
        )
        self._message_timer = 2.5
        self._banner: str | None = None
        self._banner_timer = 0.0
        self._finished = False
        self._victory = False
        self._return_to_menu = False
        self._paused = False
        self._pause_blink = 0.0

    # ── Public state ──────────────────────────────────────────────────────────

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def enemies(self) -> list:
        return self._enemies

    @property
    def ui(self) -> UI:
        return self._ui

    @property
    def layout(self) -> Layout:
        return self._layout

    @property
    def active_enemy(self):
        """The lowest *arrived* living enemy, per the targeting rules.

        A boss running its arrival intro is skipped: it still sits above the
        viewport, so it must not become the target while off-screen.
        """
        alive = [
            enemy
            for enemy in self._enemies
            if enemy.alive and not getattr(enemy, "intro_active", False)
        ]
        return max(alive, key=lambda enemy: enemy.y) if alive else None

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def victory(self) -> bool:
        return self._victory

    @property
    def return_to_menu(self) -> bool:
        return self._return_to_menu

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def message(self) -> str:
        return self._message

    @property
    def wave_manager(self) -> WaveManager:
        return self._wave_manager

    def stats(self) -> dict[str, object]:
        payload = self._state.stats()
        payload["victory"] = self._victory
        payload["start_difficulty"] = self._wave_manager.start_difficulty
        return payload

    @property
    def _danger_line(self) -> float:
        return self._layout.danger_line

    def _competition_rival(self) -> tuple[str, int] | None:
        """Name and score of the top competition player who is not this one.

        The target is the best competition run held by *someone else*, so a
        player replaying never ends up chasing their own name. Every access is
        defensive: the board may be absent (headless tests), a stub may predate
        the ``mode`` argument, or the database may be locked. No qualifying row
        is not an error — it just means the bar shows a dash.
        """
        board = self._leaderboard
        if board is None or not hasattr(board, "get_top"):
            return None
        me = str(self._state.player_name).strip().upper()
        try:
            try:
                # A batch, not a single row: the #1 may be this very player, so
                # the first *other* name is what matters.
                rows = board.get_top(10, "score", mode=MODE_COMPETITION)
            except TypeError:
                # Older / stub leaderboards only know the two-argument form;
                # filter their board-wide result down to competition here.
                rows = [
                    row
                    for row in board.get_top(10, "score")
                    if str(row.get("mode", "")).lower() == MODE_COMPETITION
                ]
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return None
        for row in rows:
            name = str(row.get("player_name", "")).strip()
            if name and name.upper() == me:
                continue
            try:
                score = int(row.get("score", 0))
            except (TypeError, ValueError, AttributeError):
                continue
            return (name, score)
        return None

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        if self._finished or self._paused:
            self._pause_blink = (self._pause_blink + dt) % 1.0
            return
        step = max(0.0, dt)
        if self._state.mode == MODE_WARMUP:
            self._warmup_remaining = max(0.0, self._warmup_remaining - step)
            if self._warmup_remaining <= 0.0:
                self._finish_warmup()
                return
        elif self._state.mode == MODE_ARCADE:
            self._arcade_remaining = max(0.0, self._arcade_remaining - step)
            if self._arcade_remaining <= 0.0:
                self._finish_arcade()
                return
        self._message_timer = max(0.0, self._message_timer - step)
        self._banner_timer = max(0.0, self._banner_timer - step)
        if self._banner_timer <= 0.0:
            self._banner = None
        self._effects.update(step)
        self._stage.update(step)
        self._state.tick_wpm()

        danger_line = self._danger_line
        for enemy in list(self._enemies):
            enemy.update(step, danger_line)
            self._emit_trail(enemy, step)
            if enemy.escaped:
                self._enemies.remove(enemy)
                self._on_enemy_escaped(enemy)
                if self._finished:
                    return

        if not self._boss_on_field():
            self._spawn_enemies(step)

        self._state.set_wave(
            self._wave_manager.wave_number,
            self._wave_manager.current_difficulty,
        )

        if self._wave_manager.is_wave_complete(self._enemies):
            self._complete_wave()

    def _boss_on_field(self) -> bool:
        return any(
            enemy.alive and getattr(enemy, "is_boss", False) for enemy in self._enemies
        )

    def _field_crowded(self) -> bool:
        alive = [enemy for enemy in self._enemies if enemy.alive]
        return bool(alive) and min(enemy.y for enemy in alive) < self._layout.spawn_clearance_y

    def _spawn_enemies(self, dt: float) -> None:
        spawned = self._wave_manager.update(
            dt, len(self._enemies), blocked=self._field_crowded(),
            total_kills=self._state.enemies_destroyed,
            occupied=[
                getattr(enemy, "station", 0.0)
                for enemy in self._enemies
                if enemy.alive
            ],
        )
        for enemy in spawned:
            enemy.limit_speed_for(
                self._danger_line, queue_seconds=self._queue_typing_seconds(enemy)
            )
            if getattr(enemy, "is_boss", False):
                enemy.begin_intro()
                self._banner = "WARNING  //  BOSS INBOUND"
                self._banner_timer = 2.4
                self._message = f"BOSS  //  {self._wave_manager.language_name}"
                self._message_timer = 2.4
                self._audio.play(SFX_BOSS)
                self._effects.add_shake(_SHAKE_BOSS, 0.35)
            self._enemies.append(enemy)

    def _queue_typing_seconds(self, incoming) -> float:
        """Typing time for ``incoming`` plus everything already on the field.

        The player clears one enemy at a time, oldest first, so a newly spawned
        enemy only arrives in time if the whole queue ahead of it can be typed
        first. Summing the real snippet lengths is what makes that guarantee
        hold when the queue mixes short and long code. ``incoming`` is excluded
        from the on-field sum because the caller may be re-checking an enemy that
        is already there (after a resize), and counting it twice would only
        ever make the cap needlessly slow.
        """
        queued = sum(
            len(enemy.text)
            for enemy in self._enemies
            if enemy is not incoming and enemy.alive
            and not getattr(enemy, "intro_active", False)
        )
        return (queued + len(incoming.text)) / max(0.1, DESCENT_REFERENCE_CPS)

    def _on_enemy_escaped(self, enemy) -> None:
        centre_x, centre_y = enemy.x + enemy.width / 2, enemy.y
        # Neither endless, warmup nor arcade has lives: an escape breaks the
        # combo and pings the field, but it can never end the run.
        ended = self._state.record_missed_enemy(
            costs_life=self._state.mode
            not in (MODE_ENDLESS, MODE_WARMUP, MODE_ARCADE)
        )
        if ended:
            self._effects.particles.explosion(centre_x, centre_y, (NEON_RED,), 26, (50.0, 160.0))
            self._effects.add_shake(_SHAKE_LIFE_LOST, 0.4)
            self._audio.play(SFX_TYPE_WRONG)
            self._banner = "LIFE LOST"
            self._banner_timer = 1.6
            self._finish(False)
            return
        self._effects.particles.explosion(centre_x, centre_y, (NEON_RED,), 12, (30.0, 90.0))
        self._effects.add_shake(_SHAKE_MISS, 0.14)
        self._effects.popups.add("MISSED", centre_x, centre_y, NEON_RED)

    def _complete_wave(self) -> None:
        self._state.record_wave_completed()
        self._audio.play(SFX_WAVE_CLEAR)
        manager = self._wave_manager
        if not manager.advance(self._state.enemies_destroyed):
            self._finish(True)
            return
        self._state.set_wave(manager.wave_number, manager.current_difficulty)
        self._message = f"WAVE {manager.wave_number}  //  {manager.language_name}"
        self._message_timer = 2.5

    def _emit_trail(self, enemy, dt: float) -> None:
        if enemy.enemy_type != ENEMY_SPECIAL or not enemy.alive:
            return
        if random.random() < dt * 26.0:
            self._effects.particles.trail(
                enemy.x + enemy.width / 2, enemy.bottom, ENEMY_COLOURS[ENEMY_SPECIAL]
            )

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._finished or event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_ESCAPE:
            self._paused = not self._paused
            return
        if self._paused:
            if event.key == pygame.K_m:
                self._paused = False
                self._return_to_menu = True
            return

        active = self.active_enemy
        if active is None:
            return

        if event.key == pygame.K_BACKSPACE:
            self._handle_backspace(active)
            return

        character = self._character_from_event(event)
        if character is None:
            return
        self._handle_character(active, character)

    def _character_from_event(self, event: pygame.event.Event) -> str | None:
        if event.key in (pygame.K_RETURN, getattr(pygame, "K_KP_ENTER", -1)):
            return "\n"
        if event.key == pygame.K_TAB:
            return "\t"
        if event.key == pygame.K_SPACE:
            return " "
        # Physical-key mapping, so dead-key layouts (e.g. United States-
        # International, where '"' needs two presses) behave like plain US.
        return printable_character(event)

    def _handle_character(self, active, character: str) -> None:
        before = self._typing_totals(active)
        outcome = active.type_character(character)
        self._record_typing(active, before)
        if outcome == "correct":
            self._audio.play(SFX_TYPE_CORRECT)
        elif outcome == "wrong":
            self._state.record_mistake()
            self._audio.play(SFX_TYPE_WRONG)
            self._effects.add_shake(_SHAKE_WRONG, 0.12)
        elif outcome == "complete":
            self._on_enemy_destroyed(active)

    def _on_enemy_destroyed(self, enemy) -> None:
        is_boss = bool(getattr(enemy, "is_boss", False))
        breakdown = self._state.record_destroy(
            enemy.text, enemy.difficulty, self._state.wave_number,
            enemy.typing.wpm, enemy.typing.accuracy, is_boss,
        )
        if enemy in self._enemies:
            self._enemies.remove(enemy)

        centre_x, centre_y = enemy.x + enemy.width / 2, enemy.y + enemy.height / 2
        colour = ENEMY_COLOURS.get(enemy.enemy_type, NEON_CYAN)
        count = 46 if is_boss else 18
        self._effects.particles.explosion(
            centre_x, centre_y, (colour, NEON_CYAN, NEON_YELLOW), count
        )
        if is_boss:
            self._effects.particles.shockwave(centre_x, centre_y, NEON_RED, 44)
        self._effects.add_shake(_SHAKE_BOSS if is_boss else _SHAKE_KILL, 0.3 if is_boss else 0.16)

        label = f"BOSS DOWN  +{breakdown.total:,}" if is_boss else f"+{breakdown.total:,}"
        self._effects.popups.add(
            label, centre_x, centre_y, NEON_RED if is_boss else NEON_GREEN,
            1.3 if is_boss else 1.0,
        )
        self._audio.play(SFX_DESTROY)
        if is_boss:
            self._audio.play(SFX_BOSS)

        self._grant_arcade_time(centre_x, centre_y, is_boss)

        milestone = self._state.take_combo_milestone()
        if milestone:
            self._celebrate_combo(milestone)

    def _grant_arcade_time(self, centre_x: float, centre_y: float, is_boss: bool) -> None:
        """Arcade's whole economy: every kill buys seconds back on the clock.

        Shown as its own popup under the score label so the reward reads as
        time, not points. The clock itself is capped so a long chain can't
        run the display out of range; the *score* has no such ceiling.
        """
        if self._state.mode != MODE_ARCADE:
            return
        bonus = ARCADE_BOSS_SECONDS if is_boss else ARCADE_KILL_SECONDS
        self._arcade_remaining = min(
            ARCADE_SECONDS * 4.0, self._arcade_remaining + bonus
        )
        self._effects.popups.add(
            f"+{bonus:g}s", centre_x, centre_y + self._ui.px(20),
            NEON_YELLOW, 1.2,
        )

    def _celebrate_combo(self, milestone: int) -> None:
        x, y = self._ui.width / 2, self._danger_line * 0.42
        self._effects.particles.shockwave(x, y, NEON_YELLOW, 36)
        self._effects.popups.add(f"COMBO x{milestone}", x, y, NEON_YELLOW, 1.4, 32.0)
        self._effects.add_shake(_SHAKE_COMBO, 0.25)
        self._audio.play(SFX_COMBO)

    def _handle_backspace(self, active) -> None:
        before = self._typing_totals(active)
        if active.undo_character():
            self._record_typing(active, before)

    @staticmethod
    def _typing_totals(active) -> tuple[int, int]:
        return active.typing.correct_characters, active.typing.total_characters

    def _record_typing(self, active, before: tuple[int, int]) -> None:
        """Book the delta since ``before``, so one keystroke counts once."""
        correct, total = self._typing_totals(active)
        self._state.record_attempt(correct - before[0], total - before[1])

    def _finish(self, victory: bool) -> None:
        self._finished = True
        self._victory = victory
        self._message = "ALL WAVES CLEARED" if victory else "GAME OVER"
        self._message_timer = 999.0
        self._audio.play(SFX_WAVE_CLEAR if victory else SFX_GAME_OVER)

    def _finish_warmup(self) -> None:
        """The 30s clock ran out: the practice run is over.

        Flagged as a victory so the summary reads as a clean completion, but
        warmup is never recorded on the leaderboard.
        """
        self._finished = True
        self._victory = True
        self._message = "TIME UP"
        self._message_timer = 999.0
        self._audio.play(SFX_WAVE_CLEAR)

    def _finish_arcade(self) -> None:
        """The arcade clock ran out: the score attack is over.

        Also flagged as a victory — running out of clock is how a *good*
        arcade run ends, not a failure — but unlike warmup this run is
        recorded on the arcade board by the game-over screen.
        """
        self._finished = True
        self._victory = True
        self._message = "TIME UP"
        self._message_timer = 999.0
        self._audio.play(SFX_WAVE_CLEAR)

    # ── Rendering ────────────────────────────────────────────────────────────

    def set_surface(self, screen: pygame.Surface) -> None:
        """Adopt a new surface: the old one is dead once the display mode changes."""
        self._screen = screen

    def _resize(self, width: int, height: int) -> None:
        """Re-derive everything display-dependent after a resize.

        The window can be dragged or the resolution changed under a run in
        progress, so the UI, layout, effects, stage and every enemy in the air
        all have to be told.
        """
        self._ui = UI(self._assets, width, height)
        # A *new* Layout, never a resize of the old one: every enemy holds a
        # reference to the layout it spawned against, and rebase() reads that
        # reference to work out the scale ratio. Mutating in place would leave
        # it reading the new scale and computing a ratio of 1.0, so nothing in
        # the field would move.
        self._layout = Layout(width, height)
        self._wave_manager.rebind_layout(self._layout)
        self._effects.rescale(self._layout.scale)
        self._stage.rebind(self._ui)
        # Positions just moved, so the speed cap has to be re-derived against
        # the new travel and the same real queue total the spawn path uses.
        for enemy in self._enemies:
            enemy.rebase(self._layout)
            enemy.limit_speed_for(
                self._danger_line, queue_seconds=self._queue_typing_seconds(enemy)
            )

    def draw(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        if (width, height) != (self._ui.width, self._ui.height):
            self._resize(width, height)

        margin = self._effects.shake.margin
        offset_x, offset_y = self._effects.shake.offset
        shaking = offset_x != 0 or offset_y != 0

        if shaking:
            canvas = pygame.Surface((width + margin * 2, height + margin * 2))
            self._paint(canvas, width, height)
            screen.fill(DARK_BG)
            screen.blit(canvas, (offset_x - margin, offset_y - margin))
        else:
            self._paint(screen, width, height)

        if self._paused:
            self._draw_pause(screen)

    def _paint(self, surface: pygame.Surface, width: int, height: int) -> None:
        surface.fill(DARK_BG)
        self._stage.draw(surface, pygame.time.get_ticks() / 1000.0)
        self._draw_danger_line(surface, width)
        for enemy in self._enemies:
            self._draw_enemy(surface, enemy)
        self._effects.draw_world(surface, self._ui.font(18, True))
        self._draw_hud(surface, width)
        self._draw_competition_bar(surface, width)
        self._draw_message(surface, width, height)
        self._draw_banner(surface, width, height)

    # ── Field chrome ─────────────────────────────────────────────────────────

    def _draw_danger_line(self, surface: pygame.Surface, width: int) -> None:
        """The warning line: a hazard band the whole field falls toward."""
        ui = self._ui
        band_height = max(6, self._layout.warning_band_height)
        y = int(self._danger_line)
        beat = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 260.0)
        colour = tuple(
            int(NEON_RED[channel] * (0.5 + 0.4 * beat)) for channel in range(3)
        )

        band = pygame.Rect(0, y - band_height // 2, width, band_height)
        wash = pygame.Surface(band.size, pygame.SRCALPHA)
        wash.fill((*colour, 30))
        surface.blit(wash, band.topleft)

        # Diagonal hatching, offset by time so the band appears to travel.
        dash = max(6, ui.px(14))
        gap = max(8, ui.px(22))
        step = dash + gap
        offset = int((pygame.time.get_ticks() / 40.0) % step)
        stripe = pygame.Surface((width, band_height), pygame.SRCALPHA)
        for x in range(-step + offset, width + step, step):
            points = [
                (x, band_height),
                (x + dash, 0),
                (x + dash + band_height, 0),
                (x + band_height, band_height),
            ]
            pygame.draw.polygon(stripe, (*colour, 46), points)
        surface.blit(stripe, band.topleft)

        pygame.draw.line(surface, colour, (0, y), (width, y), max(1, ui.px(2)))
        ui.text(
            surface, "WARNING LINE", 11, colour, width - ui.px(10),
            y - band_height // 2 - ui.px(2), bold=True, anchor="topright",
        )

    def _draw_hud(self, surface: pygame.Surface, width: int) -> None:
        """The top bar: run stats left, wave identity centre, vitals right."""
        ui = self._ui
        height = self._layout.hud_height
        pad = ui.px(22)

        body = pygame.Surface((width, height), pygame.SRCALPHA)
        body.fill((*PANEL_BG, 246))
        surface.blit(body, (0, 0))
        pygame.draw.line(surface, HAIRLINE_DIM, (0, height - 1), (width, height - 1), 1)
        pygame.draw.line(surface, NEON_CYAN, (0, height - 1), (width, height - 1), 1)

        tile_height = height - ui.px(30)
        top = ui.px(13)
        manager = self._wave_manager
        wave_text = (
            f"{manager.wave_number}/{manager.total_waves}"
            if manager.is_campaign else f"{manager.wave_number}"
        )

        # Left: the two numbers that decide how the run feels.
        left = pygame.Rect(pad, top, int(width * 0.30), tile_height)
        ui.tile(
            surface, left, "SCORE", f"{self._state.score:,}",
            value_colour=TEXT_BRIGHT, value_size=26,
        )
        combo_rect = pygame.Rect(left.right + ui.px(26), top, ui.px(96), tile_height)
        ui.tile(
            surface, combo_rect, "COMBO", f"x{self._state.combo}",
            value_colour=self._combo_colour(), value_size=26,
        )

        # Centre: which wave this is and how far through it the player is.
        centre = pygame.Rect(int(width * 0.36), top, int(width * 0.28), tile_height)
        centre_wave = ui.font(22, True).render(f"WAVE {wave_text}", True, TEXT_BRIGHT)
        surface.blit(centre_wave, centre_wave.get_rect(midtop=(centre.centerx, centre.y)))
        caption = ui.text(
            surface, f"{manager.language_name}  //  {manager.current_difficulty}",
            12, TEXT_DIM, centre.centerx,
            centre_wave.get_height() + centre.y, anchor="midtop",
        )
        meter = pygame.Rect(
            centre.x, caption.bottom + ui.px(9), centre.width, max(3, ui.px(5))
        )
        ui.meter(surface, meter, self._wave_progress(), NEON_CYAN, track=HAIRLINE_DIM)

        # Right: the numbers that tell you how well you are doing it.
        right_edge = width - pad
        right = pygame.Rect(int(width * 0.68), top, right_edge - int(width * 0.68), tile_height)
        vitals = self._hud_vitals()
        third = right.width // len(vitals)
        last = len(vitals) - 1
        for index, (label, value, colour) in enumerate(vitals):
            block = pygame.Rect(right.x + index * third, right.y, third, tile_height)
            ui.tile(
                surface, block, label, value, value_colour=colour, value_size=22,
                align="right" if index == last else "left",
            )

    def _hud_vitals(self) -> list[tuple[str, str, tuple[int, int, int]]]:
        """The right-hand HUD tiles. Endless and warmup have no lives; arcade
        trades the lives tile for the countdown clock that ends its runs."""
        vitals = [
            ("WPM", f"{self._state.current_wpm:.0f}", TEXT_BRIGHT),
            ("ACCURACY", f"{self._state.accuracy:.1f}%", TEXT_BRIGHT),
        ]
        if self._state.mode == MODE_WARMUP:
            vitals.append(
                ("TIME", f"{math.ceil(self._warmup_remaining)}s", NEON_YELLOW)
            )
        elif self._state.mode == MODE_ARCADE:
            vitals.append(
                ("TIME", f"{math.ceil(self._arcade_remaining)}s", NEON_YELLOW)
            )
        elif self._state.mode != MODE_ENDLESS:
            vitals.append(("LIVES", "♥" * self._state.player.lives, NEON_PINK))
        return vitals

    def _competition_bar_rect(self, width: int) -> pygame.Rect | None:
        """The strip under the HUD, or None outside competition mode."""
        if self._state.mode != MODE_COMPETITION:
            return None
        return pygame.Rect(
            0, self._layout.hud_height, width, self._ui.px(28)
        )

    def _draw_competition_bar(self, surface: pygame.Surface, width: int) -> None:
        """Competition mode's scoreboard: who you are, and what to beat."""
        bar = self._competition_bar_rect(width)
        if bar is None:
            return
        ui = self._ui

        body = pygame.Surface(bar.size, pygame.SRCALPHA)
        body.fill((*PANEL_BG, 246))
        surface.blit(body, bar.topleft)
        # Yellow is competition's accent everywhere else, so it marks the bar.
        pygame.draw.line(
            surface, NEON_YELLOW, (0, bar.bottom - 1), (width, bar.bottom - 1), 1
        )

        pad = ui.px(22)
        if self._competition is not None:
            name = str(getattr(self._competition, "team_name", ""))[:18] or "TEAM"
            slot = getattr(self._competition, "slot", "?")
            left_label = f"TEAM   {name}   //   REP {slot}"
            right_label = f"{str(self._state.player_name)[:16]}"
            ui.text(
                surface, left_label, 13, NEON_YELLOW,
                pad, bar.centery, bold=True, anchor="midleft",
            )
            ui.text(
                surface, right_label, 12, TEXT_DIM,
                pad + ui.px(300), bar.centery, anchor="midleft",
            )
        else:
            name = str(self._state.player_name)[:18] or "PLAYER"
            ui.text(
                surface, f"PLAYER   {name}", 13, NEON_YELLOW,
                pad, bar.centery, bold=True, anchor="midleft",
            )
        if self._rival_score is not None and self._rival_name:
            # "ALICE TO BEAT   98,450" — the name carries the challenge, the
            # number is what is measured against.
            score_rect = ui.text(
                surface, f"{self._rival_score:,}", 13, TEXT_BRIGHT,
                width - pad, bar.centery, bold=True, anchor="midright",
            )
            ui.text(
                surface, f"{str(self._rival_name)[:16]} TO BEAT", 13, NEON_YELLOW,
                score_rect.left - ui.px(10), bar.centery, bold=True,
                anchor="midright",
            )
        else:
            ui.text(
                surface, "NO ONE TO BEAT", 13, TEXT_DIM,
                width - pad, bar.centery, bold=True, anchor="midright",
            )

    def _wave_progress(self) -> float:
        wave = self._wave_manager.current_wave
        total = max(1, int(getattr(wave, "enemy_count", 1)))
        return max(0.0, min(1.0, min(total, self._state.enemies_destroyed) / total))

    def _combo_colour(self) -> tuple[int, int, int]:
        combo = self._state.combo
        if combo >= 20:
            return NEON_RED
        if combo >= 10:
            return NEON_YELLOW
        if combo >= 5:
            return NEON_ORANGE
        return NEON_GREEN

    # ── Enemies ──────────────────────────────────────────────────────────────

    def _draw_enemy(self, surface: pygame.Surface, enemy) -> None:
        ui = self._ui
        rect = pygame.Rect(int(enemy.x), int(enemy.y), enemy.width, enemy.height)
        if rect.bottom < self._layout.hud_height or rect.top > ui.height:
            return

        is_boss = bool(getattr(enemy, "is_boss", False))
        active = enemy is self.active_enemy
        border = self._enemy_colour(enemy)
        if is_boss and getattr(enemy, "intro_active", False):
            border = NEON_RED
        if enemy.flash_timer > 0:
            border = ERROR_COLOUR

        if enemy.enemy_type == ENEMY_TANK:
            self._draw_tank_shield(surface, rect, border, enemy)
        if is_boss:
            self._draw_boss_aura(surface, rect, border)

        fill = (8, 10, 32, 240) if active else (*SURFACE, 226)
        card = pygame.Surface(rect.size, pygame.SRCALPHA)
        card.fill(fill)
        radius = max(4, ui.px(8))
        surface.blit(card, rect.topleft)
        pygame.draw.rect(
            surface, border, rect,
            max(1, ui.px(3)) if active else (max(1, ui.px(2)) if is_boss else 1),
            border_radius=radius,
        )
        if active:
            self._draw_targeting_brackets(surface, rect, border, radius)

        header = pygame.Rect(
            rect.x, rect.y, rect.width, self._layout.enemy_header_height
        )
        pygame.draw.line(
            surface, HAIRLINE_DIM, (header.x, header.bottom), (header.right, header.bottom), 1
        )
        if is_boss:
            self._draw_boss_header(surface, enemy, header, border)
        else:
            self._draw_enemy_header(surface, enemy, header, border, active)

        self._draw_code(surface, enemy, rect, active, border)
        self._draw_health_bar(surface, rect, border, enemy)

    def _draw_targeting_brackets(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        border: tuple[int, int, int],
        radius: int,
    ) -> None:
        """Corner ticks that mark the card the player is actually typing."""
        ui = self._ui
        arm = max(4, ui.px(9))
        thickness = max(1, ui.px(2))
        inset = -thickness
        for x, y, dx, dy in (
            (rect.left + radius, rect.top, 1, 1),
            (rect.right - radius, rect.top, -1, 1),
            (rect.left + radius, rect.bottom, 1, -1),
            (rect.right - radius, rect.bottom, -1, -1),
        ):
            corner = (x + dx * inset, y + dy * inset)
            pygame.draw.line(
                surface, border, corner, (corner[0] + dx * arm, corner[1]), thickness
            )
            pygame.draw.line(
                surface, border, corner, (corner[0], corner[1] + dy * arm), thickness
            )

    def _draw_tank_shield(
        self, surface: pygame.Surface, rect: pygame.Rect, border, enemy
    ) -> None:
        ui = self._ui
        glow = max(0.0, min(1.0, getattr(enemy, "pulse", 0.5)))
        halo = rect.inflate(ui.px(10 + 8 * glow), ui.px(8 + 6 * glow))
        halo_surface = pygame.Surface(halo.size, pygame.SRCALPHA)
        halo_surface.fill((*border, int(26 + 34 * glow)))
        surface.blit(halo_surface, halo.topleft)

    def _draw_boss_aura(self, surface: pygame.Surface, rect: pygame.Rect, border) -> None:
        ui = self._ui
        beat = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 150.0)
        halo = rect.inflate(ui.px(26 + 16 * beat), ui.px(18 + 12 * beat))
        halo_surface = pygame.Surface(halo.size, pygame.SRCALPHA)
        halo_surface.fill((*border, int(22 + 30 * beat)))
        surface.blit(halo_surface, halo.topleft)

    def _draw_enemy_header(
        self,
        surface: pygame.Surface,
        enemy,
        header: pygame.Rect,
        border,
        active: bool,
    ) -> None:
        ui = self._ui
        pad = ui.px(10)
        if not active:
            ui.text(
                surface, f"{enemy.type_label}  {enemy.difficulty}", 12, border,
                header.x + pad, header.centery, bold=True, anchor="midleft",
            )
            return
        # A solid pill reads as "this one" far faster than a colour change.
        cap_font = ui.font(11, True)
        text = cap_font.render("ACTIVE", True, DARK_BG)
        cap = pygame.Rect(
            header.x + pad, header.centery - text.get_height() // 2 - ui.px(3),
            text.get_width() + ui.px(12), text.get_height() + ui.px(6),
        )
        chip = pygame.Surface(cap.size, pygame.SRCALPHA)
        chip.fill((*border, 240))
        surface.blit(chip, cap.topleft)
        surface.blit(text, (cap.x + ui.px(6), cap.y + ui.px(3)))
        ui.text(
            surface, f"{enemy.type_label}  {enemy.difficulty}", 12, TEXT_DIM,
            cap.right + ui.px(10), header.centery, bold=True, anchor="midleft",
        )

    def _draw_boss_header(
        self, surface: pygame.Surface, enemy, header: pygame.Rect, border
    ) -> None:
        ui = self._ui
        label = f"BOSS  //  {enemy.phase_label}  //  {enemy.health_ratio * 100:.0f}% HP"
        ui.text(
            surface, label, 15, border, header.x + ui.px(12), header.centery,
            bold=True, anchor="midleft",
        )
        ticks = ("█" * max(0, int(enemy.health_ratio * 10))).ljust(10, "░")
        ui.text(
            surface, ticks, 12, border, header.right - ui.px(12), header.centery,
            bold=True, anchor="midright",
        )

    def _draw_health_bar(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        border,
        enemy,
    ) -> None:
        ui = self._ui
        pad = ui.px(10)
        bar = pygame.Rect(
            rect.x + pad, rect.bottom - self._layout.enemy_footer_height + ui.px(7),
            rect.width - pad * 2, max(3, ui.px(5)),
        )
        ui.meter(surface, bar, enemy.health_ratio, border, track=HAIRLINE_DIM)

    def _draw_code(
        self,
        surface,
        enemy,
        rect: pygame.Rect,
        active: bool,
        border,
    ) -> None:
        """Render the one line the player is on, scaled to fill the card.

        A card shows a single line — the one holding the typing cursor — and
        nothing else. A whole listing is a wall of colour, and the player is
        reading one line at a time to retype it; the rest of the card stays
        quiet instead of competing for the eye. Scrolling is the cursor's doing,
        not the player's: type the newline and the next line is already there,
        so the line on screen is always the line being typed, in every language.

        The line keeps every hue it had in the full listing. The typed half is
        the flat green it has always been — progress is the signal the player
        plays against and must not compete with the palette — and the rest is
        painted by token kind, so a string or block comment is visibly still
        open before the player reaches it.
        """
        ui = self._ui
        text = enemy.text
        cursor = min(enemy.typing.index, len(text))
        start, end = enemy.line_bounds[enemy.line_index_for(cursor)]

        pad = ui.px(10)
        area = pygame.Rect(
            rect.x + pad,
            rect.y + self._layout.enemy_header_height,
            rect.width - pad * 2,
            enemy.code_height,
        )
        # The line counter needs a strip of its own, and only a multi-line
        # snippet has one to show.
        counter_room = ui.px(14) if len(enemy.line_bounds) > 1 else 0
        line_box = max(ui.px(10), area.height - counter_room)
        # The slack is deliberate: a line is drawn as a run per token, and a run
        # per token can measure a pixel or two wider than the whole line does in
        # one go. Without it a long line could just clear the fit and still poke
        # past the card's edge.
        size = self._fit_code_size(
            ui, enemy, area.width - ui.px(10), line_box - ui.px(4)
        )
        line_height = ui.font(size, True).get_height()
        y = area.y + (line_box - line_height) // 2

        x = area.x
        caret_x: int | None = None
        for token in enemy.tokens.between(start, end):
            # A token can straddle the cursor or a line break, so both of its
            # ends are clamped to the piece of this line being drawn.
            piece_start = max(token.start, start)
            piece_end = min(token.end, end)
            if piece_start >= cursor:
                x += ui.blit_run(
                    surface,
                    text[piece_start:piece_end],
                    size,
                    SYNTAX_COLOURS.get(token.kind, REMAINING_COLOUR),
                    x,
                    y,
                    bold=True,
                )
                continue
            if caret_x is None:
                typed_end = min(piece_end, cursor)
                x += ui.blit_run(
                    surface, text[piece_start:typed_end], size, TYPED_COLOUR, x, y,
                    bold=True,
                )
                if typed_end >= cursor:
                    caret_x = x
            if piece_end > cursor:
                x += ui.blit_run(
                    surface,
                    text[max(piece_start, cursor):piece_end],
                    size,
                    SYNTAX_COLOURS.get(token.kind, REMAINING_COLOUR),
                    x,
                    y,
                    bold=True,
                )
        if caret_x is None and start <= cursor <= end:
            # Nothing on this line has been typed yet, so the cursor sits at the
            # margin — the same place the old two-block draw put it.
            caret_x = x
        if caret_x is not None:
            caret_width = max(2, ui.px(3))
            caret_height = max(3, int(line_height * 0.86))
            pygame.draw.rect(
                surface,
                CURSOR_COLOUR if active else GREY,
                (caret_x, y + (line_height - caret_height) // 2, caret_width, caret_height),
            )

        if counter_room:
            number = enemy.line_index_for(cursor) + 1
            ui.text(
                surface,
                f"LINE {number} / {len(enemy.line_bounds)}",
                10,
                GREY,
                area.right,
                area.bottom - ui.px(2),
                bold=True,
                anchor="bottomright",
            )

    def _fit_code_size(self, ui, enemy, width: int, height: int) -> int:
        """Largest bold size at which every line of the snippet still fits.

        The card is sized for up to ``ENEMY_MAX_LINES`` lines but only ever
        shows one, so a short line on a tall card can afford to be much bigger
        than a long one on a short card. Anything wider than the card would run
        off the edge, so the width is the hard limit and the height only caps it.

        Measuring every line at every candidate size is not free, and this runs
        on a per-frame redraw, so the answer is cached against the box it was
        fitted to — a resize is the only thing that can invalidate it.
        """
        key = (width, height)
        cached = enemy.code_size_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        lines = [enemy.text[start:end] for start, end in enemy.line_bounds]
        size = _CODE_SIZE_MIN
        for candidate in range(_CODE_SIZE_MAX, _CODE_SIZE_MIN - 1, -1):
            if ui.font(candidate, True).get_height() > height:
                continue
            if any(ui.measure(line, candidate, True)[0] > width for line in lines):
                continue
            size = candidate
            break
        enemy.code_size_cache = (key, size)
        return size

    # ── Transient overlays ───────────────────────────────────────────────────

    def _draw_message(self, surface: pygame.Surface, width: int, height: int) -> None:
        if self._message_timer <= 0:
            return
        ui = self._ui
        alpha = min(1.0, self._message_timer / 1.2)
        bar = self._competition_bar_rect(width)
        top = self._layout.hud_height + (bar.height if bar is not None else 0)
        ui.text(
            surface, self._message, 22, mix(NEON_CYAN, DARK_BG, 1.0 - alpha),
            width // 2, top + ui.px(16),
            bold=True, anchor="midtop", glow=None,
        )

    def _draw_banner(self, surface: pygame.Surface, width: int, height: int) -> None:
        if not self._banner or self._banner_timer <= 0:
            return
        ui = self._ui
        ratio = max(0.0, min(1.0, self._banner_timer))
        beat = pulse(pygame.time.get_ticks() / 1000.0, 8.0)
        colour = mix(NEON_RED, DARK_BG, 1.0 - ratio * (0.6 + 0.4 * beat))
        title = ui.font(40, True).render(self._banner, True, colour)
        rect = title.get_rect(center=(width // 2, int(height * 0.34)))

        plate = rect.inflate(ui.px(70), ui.px(30))
        ui.panel(
            surface, plate, fill=(40, 6, 12), alpha=int(60 + 120 * ratio),
            border=NEON_RED, border_width=max(1, ui.px(1)), glow=ratio,
        )
        surface.blit(title, rect)

    def _draw_pause(self, surface: pygame.Surface) -> None:
        ui = self._ui
        ui.veil(surface, 196)
        box = ui.centre_panel(420, 190)
        ui.panel(
            surface, box, fill=PANEL_BG, alpha=250, border=NEON_CYAN,
            accent=NEON_CYAN, glow=0.6 + 0.4 * self._pause_blink,
        )
        ui.heading(surface, "PAUSED", box.centerx, box.y + ui.px(26), size=32)
        if self._pause_blink < 0.5:
            ui.chips(
                surface, [("ESC", "RESUME"), ("M", "MAIN MENU")], box.bottom - ui.px(34)
            )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _enemy_colour(enemy) -> tuple[int, int, int]:
        if not getattr(enemy, "is_boss", False):
            return ENEMY_COLOURS.get(enemy.enemy_type, NEON_CYAN)
        return NEON_RED if getattr(enemy, "intro_active", False) else enemy.phase_colour
