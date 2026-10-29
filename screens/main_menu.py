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
    HAIRLINE_DIM,
    MODE_ARCADE,
    MODE_CAMPAIGN,
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
    ("ARCADE",      MODE_ARCADE,      "2 min · kills add time"),
    ("COMPETITION", MODE_COMPETITION, "5 waves · team tournament"),
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
    NEON_PINK,
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
        self._title_bottom = 0   # measured when the title block is drawn

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
        if action in (
            MODE_CAMPAIGN,
            MODE_ENDLESS,
            MODE_ARCADE,
            MODE_COMPETITION,
            MODE_WARMUP,
        ):
            difficulty = DIFFICULTY_ORDER[self._diff_index]
            if action == MODE_COMPETITION:
                # Competition owns a team tournament hub rather than a single
                # player name: it sets up the five teams and tracks the bracket.
                from screens.competition_screen import CompetitionScreen
                return CompetitionScreen(
                    self._screen, self._settings, self._assets,
                    self._audio, self._leaderboard,
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
        ui.diamond(self._screen, cx - half - ui.px(8), rule_y, NEON_CYAN)
        ui.diamond(self._screen, cx + half + ui.px(8), rule_y, NEON_CYAN)
        # A bright spark travels along the rule so the title block feels alive.
        travel = (self._tick * 0.35) % 1.0
        spark_x = int(cx - half + (2 * half) * travel)
        ui.divider(self._screen, spark_x - ui.px(18), spark_x + ui.px(18), rule_y, TEXT_BRIGHT, 200)
        caption = ui.text(
            self._screen,
            "PROGRAMMING TYPING GAME",
            15, TEXT_BRIGHT, cx, rule_y + ui.px(14),
            anchor="midtop", glow=NEON_CYAN,
        )
        # Remember where the title block ends so the menu panel can stay below
        # it (the block's height depends on the real font).
        self._title_bottom = caption.bottom

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
                self._screen, str(i + 1), 10, text_col,
                btn.x + ui.px(6), btn.centery, anchor="midleft",
            )
            # Difficulty label — centred in the button
            ui.text(
                self._screen, diff, 12, text_col,
                btn.centerx + ui.px(6), btn.centery, bold=True, anchor="center",
            )
            if is_active:
                pygame.draw.rect(
                    self._screen, colour,
                    pygame.Rect(btn.x + ui.px(6), btn.bottom - ui.px(3),
                                btn.width - ui.px(12), max(2, ui.px(2))),
                    border_radius=1,
                )

    # ── Menu panel ────────────────────────────────────────────────────────────

    def _draw_menu(self) -> None:
        ui   = self._ui
        cx   = ui.width // 2

        # ── Geometry constants (design space → px) ────────────────────────────
        pad        = ui.px(18)         # uniform left / right inset inside panel
        gap        = ui.px(4)          # gap between rows
        arrow_w    = ui.px(32)         # reserved width for ">>" arrow column
        strip_h    = ui.px(30)         # difficulty button height
        section_h  = ui.px(38)         # "SELECT MODE" label block height
        strip_gap  = ui.px(12)         # space between strip and first row
        note_h     = ui.px(38)         # bottom note block height

        count     = len(_MENU_ITEMS)
        fixed_h   = section_h + strip_h + strip_gap + note_h + ui.px(14)
        panel_w   = min(ui.width - ui.px(56), ui.px(620))

        # Vertical placement: below the title, above the footer chips. The title
        # block's height depends on the real font, so it is measured as it is
        # drawn; reserve room for it and shorten the rows if the panel would
        # otherwise ride up and cover the caption.
        top_floor    = self._title_bottom + ui.px(16)
        bottom_limit = ui.height - ui.px(56)

        item_h    = ui.px(50)
        available = bottom_limit - top_floor
        if fixed_h + count * item_h + (count - 1) * gap > available:
            free   = available - fixed_h - (count - 1) * gap
            item_h = max(ui.px(34), free // count)

        rows_h  = count * item_h + (count - 1) * gap
        panel_h = fixed_h + rows_h

        panel_top = min(
            max(ui.px(108), int(ui.height * 0.29)),
            bottom_limit - panel_h,
        )
        panel_top = max(panel_top, top_floor)
        panel = pygame.Rect(cx - panel_w // 2, panel_top, panel_w, panel_h)

        # Panel background
        ui.panel(
            self._screen, panel,
            fill=PANEL_BG, alpha=228, border=HAIRLINE_DIM,
            glow=0.35 + 0.25 * pulse(self._tick, 1.6),
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

        # The blurb is right-aligned inside each row, keeping it clear of the
        # arrow + label column at the left.
        inner_w   = panel_w - pad * 2

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

            warm = self._warmth[i]

            # Faint separator under every row but the last, and not beside the
            # selected one, whose wash already marks its edges.
            if i < count - 1 and not selected and self._selected != i + 1:
                ui.divider(
                    self._screen, row.x + arrow_w, row.right - ui.px(6),
                    row.bottom + gap // 2, HAIRLINE_DIM, 90,
                )

            # Chevron eases in and out with the selection.
            if warm > 0.05:
                ui.chevron(
                    self._screen, row.x + ui.px(10) + int(ui.px(4) * warm),
                    row.centery, colour, size=5,
                )

            # Mode label — nudged right as the row warms up.
            ui.text(
                self._screen, label, 22, colour,
                row.x + arrow_w + int(ui.px(6) * warm), row.centery,
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