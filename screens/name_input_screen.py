"""Name entry for tournament mode.

For CCS Days tournament, collects player name, team number (1-5), and player number (1-5).
For legacy competition modes, only collects player name.
"""

from __future__ import annotations

import pygame

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
    TOURNAMENT_PLAYER_NUMBERS,
    TOURNAMENT_TEAM_NUMBERS,
    TOURNAMENT_NAME,
)
from game.audio_manager import SFX_MENU_MOVE, SFX_MENU_SELECT
from game.display import toggle_fullscreen
from game.input_map import printable_character
from game.ui import UI, Stage, pulse
from game.tournament import TournamentStore


class NameInputScreen:
    def __init__(
        self,
        screen,
        settings,
        assets,
        audio,
        leaderboard,
        mode,
        difficulty: str | None = None,
        competition=None,
        tournament=None,
        team: int | None = None,
        player: int | None = None,
    ):
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._mode = mode
        self._difficulty = difficulty
        self._competition = competition
        self._tournament = tournament
        
        # CCS Days tournament fields
        self._name = ""
        self._max_length = 32
        self._team = team
        self._player = player
        self._focus = 0  # 0: name, 1: team, 2: player
        self._error = ""
        self._notice = ""
        self._status = "available"
        self._status_result = None
        self._reset_confirm = False
        
        # Legacy fields for non-tournament modes
        self._legacy_name = ""
        self._legacy_max_length = 32
        
        self._tick = 0.0
        self._rebuild(screen)
        self._refresh_status()

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=120, horizon_fraction=0.5, scroll=16.0)

    def set_surface(self, screen: pygame.Surface) -> None:
        """Adopt a new surface after a display-mode change."""
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        """F11: borderless fullscreen at the monitor's own resolution."""
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
        if self._tournament is not None:
            return self._handle_tournament_key(event)
        return self._handle_legacy_key(event)

    # ── Legacy name entry ────────────────────────────────────────────────────

    def _handle_legacy_key(self, event: pygame.event.Event):
        if event.key == pygame.K_ESCAPE:
            from screens.main_menu import MainMenuScreen
            return MainMenuScreen(
                self._screen,
                self._settings,
                self._assets,
                self._audio,
                self._leaderboard,
            )
        if event.key in (pygame.K_RETURN, getattr(pygame, "K_KP_ENTER", -1)):
            from screens.game_screen import GameScreen
            name = self._name.strip() or "PLAYER"
            self._audio.play(SFX_MENU_SELECT)
            return GameScreen(
                self._screen,
                self._settings,
                self._assets,
                self._audio,
                self._leaderboard,
                self._mode,
                name,
                self._difficulty,
                competition=self._competition,
            )
        if event.key == pygame.K_BACKSPACE:
            self._name = self._name[:-1]
            return None
        character = printable_character(event)
        if character is not None and len(self._name) < self._max_length:
            self._name += character
        return None

    # ── CCS Days tournament registration ─────────────────────────────────────

    def _handle_tournament_key(self, event: pygame.event.Event):
        key = event.key
        if self._reset_confirm:
            return self._handle_reset_key(key)
        if key == pygame.K_ESCAPE:
            from screens.tournament_screen import TournamentScreen
            return TournamentScreen(
                self._screen, self._settings, self._assets,
                self._audio, self._leaderboard, difficulty=self._difficulty,
            )
            from screens.main_menu import MainMenuScreen
            return MainMenuScreen(
                self._screen,
                self._settings,
                self._assets,
                self._audio,
                self._leaderboard,
            )
        if key == pygame.K_F8:
            if self._team is not None and self._player is not None:
                self._reset_confirm = True
                self._audio.play(SFX_MENU_SELECT)
            else:
                self._error = "SELECT A TEAM AND PLAYER NUMBER BEFORE RESET"
            return None
        if key in (pygame.K_TAB, pygame.K_DOWN, pygame.K_UP):
            step = -1 if key in (pygame.K_UP, pygame.K_TAB) else 1
            self._focus = (self._focus + step) % 3
            self._audio.play(SFX_MENU_MOVE)
            return None

        if key == pygame.K_BACKSPACE:
            if self._focus == 0:
                self._name = self._name[:-1]
            return None

        if key in (pygame.K_RETURN, getattr(pygame, "K_KP_ENTER", -1)):
            return self._start_tournament_attempt()

        if self._focus == 1:
            if key in (pygame.K_LEFT, pygame.K_a):
                self._adjust_choice(team=True, delta=-1)
            elif key in (pygame.K_RIGHT, pygame.K_d):
                self._adjust_choice(team=True, delta=1)
            else:
                self._set_choice_from_key(team=True, key=key)
            return None

        if self._focus == 2:
            if key in (pygame.K_LEFT, pygame.K_a):
                self._adjust_choice(team=False, delta=-1)
            elif key in (pygame.K_RIGHT, pygame.K_d):
                self._adjust_choice(team=False, delta=1)
            else:
                self._set_choice_from_key(team=False, key=key)
            return None

        character = printable_character(event)
        if character is not None and len(self._name) < self._max_length:
            self._name += character
        return None

    def _set_choice_from_key(self, *, team: bool, key: int) -> None:
        number = None
        for index, candidate in enumerate(TOURNAMENT_TEAM_NUMBERS if team else TOURNAMENT_PLAYER_NUMBERS, start=1):
            key_code = getattr(pygame, f"K_{index}", -1)
            if key == key_code or key == getattr(pygame, f"K_KP{index}", -1):
                number = candidate
                break
        if number is not None:
            if team:
                self._team = number
            else:
                self._player = number
            self._after_choice_change()

    def _adjust_choice(self, *, team: bool, delta: int) -> None:
        values = TOURNAMENT_TEAM_NUMBERS if team else TOURNAMENT_PLAYER_NUMBERS
        current = self._team if team else self._player
        if current is None:
            new_value = values[0] if delta > 0 else values[-1]
        else:
            index = (values.index(current) + delta) % len(values)
            new_value = values[index]
        if team:
            self._team = new_value
        else:
            self._player = new_value
        self._after_choice_change()

    def _after_choice_change(self) -> None:
        self._error = ""
        self._audio.play(SFX_MENU_MOVE)
        self._refresh_status()

    def _refresh_status(self) -> None:
        self._status = "available"
        self._status_result = None
        if (
            self._tournament is None
            or self._team is None
            or self._player is None
        ):
            return
        try:
            status = self._tournament.slot_status(self._team, self._player)
        except (OSError, TypeError, ValueError):
            return
        self._status = status.state
        self._status_result = status.result

    def _start_tournament_attempt(self):
        """Start CCS Days tournament attempt."""
        name = self._name.strip()
        self._error = ""
        if not name:
            self._error = "ENTER PLAYER NAME"
            return None
        if self._team is None:
            self._error = "SELECT TEAM 1-5"
            return None
        if self._player is None:
            self._error = "SELECT PLAYER NUMBER 1-5"
            return None
        if self._tournament is None:
            self._error = "COMPETITION STORAGE UNAVAILABLE"
            return None

        try:
            start = self._tournament.begin_attempt(name, self._team, self._player)
        except (OSError, TypeError, ValueError) as exc:
            self._error = str(exc) or "COULD NOT START OFFICIAL ATTEMPT"
            return None
        if not start.get("accepted") or start.get("entry") is None:
            self._error = start.get("reason", "") or "COULD NOT START OFFICIAL ATTEMPT"
            self._refresh_status()
            return None

        self._refresh_status()
        self._audio.play(SFX_MENU_SELECT)
        from screens.game_screen import GameScreen

        entry = start.get("entry")
        return GameScreen(
            self._screen,
            self._settings,
            self._assets,
            self._audio,
            self._leaderboard,
            "tournament",
            entry.player_name,
            "EASY",
            competition=entry,
        )

    def _handle_reset_key(self, key: int):
        if key == pygame.K_y and self._team is not None and self._player is not None:
            removed = False
            if self._tournament is not None:
                try:
                    removed = self._tournament.reset_slot(self._team, self._player)
                except (OSError, TypeError, ValueError):
                    self._error = "COULD NOT RESET SLOT"
            self._notice = (
                "SLOT CLEARED — ONE NEW ATTEMPT ALLOWED"
                if removed
                else "SLOT WAS ALREADY EMPTY"
            )
            self._error = "" if removed else self._error
            self._refresh_status()
            self._reset_confirm = False
            self._audio.play(SFX_MENU_SELECT)
            return None
        if key in (pygame.K_n, pygame.K_ESCAPE):
            self._reset_confirm = False
            self._audio.play(SFX_MENU_MOVE)
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)

        if self._tournament is not None:
            self._draw_tournament()
            if self._reset_confirm:
                self._draw_reset_confirm()
        else:
            self._draw_legacy()

    def _draw_legacy(self) -> None:
        ui = self._ui
        box = ui.centre_panel(560, 300)
        ui.panel(
            self._screen, box,
            fill=PANEL_BG, alpha=238, border=HAIRLINE_DIM,
            accent=NEON_CYAN, glow=0.3 + 0.2 * pulse(self._tick, 1.5),
        )
        title = (
            "ENTER REPRESENTATIVE NAME"
            if self._competition is not None
            else "ENTER PLAYER NAME"
        )
        ui.text(
            self._screen, title, 28, TEXT_BRIGHT, box.centerx,
            box.y + ui.px(30), bold=True, anchor="midtop", glow=NEON_CYAN,
        )
        subtitle = f"MODE   //   {self._mode.upper()}"
        if self._competition is not None:
            subtitle = (
                f"{self._competition.team_name.upper()}   //   "
                f"REPRESENTATIVE {self._competition.slot}"
            )
        ui.text(
            self._screen, subtitle, 13, TEXT_DIM,
            box.centerx, box.y + ui.px(70), anchor="midtop",
        )
        ui.divider(
            self._screen, box.x + ui.px(30), box.right - ui.px(30),
            box.y + ui.px(92), HAIRLINE_DIM,
        )

        self._draw_field(box)
        self._draw_footer(box)

    def _draw_field(self, box: pygame.Rect) -> None:
        ui = self._ui
        field = pygame.Rect(
            box.x + ui.px(30), box.y + ui.px(112), box.width - ui.px(60), ui.px(58)
        )
        caret_on = (pygame.time.get_ticks() // 450) % 2 == 0
        pygame.draw.rect(
            self._screen, NEON_CYAN, field, max(1, ui.px(2)), border_radius=ui.px(6)
        )
        glow = field.inflate(ui.px(8), ui.px(8))
        wash = pygame.Surface(glow.size, pygame.SRCALPHA)
        wash.fill((*NEON_CYAN, 18))
        self._screen.blit(wash, glow.topleft)

        shown = self._name or "PLAYER"
        placeholder = not self._name
        colour = TEXT_BRIGHT if placeholder else TEXT_BRIGHT
        text = f"{shown}{'_' if caret_on else ''}" if not placeholder else shown
        if placeholder and caret_on:
            text = f"{shown}_"
        ui.text(
            self._screen, text, 26, colour,
            field.x + ui.px(16), field.centery, bold=True, anchor="midleft",
            glow=NEON_CYAN if placeholder else None,
        )

        ratio = min(1.0, len(self._name) / self._max_length)
        meter = pygame.Rect(
            field.x, field.bottom + ui.px(12), field.width, max(2, ui.px(4))
        )
        ui.meter(
            self._screen, meter, ratio,
            NEON_PINK if ratio > 0.85 else NEON_CYAN, track=HAIRLINE_DIM,
        )
        ui.text(
            self._screen, f"{len(self._name)}/{self._max_length}", 12, TEXT_DIM,
            meter.right, meter.bottom + ui.px(6), bold=True, anchor="topright",
        )

    def _draw_footer(self, box: pygame.Rect) -> None:
        ui = self._ui
        ui.chips(
            self._screen,
            [("ENTER", "START"), ("BACKSPACE", "EDIT"), ("ESC", "MENU")],
            box.bottom - ui.px(28),
        )

    # ── Tournament drawing ────────────────────────────────────────────────────

    def _draw_tournament(self) -> None:
        ui = self._ui
        box = ui.centre_panel(700, 500)
        accent = NEON_CYAN if self._status == "available" else NEON_ORANGE
        ui.panel(
            self._screen, box, fill=PANEL_BG, alpha=242, border=HAIRLINE_DIM,
            accent=accent, glow=0.34 + 0.2 * pulse(self._tick, 1.8),
        )

        ui.text(
            self._screen, TOURNAMENT_NAME, 25, TEXT_BRIGHT, box.centerx,
            box.y + ui.px(18), bold=True, anchor="midtop", glow=NEON_YELLOW,
        )
        ui.text(
            self._screen, "PLAYER REGISTRATION   //   ONE OFFICIAL ATTEMPT",
            12, TEXT_DIM, box.centerx, box.y + ui.px(52), anchor="midtop",
        )
        ui.divider(
            self._screen, box.x + ui.px(30), box.right - ui.px(30),
            box.y + ui.px(74), HAIRLINE_DIM,
        )

        left = box.x + ui.px(34)
        inner_w = box.width - ui.px(68)
        ui.section_label(
            self._screen, "PLAYER NAME", left, box.y + ui.px(86),
            colour=TEXT_DIM,
        )
        name_field = pygame.Rect(
            left, box.y + ui.px(102), inner_w, ui.px(52)
        )
        self._draw_name_field(name_field)

        gap = ui.px(14)
        choice_w = (inner_w - gap) // 2
        choice_top = box.y + ui.px(196)
        team_field = pygame.Rect(left, choice_top, choice_w, ui.px(52))
        player_field = pygame.Rect(
            left + choice_w + gap, choice_top, choice_w, ui.px(52)
        )
        self._draw_choice_field(
            team_field,
            "TEAM",
            team_label(self._team).upper() if self._team is not None else "SELECT",
            focused=self._focus == 1,
            selected=self._team is not None,
        )
        self._draw_choice_field(
            player_field,
            "PLAYER NUMBER",
            player_label(self._player).upper()
            if self._player is not None
            else "SELECT",
            focused=self._focus == 2,
            selected=self._player is not None,
        )

        status_y = box.y + ui.px(272)
        self._draw_status(left, inner_w, status_y)

        if self._error:
            ui.text(
                self._screen, self._error[:78], 12, NEON_RED,
                box.centerx, box.y + ui.px(316), bold=True, anchor="midtop",
            )
        elif self._notice:
            ui.text(
                self._screen, self._notice[:78], 12, NEON_GREEN,
                box.centerx, box.y + ui.px(316), bold=True, anchor="midtop",
            )

        ui.divider(
            self._screen, left, box.right - ui.px(34),
            box.bottom - ui.px(92), HAIRLINE_DIM,
        )
        ui.text(
            self._screen,
            "5 WAVES  ·  3 LIVES  ·  EASY START  ·  SAME CONTENT FOR EVERY PC",
            11, TEXT_DIM, box.centerx, box.bottom - ui.px(82), anchor="midtop",
        )
        ui.text(
            self._screen,
            "One attempt per team + player number on this PC. "
            "Organizers record individual scores manually.",
            10, TEXT_DIM, box.centerx, box.bottom - ui.px(64), anchor="midtop",
        )

        hints = [
            ("TAB", "FIELD"), ("← →", "SELECT"), ("ENTER", "START"),
            ("ESC", "MENU"),
        ]
        if self._status != "available":
            hints.insert(3, ("F8", "RESET"))
        ui.chips(self._screen, hints, box.bottom - ui.px(26))

    def _draw_name_field(self, rect: pygame.Rect) -> None:
        ui = self._ui
        focused = self._focus == 0
        colour = NEON_CYAN if focused else HAIRLINE_DIM
        if focused:
            wash = pygame.Surface(rect.inflate(ui.px(8), ui.px(8)).size, pygame.SRCALPHA)
            wash.fill((*NEON_CYAN, 18))
            self._screen.blit(wash, rect.inflate(ui.px(8), ui.px(8)).topleft)
        pygame.draw.rect(
            self._screen, colour, rect,
            max(1, ui.px(2) if focused else ui.px(1)),
            border_radius=ui.px(5),
        )
        caret_on = (pygame.time.get_ticks() // 450) % 2 == 0
        if self._name:
            shown = f"{self._name}{'_' if focused and caret_on else ''}"
            text_colour = TEXT_BRIGHT
        else:
            shown = "TYPE PLAYER NAME" + ("_" if focused and caret_on else "")
            text_colour = TEXT_DIM
        ui.text(
            self._screen, shown, 22, text_colour,
            rect.x + ui.px(14), rect.centery, bold=True, anchor="midleft",
        )
        ui.text(
            self._screen, f"{len(self._name)}/{self._max_length}", 10, TEXT_DIM,
            rect.right - ui.px(10), rect.bottom - ui.px(4),
            anchor="bottomright",
        )

    def _draw_choice_field(
        self,
        rect: pygame.Rect,
        label: str,
        value: str,
        *,
        focused: bool,
        selected: bool,
    ) -> None:
        ui = self._ui
        border = NEON_CYAN if focused else HAIRLINE_DIM
        ui.panel(
            self._screen, rect, fill=SURFACE_RAISED if focused else PANEL_BG,
            alpha=236, border=border, glow=0.25 if focused else 0.0,
        )
        ui.text(
            self._screen, label, 9, NEON_CYAN,
            rect.x + ui.px(14), rect.y + ui.px(10), bold=True, anchor="topleft",
        )
        ui.text(
            self._screen, value, 18,
            TEXT_BRIGHT if selected else TEXT_DIM,
            rect.centerx, rect.y + ui.px(31), bold=True, anchor="center",
        )
        arrow_colour = NEON_CYAN if focused else HAIRLINE_DIM
        ui.text(
            self._screen, "◀", 13, arrow_colour,
            rect.x + ui.px(10), rect.centery + ui.px(4), anchor="midleft",
        )
        ui.text(
            self._screen, "▶", 13, arrow_colour,
            rect.right - ui.px(10), rect.centery + ui.px(4), anchor="midright",
        )

    def _draw_status(self, left: int, width: int, y: int) -> None:
        ui = self._ui
        if self._team is None or self._player is None:
            message = "SELECT A TEAM AND PLAYER NUMBER TO CHECK THIS PC'S ATTEMPT SLOT"
            colour = TEXT_DIM
        elif self._status == "started":
            message = (
                "SLOT LOCKED — ATTEMPT STARTED OR INTERRUPTED  ·  "
                "F8 ORGANIZER RESET"
            )
            colour = NEON_ORANGE
        elif self._status == "completed":
            result = self._status_result
            detail = ""
            if result is not None and result.score is not None:
                detail = (
                    f"  ·  SCORE {result.score:,}  ·  {result.wpm:.1f} WPM"
                    f"  ·  {result.accuracy:.1f}%"
                )
            message = (
                "SLOT LOCKED — RESULT ALREADY RECORDED"
                f"{detail}  ·  F8 ORGANIZER RESET"
            )
            colour = NEON_ORANGE
        else:
            message = "SLOT AVAILABLE — READY FOR THE OFFICIAL ATTEMPT"
            colour = NEON_GREEN
        ui.text(
            self._screen, message[:110], 12, colour,
            left, y, bold=True, anchor="topleft",
        )
        ui.text(
            self._screen,
            f"{team_label(self._team or 0).upper() if self._team else 'TEAM —'}"
            f"   //   "
            f"{player_label(self._player or 0).upper() if self._player else 'PLAYER —'}",
            11, TEXT_DIM, left, y + ui.px(18),
            anchor="topleft",
        )

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
            self._screen, "ORGANIZER RESET", box.centerx,
            box.y + ui.px(26), size=24, colour=NEON_RED, glow=NEON_RED,
        )
        ui.text(
            self._screen,
            f"Clear {team_label(self._team or 0)} {player_label(self._player or 0)}"
            " and allow one new attempt?",
            14, TEXT_BRIGHT, box.centerx, box.bottom - ui.px(84),
            anchor="midtop",
        )
        ui.text(
            self._screen,
            "Existing CSV rows are never deleted.",
            11, TEXT_DIM, box.centerx, box.bottom - ui.px(62),
            anchor="midtop",
        )
        ui.chips(
            self._screen, [("Y", "CLEAR SLOT"), ("N / ESC", "CANCEL")],
            box.bottom - ui.px(30),
        )


def team_label(number: int) -> str:
    return f"Team {number}"


def player_label(number: int) -> str:
    return f"Player {number}"