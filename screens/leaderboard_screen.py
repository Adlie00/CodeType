"""Leaderboard screen — the local high-score table."""

from __future__ import annotations

import sqlite3

import pygame

from game.constants import (
    HAIRLINE,
    HAIRLINE_DIM,
    NEON_CYAN,
    NEON_GREEN,
    NEON_ORANGE,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    PB_HIGHLIGHT,
    SURFACE_RAISED,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.constants import MODE_CAMPAIGN, MODE_ENDLESS, MODE_COMPETITION
from game.display import toggle_fullscreen
from game.ui import UI, Stage, pulse


# Medals for the top three, so the head of the table separates at a glance.
_RANK_COLOURS = (NEON_YELLOW, (200, 205, 220), (200, 140, 80))

_COLUMNS = (
    ("#", 0.06, "left"),
    ("PLAYER", 0.34, "left"),
    ("SCORE", 0.62, "right"),
    ("WPM", 0.74, "right"),
    ("ACC", 0.84, "right"),
    ("MODE", 0.97, "right"),
)

# Colour per mode for the mode label cells; dim fallback for unknowns.
_MODE_COLOURS = {
    MODE_CAMPAIGN:    NEON_CYAN,
    MODE_ENDLESS:     NEON_GREEN,
    MODE_COMPETITION: NEON_YELLOW,
}

# None means "no filter" (show all).
_FILTER_OPTIONS = (None, MODE_CAMPAIGN, MODE_ENDLESS, MODE_COMPETITION)
_FILTER_LABELS  = ("ALL", "CAMPAIGN", "ENDLESS", "COMPETITION")


class LeaderboardScreen:
    _sort_options = ("score", "wpm", "accuracy")

    def __init__(self, screen, settings, assets, audio, leaderboard):
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._sort_index = 0
        self._filter_index = 0        # index into _FILTER_OPTIONS; 0 = ALL
        # Track who last played so we can highlight their rows.
        self._last_player: str = str(
            getattr(leaderboard, "last_player_name", "") or ""
        )
        self._rows = self._load_rows()
        self._confirm_reset = False
        self._notice = ""
        self._notice_timer = 0.0
        self._tick = 0.0
        self._rebuild(screen)

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=130, horizon_fraction=0.48, scroll=18.0)

    def set_surface(self, screen: pygame.Surface) -> None:
        """Adopt a new surface after a display-mode change."""
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        """F11: borderless fullscreen at the monitor's own resolution."""
        self.set_surface(toggle_fullscreen(self._settings))

    def run(self, clock: pygame.time.Clock):
        from screens.main_menu import MainMenuScreen

        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt
            self._notice_timer = max(0.0, self._notice_timer - dt)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue
                if self._confirm_reset:
                    if event.key in (pygame.K_y, pygame.K_RETURN, pygame.K_KP_ENTER):
                        self._perform_reset()
                    elif event.key in (pygame.K_n, pygame.K_ESCAPE):
                        self._confirm_reset = False
                    continue
                if event.key == pygame.K_ESCAPE:
                    return MainMenuScreen(
                        self._screen,
                        self._settings,
                        self._assets,
                        self._audio,
                        self._leaderboard,
                    )
                if event.key == pygame.K_F12:
                    self._confirm_reset = True
                    continue
                if event.key == pygame.K_r:
                    self._rows = self._load_rows()
                    self._set_notice("REFRESHED")
                if event.key == pygame.K_s:
                    self._sort_index = (self._sort_index + 1) % len(self._sort_options)
                    self._rows = self._load_rows()
                    self._set_notice(f"SORT  {self._sort_options[self._sort_index].upper()}")
                # F or 1–4: cycle / jump to a mode filter
                if event.key == pygame.K_f:
                    self._filter_index = (self._filter_index + 1) % len(_FILTER_OPTIONS)
                    self._rows = self._load_rows()
                    label = _FILTER_LABELS[self._filter_index]
                    self._set_notice(f"FILTER  {label}")
                for digit, idx in ((pygame.K_1, 0), (pygame.K_2, 1),
                                   (pygame.K_3, 2), (pygame.K_4, 3)):
                    if event.key == digit and idx < len(_FILTER_OPTIONS):
                        self._filter_index = idx
                        self._rows = self._load_rows()
                        self._set_notice(f"FILTER  {_FILTER_LABELS[idx]}")
            self._draw()
            pygame.display.flip()

    def _perform_reset(self) -> None:
        self._confirm_reset = False
        if self._leaderboard is None:
            self._set_notice("LEADERBOARD UNAVAILABLE")
            return
        try:
            self._leaderboard.reset()
        except (OSError, sqlite3.Error):
            self._set_notice("RESET FAILED")
            return
        self._rows = self._load_rows()
        self._set_notice("LEADERBOARD CLEARED")

    def _set_notice(self, message: str) -> None:
        self._notice = message
        self._notice_timer = 2.0

    def _load_rows(self) -> list[dict[str, object]]:
        if self._leaderboard is None:
            return []
        try:
            mode_filter = _FILTER_OPTIONS[self._filter_index]
            # get_top accepts an optional mode keyword; fall back for older builds.
            if mode_filter is not None and hasattr(self._leaderboard, "get_top"):
                try:
                    return self._leaderboard.get_top(
                        10, self._sort_options[self._sort_index], mode=mode_filter
                    )
                except TypeError:
                    pass
            return self._leaderboard.get_top(10, self._sort_options[self._sort_index])
        except (OSError, sqlite3.Error):
            return []

    @staticmethod
    def _number(row: dict[str, object], key: str, default: float = 0.0) -> float:
        value = row.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            # The window was resized under us; rebuild for the new size.
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)
        self._draw_table()
        if self._confirm_reset:
            self._draw_reset_prompt()

    def _table_rect(self) -> pygame.Rect:
        ui = self._ui
        margin_x = max(ui.px(24), ui.width // 12)
        top = max(ui.px(28), int(ui.height * 0.08))
        return pygame.Rect(
            margin_x, top, ui.width - margin_x * 2, ui.height - top - ui.px(72)
        )

    def _draw_table(self) -> None:
        ui = self._ui
        table = self._table_rect()
        ui.panel(
            self._screen, table,
            fill=PANEL_BG, alpha=230, border=HAIRLINE_DIM,
            accent=NEON_CYAN, glow=0.25,
        )

        ui.text(
            self._screen, "LEADERBOARD", 34, TEXT_BRIGHT, table.centerx, table.y + ui.px(24),
            bold=True, anchor="midtop", glow=NEON_CYAN,
        )
        # Subtitle: current sort + active mode filter.
        active_filter = _FILTER_LABELS[self._filter_index]
        subtitle = (
            f"SORTED BY  {self._sort_options[self._sort_index].upper()}"
            f"   ·   FILTER  {active_filter}"
        )
        ui.text(
            self._screen, subtitle,
            13, TEXT_DIM, table.centerx, table.y + ui.px(66), anchor="midtop",
        )

        # Column headers, positioned as fractions of the table so the layout
        # holds from a 4K panel down to a small window.
        head_y = table.y + ui.px(96)
        ui.section_label(
            self._screen, "TOP 10", table.x + ui.px(24), head_y
        )
        header_y = head_y + ui.px(26)
        for label, fraction, align in _COLUMNS:
            x = self._column_x(table, fraction)
            ui.text(
                self._screen, label, 12, TEXT_DIM, x, header_y,
                bold=True, anchor=("midright" if align == "right" else "midleft"),
            )
        ui.divider(
            self._screen, table.x + ui.px(24), table.right - ui.px(24),
            header_y + ui.px(14), HAIRLINE_DIM,
        )

        if not self._rows:
            self._draw_empty(table, header_y + ui.px(60))
        else:
            self._draw_rows(table, header_y + ui.px(26))

        self._draw_footer(table)

    def _column_x(self, table: pygame.Rect, fraction: float) -> int:
        return table.x + int(table.width * fraction)

    def _draw_rows(self, table: pygame.Rect, top: int) -> None:
        ui = self._ui
        row_height = max(20, ui.px(34))
        available = table.bottom - ui.px(60) - top
        # Never draw a row past the panel: a short window shows fewer entries
        # rather than spilling over the footer.
        capacity = max(1, int(available // row_height))

        for index, row in enumerate(self._rows[:capacity], start=1):
            y = top + (index - 1) * row_height
            rect = pygame.Rect(table.x + ui.px(16), y, table.width - ui.px(32), row_height)

            name = str(row.get("player_name", "PLAYER"))[:18]
            is_pb = bool(
                self._last_player
                and name.upper() == self._last_player.upper()
            )

            if index == 1:
                # Leader gets a gold wash.
                wash = pygame.Surface(rect.size, pygame.SRCALPHA)
                wash.fill((*NEON_YELLOW, 18))
                self._screen.blit(wash, rect.topleft)
            elif is_pb:
                # Personal-best row: cyan tint + left rail.
                wash = pygame.Surface(rect.size, pygame.SRCALPHA)
                wash.fill((*PB_HIGHLIGHT, 90))
                self._screen.blit(wash, rect.topleft)
                rail = pygame.Rect(rect.x, rect.y, ui.px(3), rect.height)
                pygame.draw.rect(self._screen, NEON_CYAN, rail, border_radius=2)
            elif index % 2 == 0:
                wash = pygame.Surface(rect.size, pygame.SRCALPHA)
                wash.fill((255, 255, 255, 6))
                self._screen.blit(wash, rect.topleft)

            colour = _RANK_COLOURS[index - 1] if index <= 3 else TEXT_BRIGHT
            mode_str = str(row.get("mode", "campaign")).lower()
            mode_label = mode_str.upper()[:10]
            mode_colour = _MODE_COLOURS.get(mode_str, TEXT_DIM)

            cells = (
                (str(index),                                    _COLUMNS[0][1], "left",  colour),
                (name,                                          _COLUMNS[1][1], "left",  colour),
                (f"{int(self._number(row, 'score')):,}",       _COLUMNS[2][1], "right", colour),
                (f"{self._number(row, 'wpm'):.1f}",            _COLUMNS[3][1], "right", TEXT_DIM),
                (f"{self._number(row, 'accuracy'):.1f}%",      _COLUMNS[4][1], "right", TEXT_DIM),
            )
            for value, fraction, align, cell_col in cells:
                x = self._column_x(table, fraction)
                ui.text(
                    self._screen, value, 19 if index <= 3 else 18, cell_col, x,
                    rect.centery, bold=index <= 3,
                    anchor="midright" if align == "right" else "midleft",
                )

            # Mode cell: colour-coded pill label.
            mode_x = self._column_x(table, _COLUMNS[5][1])
            ui.text(
                self._screen, mode_label, 12, mode_colour, mode_x,
                rect.centery, bold=False, anchor="midright",
            )

    def _draw_empty(self, table: pygame.Rect, top: int) -> None:
        ui = self._ui
        y = top + (table.bottom - ui.px(70) - top) // 2
        ui.text(
            self._screen, "NO SCORES RECORDED YET", 24, NEON_GREEN,
            table.centerx, y, bold=True, anchor="midtop",
        )
        ui.text(
            self._screen, "Finish a run to put a name on the board.", 14, TEXT_DIM,
            table.centerx, y + ui.px(38), anchor="midtop",
        )

    def _draw_footer(self, table: pygame.Rect) -> None:
        ui = self._ui
        if self._notice and self._notice_timer > 0:
            fade = min(1.0, self._notice_timer / 0.5)
            ui.text(
                self._screen, self._notice, 13, NEON_GREEN,
                table.centerx, table.bottom - ui.px(56), bold=True, anchor="midtop",
            )
        ui.chips(
            self._screen,
            [
                ("S", "SORT"),
                ("F / 1–4", "FILTER MODE"),
                ("R", "REFRESH"),
                ("F12", "RESET"),
                ("ESC", "BACK"),
            ],
            table.bottom - ui.px(28),
        )

    def _draw_reset_prompt(self) -> None:
        ui = self._ui
        ui.veil(self._screen, 208)
        box = ui.centre_panel(480, 200)
        ui.panel(
            self._screen, box,
            fill=PANEL_BG, alpha=250, border=NEON_RED,
            border_width=max(1, ui.px(2)), glow=0.5 + 0.5 * pulse(self._tick, 4.0),
        )
        ui.heading(
            self._screen, "RESET LEADERBOARD?", box.centerx, box.y + ui.px(30),
            size=26, colour=NEON_RED, glow=NEON_RED,
        )
        ui.text(
            self._screen, "This permanently deletes every saved score.", 15,
            TEXT_BRIGHT, box.centerx, box.bottom - ui.px(62), anchor="midtop",
        )
        ui.chips(
            self._screen,
            [("Y", "DELETE ALL"), ("N / ESC", "CANCEL")],
            box.bottom - ui.px(28),
        )