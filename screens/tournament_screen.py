"""Tournament mode for CodeType.

Each participant enters their details and completes one official attempt.
Organizers manually calculate team totals from individual results.
"""

from __future__ import annotations

import pygame

from game.audio_manager import SFX_MENU_MOVE, SFX_MENU_SELECT
from game.constants import (
    HAIRLINE_DIM,
    NEON_CYAN,
    NEON_GREEN,
    NEON_ORANGE,
    NEON_PINK,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    SURFACE_RAISED,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
    TOURNAMENT_DIFFICULTY,
    TOURNAMENT_NAME,
    TOURNAMENT_PLAYER_NUMBERS,
    TOURNAMENT_TEAM_NUMBERS,
)
from game.display import toggle_fullscreen
from game.input_map import printable_character
from game.ui import UI, Stage, pulse
from game.tournament import TournamentStore


class TournamentScreen:
    """Tournament hub for participant registration and attempt tracking.

    Manages team setup, individual participant slots, and tournament progression
    without automatic team totals or brackets. Each participant gets one official
    attempt, identified by team number and player number.
    """

    def __init__(self, screen, settings, assets, audio, leaderboard, difficulty=None):
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._difficulty = difficulty
        self._tournament = getattr(leaderboard, "tournament", None)
        self._team_index = 0
        self._player_index = 0
        self._slot_index = 0  # 0: team field, 1: player field
        self._status = "available"
        self._status_result = None
        self._reset_confirm = False
        self._notice = ""
        self._refresh_status()
        self._tick = 0.0
        self._rebuild(screen)

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=140, horizon_fraction=0.5, scroll=20.0)

    def set_surface(self, screen: pygame.Surface) -> None:
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        self.set_surface(toggle_fullscreen(self._settings))

    def run(self, clock: pygame.time.Clock):
        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt
            self._stage.update(dt)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self._toggle_fullscreen()
                        continue
                    result = self._handle_key(event)
                    if result is not None:
                        return result
            self._draw()
            pygame.display.flip()

    def _handle_key(self, event: pygame.event.Event):
        key = event.key
        if self._reset_confirm:
            return self._handle_reset_key(key)
        if key == pygame.K_ESCAPE:
            return self._to_menu()
        if key == pygame.K_F8 or key == pygame.K_r:
            if self._status != "available":
                self._reset_confirm = True
                self._notice = ""
                self._audio.play(SFX_MENU_SELECT)
            return None
        if key in (pygame.K_TAB, pygame.K_DOWN, pygame.K_UP):
            self._audio.play(SFX_MENU_MOVE)
            backwards = key == pygame.K_UP or (
                key == pygame.K_TAB and event.mod & pygame.KMOD_SHIFT
            )
            self._move_selection(direction=-1 if backwards else 1)
            return None
        if key in (pygame.K_LEFT, pygame.K_a):
            self._adjust(-1)
            return None
        if key in (pygame.K_RIGHT, pygame.K_d):
            self._adjust(1)
            return None
        if pygame.K_1 <= key <= pygame.K_9 or pygame.K_KP1 <= key <= pygame.K_KP9:
            base = pygame.K_1 if key <= pygame.K_9 else pygame.K_KP1
            self._set_number(key - base + 1)
            return None
        if key == pygame.K_RETURN or key == getattr(pygame, "K_KP_ENTER", -1):
            return self._start_participant_selection()
        if key == pygame.K_l:
            from screens.leaderboard_screen import LeaderboardScreen
            self._audio.play(SFX_MENU_SELECT)
            return LeaderboardScreen(
                self._screen, self._settings, self._assets,
                self._audio, self._leaderboard,
            )
        return None

    def _move_selection(self, direction: int) -> None:
        """Move focus between the team and player fields."""
        self._slot_index = (self._slot_index + direction) % 2

    def _adjust(self, delta: int) -> None:
        """Change the focused field's value, wrapping around."""
        self._audio.play(SFX_MENU_MOVE)
        if self._slot_index == 0:
            count = len(TOURNAMENT_TEAM_NUMBERS)
            self._team_index = (self._team_index + delta) % count
        else:
            count = len(TOURNAMENT_PLAYER_NUMBERS)
            self._player_index = (self._player_index + delta) % count
        self._refresh_status()

    def _set_number(self, number: int) -> None:
        """Jump straight to a number with the 1-5 keys."""
        if self._slot_index == 0:
            numbers, attr = TOURNAMENT_TEAM_NUMBERS, "_team_index"
        else:
            numbers, attr = TOURNAMENT_PLAYER_NUMBERS, "_player_index"
        if number in numbers:
            setattr(self, attr, numbers.index(number))
            self._audio.play(SFX_MENU_MOVE)
            self._refresh_status()

    @property
    def _team_number(self) -> int:
        return TOURNAMENT_TEAM_NUMBERS[self._team_index]

    @property
    def _player_number(self) -> int:
        return TOURNAMENT_PLAYER_NUMBERS[self._player_index]

    def _handle_reset_key(self, key: int):
        if key == pygame.K_y:
            removed = False
            if self._tournament is not None:
                try:
                    removed = self._tournament.reset_slot(
                        self._team_number, self._player_number
                    )
                except (OSError, TypeError, ValueError):
                    removed = False
            self._notice = (
                "SLOT REFRESHED - ONE NEW ATTEMPT ALLOWED"
                if removed else "COULD NOT RESET SLOT"
            )
            self._reset_confirm = False
            self._refresh_status()
            self._audio.play(SFX_MENU_SELECT)
        elif key in (pygame.K_n, pygame.K_ESCAPE):
            self._reset_confirm = False
            self._audio.play(SFX_MENU_MOVE)
        return None

    def _refresh_status(self) -> None:
        self._status = "available"
        self._status_result = None
        if self._tournament is None:
            return
        try:
            status = self._tournament.slot_status(
                self._team_number, self._player_number
            )
        except (OSError, TypeError, ValueError):
            return
        self._status = status.state
        self._status_result = status.result

    def _start_participant_selection(self):
        """Continue to name entry with the chosen team and player."""
        from screens.name_input_screen import NameInputScreen

        self._audio.play(SFX_MENU_SELECT)
        return NameInputScreen(
            self._screen, self._settings, self._assets, self._audio,
            self._leaderboard, "tournament", difficulty=self._difficulty,
            tournament=self._tournament,
            team=self._team_number, player=self._player_number,
        )

    def _to_menu(self):
        from screens.main_menu import MainMenuScreen
        return MainMenuScreen(
            self._screen, self._settings, self._assets,
            self._audio, self._leaderboard,
        )

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)
        self._draw_title()
        self._draw_participant_selection()
        self._draw_footer()
        if self._reset_confirm:
            self._draw_reset_confirm()

    def _draw_title(self) -> None:
        ui = self._ui
        cx = ui.width // 2
        ui.text(
            self._screen, TOURNAMENT_NAME, 30, TEXT_BRIGHT, cx,
            ui.px(20), bold=True, anchor="midtop", glow=NEON_CYAN,
        )

    def _draw_participant_selection(self) -> None:
        ui = self._ui
        box = ui.centre_panel(700, 450)
        ui.panel(
            self._screen, box, fill=PANEL_BG, alpha=242, border=HAIRLINE_DIM,
            accent=NEON_CYAN, glow=0.34 + 0.2 * pulse(self._tick, 1.8),
        )
        left = box.x + ui.px(34)
        inner_w = box.width - ui.px(68)

        ui.section_label(self._screen, "TEAM SELECTION", left, box.y + ui.px(50))
        self._draw_choice_field(
            pygame.Rect(left, box.y + ui.px(78), inner_w, ui.px(60)),
            "TEAM", team_label(self._team_number), self._slot_index == 0,
        )

        ui.section_label(self._screen, "PLAYER SELECTION", left, box.y + ui.px(166))
        self._draw_choice_field(
            pygame.Rect(left, box.y + ui.px(194), inner_w, ui.px(60)),
            "PLAYER", player_label(self._player_number), self._slot_index == 1,
        )

        self._draw_status(box.centerx, box.y + ui.px(290))

    def _draw_choice_field(self, rect, label, value, focused) -> None:
        ui = self._ui
        colour = NEON_CYAN if focused else HAIRLINE_DIM
        ui.panel(
            self._screen, rect, fill=SURFACE_RAISED if focused else PANEL_BG,
            alpha=236, border=colour, glow=0.25 if focused else 0.0,
        )
        ui.text(
            self._screen, label, 14, NEON_CYAN,
            rect.x + ui.px(40), rect.y + ui.px(8),
        )
        ui.text(
            self._screen, value, 28, TEXT_BRIGHT,
            rect.centerx, rect.centery + ui.px(4), bold=True, anchor="center",
        )
        ui.text(
            self._screen, "<", 22, colour,
            rect.x + ui.px(16), rect.centery, bold=True, anchor="midleft",
        )
        ui.text(
            self._screen, ">", 22, colour,
            rect.right - ui.px(16), rect.centery, bold=True, anchor="midright",
        )

    def _draw_status(self, cx: int, y: int) -> None:
        ui = self._ui
        if self._status == "started":
            message, colour = "SLOT LOCKED - ATTEMPT ALREADY STARTED", NEON_ORANGE
        elif self._status == "completed":
            message, colour = "SLOT LOCKED - RESULT ALREADY RECORDED", NEON_ORANGE
            result = self._status_result
            if result is not None and result.score is not None:
                message += f"  |  SCORE {result.score:,}"
        else:
            message, colour = "SLOT AVAILABLE - READY FOR THE OFFICIAL ATTEMPT", NEON_GREEN
        if self._status != "available":
            message += "  |  F8 REFRESH"
        ui.text(
            self._screen, message, 13, colour, cx, y, bold=True, anchor="midtop",
        )
        if self._notice:
            ui.text(
                self._screen, self._notice, 12, NEON_GREEN,
                cx, y + ui.px(48), bold=True, anchor="midtop",
            )
        ui.text(
            self._screen,
            f"{team_label(self._team_number).upper()}   //   "
            f"{player_label(self._player_number).upper()}",
            12, TEXT_DIM, cx, y + ui.px(24), anchor="midtop",
        )

    def _draw_footer(self) -> None:
        ui = self._ui
        hints = [
            ("TAB", "FIELD"), ("< >", "CHANGE"), ("1-5", "JUMP"),
            ("ENTER", "CONTINUE"), ("ESC", "MENU"),
        ]
        if self._status != "available":
            hints.insert(4, ("F8", "REFRESH"))
        ui.chips(self._screen, hints, ui.height - ui.px(30))

    def _draw_reset_confirm(self) -> None:
        ui = self._ui
        ui.veil(self._screen, 208)
        box = ui.centre_panel(560, 230)
        ui.panel(
            self._screen, box, fill=PANEL_BG, alpha=250, border=NEON_RED,
            border_width=max(1, ui.px(2)),
            glow=0.5 + 0.5 * pulse(self._tick, 4.0),
        )
        ui.heading(
            self._screen, "REFRESH SLOT", box.centerx,
            box.y + ui.px(26), size=24, colour=NEON_RED, glow=NEON_RED,
        )
        ui.text(
            self._screen,
            f"Clear {team_label(self._team_number)} "
            f"{player_label(self._player_number)} and allow one new attempt?",
            14, TEXT_BRIGHT, box.centerx, box.bottom - ui.px(84),
            anchor="midtop",
        )
        ui.text(
            self._screen, "Existing CSV rows are never deleted.",
            11, TEXT_DIM, box.centerx, box.bottom - ui.px(62), anchor="midtop",
        )
        ui.chips(
            self._screen, [("Y", "CLEAR SLOT"), ("N / ESC", "CANCEL")],
            box.bottom - ui.px(30),
        )


def team_label(number: int) -> str:
    return f"Team {number}"


def player_label(number: int) -> str:
    return f"Player {number}"