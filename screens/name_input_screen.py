"""Name entry for competition mode."""

from __future__ import annotations

import pygame

from game.constants import (
    HAIRLINE_DIM,
    NEON_CYAN,
    NEON_PINK,
    PANEL_BG,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.audio_manager import SFX_MENU_SELECT
from game.display import toggle_fullscreen
from game.ui import UI, Stage, pulse


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
    ):
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._mode = mode
        self._difficulty = difficulty
        self._name = ""
        self._max_length = 32
        self._tick = 0.0
        self._rebuild(screen)

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
            )
        if event.key == pygame.K_BACKSPACE:
            self._name = self._name[:-1]
            return None
        character = getattr(event, "unicode", "")
        if isinstance(character, str) and len(character) == 1:
            if ord(character) >= 32 and len(self._name) < self._max_length:
                self._name += character
        return None

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            # The window was resized under us; rebuild for the new size.
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)

        box = ui.centre_panel(560, 300)
        ui.panel(
            self._screen, box,
            fill=PANEL_BG, alpha=238, border=HAIRLINE_DIM,
            accent=NEON_CYAN, glow=0.3 + 0.2 * pulse(self._tick, 1.5),
        )
        ui.text(
            self._screen, "ENTER PLAYER NAME", 30, TEXT_BRIGHT, box.centerx,
            box.y + ui.px(30), bold=True, anchor="midtop", glow=NEON_CYAN,
        )
        ui.text(
            self._screen, f"MODE   //   {self._mode.upper()}", 13, TEXT_DIM,
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
        # A full-length glow is the focus cue: there is only one field, so the
        # whole panel should read as "type here".
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

        # Length meter: a hairline that fills as the name approaches the cap.
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
