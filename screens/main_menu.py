"""
Main Menu Screen — entry point of the game UI.

Like every screen this one authors itself in design space and pushes lengths
through ``UI.px``; nothing here is a literal pixel count, so the menu fills a
720p window and a 4K one with the same proportions.
"""

import pygame

from game.constants import (
    DIFFICULTY_EASY,
    DIFFICULTY_MEDIUM,
    DIFFICULTY_HARD,
    DIFFICULTY_EXPERT,
    DIFFICULTY_ORDER,
    HAIRLINE,
    HAIRLINE_DIM,
    MODE_CAMPAIGN,
    MODE_COMPETITION,
    MODE_ENDLESS,
    MODE_WARMUP,
    NEON_CYAN,
    NEON_GREEN,
    NEON_ORANGE,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    SURFACE_RAISED,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.audio_manager import SFX_MENU_MOVE, SFX_MENU_SELECT
from game.display import toggle_fullscreen
from game.ui import UI, Stage, pulse


# Label, action, and the one-line description shown beside the selection.
_MENU_ITEMS = [
    ("CAMPAIGN",    MODE_CAMPAIGN,    "10 waves · clear them all"),
    ("ENDLESS",     MODE_ENDLESS,     "boss every 20 kills"),
    ("COMPETITION", MODE_COMPETITION, "scored on its own board"),
    ("WARMUP",      MODE_WARMUP,      "30s practice · not scored"),
    ("LEADERBOARD", "leaderboard",    "local high scores"),
    ("SETTINGS",    "settings",       "resolution, audio, effects"),
    ("EXIT",        "exit",           "quit to desktop"),
]
_EXIT_REQUESTED = object()

# Accent per row.
_ITEM_COLOURS = (
    NEON_CYAN,
    NEON_GREEN,
    NEON_YELLOW,
    NEON_ORANGE,
    NEON_CYAN,
    NEON_CYAN,
    (150, 150, 170),
)

# Accent per difficulty level.
_DIFF_COLOURS = {
    DIFFICULTY_EASY:   NEON_GREEN,
    DIFFICULTY_MEDIUM: NEON_CYAN,
    DIFFICULTY_HARD:   NEON_ORANGE,
    DIFFICULTY_EXPERT: NEON_RED,
}

# What fraction of the row's inner width is reserved for the label column.
# The rest (right of this split) is the blurb column.
_LABEL_SPLIT = 0.52


class MainMenuScreen:
    def __init__(
        self,
        screen: pygame.Surface,
        settings,
        assets,
        audio,
        leaderboard,
    ) -> None:
        self._screen   = screen
        self._settings = settings
        self._assets   = assets
        self._audio    = audio
        self._leaderboard = leaderboard

        self._selected   = 0
        self._tick       = 0.0
        self._diff_index = DIFFICULTY_ORDER.index(DIFFICULTY_MEDIUM)
        self._warmth     = [0.0] * len(_MENU_ITEMS)

        self._rebuild(screen)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui    = UI(self._assets, width, height)
        self._stage = Stage(
            self._ui, star_count=200, horizon_fraction=0.62, horizon_rule=False
        )

    def set_surface(self, screen: pygame.Surface) -> None:
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        self.set_surface(toggle_fullscreen(self._settings))

    # ── Event loop ────────────────────────────────────────────────────────────

    def run(self, clock: pygame.time.Clock):
        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self._toggle_fullscreen()
                        continue
                    result = self._handle_key(event.key)
                    if result is _EXIT_REQUESTED:
                        return None
                    if result is not None:
                        return result

            self._update(dt)
            self._draw()
            pygame.display.flip()

    def _handle_key(self, key: int):
        if key in (pygame.K_UP, pygame.K_w):
            self._selected = (self._selected - 1) % len(_MENU_ITEMS)
            self._audio.play(SFX_MENU_MOVE)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self._selected = (self._selected + 1) % len(_MENU_ITEMS)
            self._audio.play(SFX_MENU_MOVE)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self._audio.play(SFX_MENU_SELECT)
            return self._activate(_MENU_ITEMS[self._selected][1])
        elif key == pygame.K_ESCAPE:
            return _EXIT_REQUESTED
        elif key == pygame.K_1:
            self._diff_index = 0
            self._audio.play(SFX_MENU_MOVE)
        elif key == pygame.K_2:
            self._diff_index = 1
            self._audio.play(SFX_MENU_MOVE)
        elif key == pygame.K_3:
            self._diff_index = 2
            self._audio.play(SFX_MENU_MOVE)
        elif key == pygame.K_4:
            self._diff_index = 3
            self._audio.play(SFX_MENU_MOVE)
        elif key == pygame.K_TAB:
            self._diff_index = (self._diff_index + 1) % len(DIFFICULTY_ORDER)
            self._audio.play(SFX_MENU_MOVE)
        return None

    def _activate(self, action: str):
        if action == "exit":
            return _EXIT_REQUESTED
        if action == "leaderboard":
            from screens.leaderboard_screen import LeaderboardScreen
            return LeaderboardScreen(
                self._screen, self._settings, self._assets,
                self._audio, self._leaderboard,
            )
        if action == "settings":
            from screens.settings_screen import SettingsScreen
            return SettingsScreen(
                self._screen, self._settings, self._assets,
                self._audio, self._leaderboard,
            )
        if action in (MODE_CAMPAIGN, MODE_ENDLESS, MODE_COMPETITION, MODE_WARMUP):
            difficulty = DIFFICULTY_ORDER[self._diff_index]
            if action == MODE_COMPETITION:
                from screens.name_input_screen import NameInputScreen
                return NameInputScreen(
                    self._screen, self._settings, self._assets,
                    self._audio, self._leaderboard, action,
                    difficulty=difficulty,
                )
            from screens.game_screen import GameScreen
            return GameScreen(
                self._screen, self._settings, self._assets,
                self._audio, self._leaderboard, action,
                player_name="PLAYER", difficulty=difficulty,
            )
        return None

    def _update(self, dt: float) -> None:
        step = max(0.0, dt)
        self._stage.update(step)
        for index in range(len(self._warmth)):
            target = 1.0 if index == self._selected else 0.0
            self._warmth[index] += (target - self._warmth[index]) * min(1.0, step * 12)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)
        self._draw_title()
        self._draw_menu()
        self._draw_footer()

    # ── Title ─────────────────────────────────────────────────────────────────

    def _draw_title(self) -> None:
        ui = self._ui
        cx    = ui.width // 2
        beat  = pulse(self._tick, 1.6)
        warm  = (
            int(120 + 90 * beat),
            int(210 + 45 * beat),
            255,
        )
        title_top = max(ui.px(36), int(ui.height * 0.10))
        rect = ui.text(
            self._screen, "CODETYPE", 64, warm, cx, title_top,
            bold=True, anchor="midtop", glow=NEON_CYAN,
        )
        rule_y = rect.bottom + ui.px(14)
        half   = min(ui.width // 2 - ui.px(20), rect.width // 2 + ui.px(60))
        ui.divider(self._screen, cx - half, cx + half, rule_y, HAIRLINE_DIM)
        core   = max(ui.px(40), int(half * 0.28))
        ui.divider(self._screen, cx - core, cx + core, rule_y, NEON_CYAN, 240)
        ui.text(
            self._screen,
            "PROGRAMMING TYPING GAME",
            14, TEXT_DIM, cx, rule_y + ui.px(14), anchor="midtop",
        )

    # ── Difficulty strip ──────────────────────────────────────────────────────

    def _draw_difficulty_strip(
        self,
        panel: pygame.Rect,
        top: int,
        strip_h: int,
        pad: int,
    ) -> None:
        """Four equal-width difficulty buttons spanning the panel's inner width."""
        ui    = self._ui
        gap_x = ui.px(5)
        left  = panel.x + pad
        right = panel.right - pad
        count = len(DIFFICULTY_ORDER)
        # Distribute width evenly; remainder goes to the last cell.
        total_gap = gap_x * (count - 1)
        cell      = (right - left - total_gap) // count
        active    = DIFFICULTY_ORDER[self._diff_index]

        for i, diff in enumerate(DIFFICULTY_ORDER):
            colour    = _DIFF_COLOURS[diff]
            is_active = diff == active
            x         = left + i * (cell + gap_x)
            # Last cell gets any leftover pixels so the strip reaches the right edge.
            w = cell if i < count - 1 else right - x
            btn = pygame.Rect(x, top, w, strip_h)

            # Fill
            bg = pygame.Surface(btn.size, pygame.SRCALPHA)
            bg.fill((*colour, 36) if is_active else (*SURFACE_RAISED, 180))
            self._screen.blit(bg, btn.topleft)

            # Border
            border_col = colour if is_active else HAIRLINE_DIM
            pygame.draw.rect(self._screen, border_col, btn, 1,
                             border_radius=ui.px(3))

            # Shortcut digit — top-left corner
            text_col = colour if is_active else TEXT_DIM
            ui.text(
                self._screen, str(i + 1), 8, text_col,
                btn.x + ui.px(5), btn.y + ui.px(4), anchor="topleft",
            )
            # Difficulty label — centred in the button
            ui.text(
                self._screen, diff, 11, text_col,
                btn.centerx, btn.centery, bold=True, anchor="center",
            )

    # ── Menu panel ────────────────────────────────────────────────────────────

    def _draw_menu(self) -> None:
        ui   = self._ui
        cx   = ui.width // 2

        # ── Geometry constants (design space → px) ────────────────────────────
        pad        = ui.px(18)         # uniform left / right inset inside panel
        item_h     = ui.px(50)         # row height
        gap        = ui.px(4)          # gap between rows
        arrow_w    = ui.px(32)         # reserved width for ">>" arrow column
        strip_h    = ui.px(30)         # difficulty button height
        section_h  = ui.px(38)         # "SELECT MODE" label block height
        strip_gap  = ui.px(12)         # space between strip and first row
        note_h     = ui.px(38)         # bottom note block height

        rows_h    = len(_MENU_ITEMS) * item_h + (len(_MENU_ITEMS) - 1) * gap
        panel_h   = section_h + strip_h + strip_gap + rows_h + note_h + ui.px(14)
        panel_w   = min(ui.width - ui.px(56), ui.px(620))

        # Vertical placement: below the title, above the footer chips.
        panel_top = min(
            max(ui.px(108), int(ui.height * 0.29)),
            ui.height - panel_h - ui.px(56),
        )
        panel = pygame.Rect(cx - panel_w // 2, panel_top, panel_w, panel_h)

        selected_colour = _ITEM_COLOURS[self._selected]

        # Panel background
        ui.panel(
            self._screen, panel,
            fill=PANEL_BG, alpha=228, border=HAIRLINE_DIM,
            accent=selected_colour, glow=0.35 + 0.25 * pulse(self._tick, 1.6),
        )

        # ── "SELECT MODE" caption ─────────────────────────────────────────────
        caption_y = panel.y + ui.px(10)
        ui.section_label(
            self._screen, "SELECT MODE", panel.x + pad, caption_y,
        )

        # ── Difficulty strip ──────────────────────────────────────────────────
        strip_y = panel.y + section_h
        self._draw_difficulty_strip(panel, strip_y, strip_h, pad)

        # Divider between strip and rows
        div_y = strip_y + strip_h + ui.px(6)
        ui.divider(
            self._screen, panel.x + pad, panel.right - pad,
            div_y, HAIRLINE_DIM,
        )

        # ── Mode rows ─────────────────────────────────────────────────────────
        rows_y = div_y + ui.px(4)

        # The blurb column starts after the arrow + label column.
        # Split at _LABEL_SPLIT of the inner width so blurb never overlaps label.
        inner_w   = panel_w - pad * 2
        label_col = int(inner_w * _LABEL_SPLIT)  # px the label+arrow occupies
        blurb_x   = panel.x + pad + label_col    # left edge of blurb column

        for i, (label, _action, blurb) in enumerate(_MENU_ITEMS):
            row = pygame.Rect(
                panel.x + pad,
                rows_y + i * (item_h + gap),
                inner_w,
                item_h,
            )
            selected = i == self._selected
            colour   = _ITEM_COLOURS[i] if selected else TEXT_BRIGHT

            # Selection highlight + left rail
            if selected:
                ui.select_row(
                    self._screen, row, selected=True, colour=colour,
                    intensity=self._warmth[i],
                )

            # Arrow: ">>" when selected, blank otherwise
            arrow_str = ">>" if selected else "  "
            ui.text(
                self._screen, arrow_str, 13, colour,
                row.x + ui.px(4), row.centery,
                bold=True, anchor="midleft",
            )

            # Mode label — left-aligned inside the label column, after the arrow
            ui.text(
                self._screen, label, 22, colour,
                row.x + arrow_w, row.centery,
                bold=True, anchor="midleft",
            )

            # Blurb — right-aligned inside the blurb column
            # Colour: dim on unselected rows, accent on the selected one
            w = self._warmth[i]
            blurb_colour = (
                int(TEXT_DIM[0] + (colour[0] - TEXT_DIM[0]) * w),
                int(TEXT_DIM[1] + (colour[1] - TEXT_DIM[1]) * w),
                int(TEXT_DIM[2] + (colour[2] - TEXT_DIM[2]) * w),
            )
            ui.text(
                self._screen, blurb, 12, blurb_colour,
                row.right - ui.px(6), row.centery,
                anchor="midright",
            )

        # ── Bottom note ───────────────────────────────────────────────────────
        note_y = rows_y + rows_h + ui.px(6)
        ui.divider(
            self._screen, panel.x + pad, panel.right - pad,
            note_y, HAIRLINE_DIM,
        )
        sel_label, _, sel_blurb = _MENU_ITEMS[self._selected]
        ui.text(
            self._screen, f"{sel_label}  —  {sel_blurb}", 12, TEXT_DIM,
            panel.centerx, note_y + ui.px(10), anchor="midtop",
        )

    # ── Footer ────────────────────────────────────────────────────────────────

    def _draw_footer(self) -> None:
        ui = self._ui
        y  = ui.height - ui.px(34)
        ui.chips(
            self._screen,
            [
                ("↑ ↓",  "NAVIGATE"),
                ("ENTER", "SELECT"),
                ("1 – 4", "DIFFICULTY"),
                ("TAB",   "CYCLE DIFF"),
                ("ESC",   "QUIT"),
            ],
            y,
        )
        ui.text(
            self._screen, "WASD ALSO WORKS", 11, TEXT_DIM,
            ui.width - ui.px(18), y, anchor="midright",
        )