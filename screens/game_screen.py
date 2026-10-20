"""Interactive gameplay screen for CODETYPE.

The screen is a thin shell: it owns the run loop and forwards events to
``Game``, which draws itself. The only thing drawn here is the content-error
state, which is a normal screen so it gets the same chrome as everything else.
"""

from __future__ import annotations

import sqlite3

import pygame

from game.constants import (
    HAIRLINE_DIM,
    MODE_ARCADE,
    MODE_ENDLESS,
    NEON_RED,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.content import ContentError
from game.display import toggle_fullscreen
from game.game import Game
from game.ui import UI, Stage


class GameScreen:
    def __init__(
        self,
        screen: pygame.Surface,
        settings,
        assets,
        audio,
        leaderboard,
        mode: str,
        player_name: str = "PLAYER",
        difficulty: str | None = None,
    ) -> None:
        self._screen = screen
        self._assets = assets
        self._settings = settings
        self._audio = audio
        self._leaderboard = leaderboard
        self._mode = mode
        self._player_name = player_name
        self._tick = 0.0
        self._game: Game | None = None
        self._error: str | None = None

        self._rebuild(screen)
        try:
            self._game = Game(
                screen=screen,
                settings=settings,
                assets=assets,
                audio=audio,
                mode=mode,
                player_name=player_name,
                difficulty=difficulty,
                leaderboard=leaderboard,
            )
        except (ContentError, OSError, ValueError) as exc:
            self._error = str(exc)

    def _rebuild(self, screen: pygame.Surface) -> None:
        """Re-derive the chrome used by the content-error state.

        The live game owns its own UI and re-layouts itself every frame, but the
        error state is drawn here, so it needs a UI of its own for the surface it
        is currently on.
        """
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=90, horizon_fraction=0.5, scroll=12.0)

    def set_surface(self, screen: pygame.Surface) -> None:
        """Adopt a new surface after a display-mode change.

        The live game re-derives its own layout from whatever surface it is
        handed on the next draw, so it only needs telling about the swap.
        """
        self._screen = screen
        if self._game is not None:
            self._game.set_surface(screen)
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        """F11: borderless fullscreen, without the F11 becoming a typed key."""
        self.set_surface(toggle_fullscreen(self._settings))

    def run(self, clock: pygame.time.Clock):
        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                # Checked before the game sees the event, or F11 would be typed
                # into the snippet the player is in the middle of.
                if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue
                if self._game is not None:
                    self._game.handle_event(event)
                elif event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_ESCAPE,
                    pygame.K_m,
                ):
                    return self._to_menu()

            if self._error is not None:
                self._stage.update(dt)
                self._draw_error()
            else:
                self._game.update(dt)
                self._game.draw(self._screen)
                if self._game.return_to_menu:
                    if self._mode in (MODE_ENDLESS, MODE_ARCADE):
                        # Neither endless nor arcade ever ends on its own short
                        # of the clock, so quitting is the only way to bank an
                        # unfinished run: record it before heading back.
                        self._save_run()
                    return self._to_menu()
                if self._game.finished:
                    from screens.game_over_screen import GameOverScreen

                    return GameOverScreen(
                        self._screen,
                        self._settings,
                        self._assets,
                        self._audio,
                        self._leaderboard,
                        self._game.stats(),
                    )
            pygame.display.flip()

    def _save_run(self) -> None:
        """Bank an abandoned run's score, mirroring the game-over save."""
        if self._leaderboard is None or self._game is None:
            return
        stats = self._game.stats()
        try:
            self._leaderboard.save_score(
                player_name=str(stats.get("player_name", "PLAYER")),
                score=int(stats.get("score", 0)),
                wpm=float(stats.get("wpm", 0.0)),
                accuracy=float(stats.get("accuracy", 0.0)),
                max_combo=int(stats.get("max_combo", 0)),
                waves=int(stats.get("waves", 0)),
                enemies=int(stats.get("enemies", 0)),
                mode=str(stats.get("mode", "campaign")),
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            pass

    def _to_menu(self):
        from screens.main_menu import MainMenuScreen

        return MainMenuScreen(
            self._screen,
            self._settings,
            self._assets,
            self._audio,
            self._leaderboard,
        )

    def _draw_error(self) -> None:
        if self._stage.stale(self._screen):
            # The window was resized under us; rebuild for the new size.
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)

        box = ui.centre_panel(620, 300)
        ui.panel(
            self._screen, box,
            fill=(12, 12, 32), alpha=242, border=HAIRLINE_DIM,
            accent=NEON_RED, glow=0.6,
        )
        ui.heading(
            self._screen, "CONTENT ERROR", box.centerx, box.y + ui.px(32),
            size=32, colour=NEON_RED, glow=NEON_RED,
        )
        for index, line in enumerate(ui.wrap(self._error or "", 14, box.width - ui.px(70))[:6]):
            ui.text(
                self._screen, line, 14, TEXT_BRIGHT, box.centerx,
                box.y + ui.px(104) + index * ui.px(24), anchor="midtop",
            )
        ui.text(
            self._screen,
            "The snippet library could not be read. Check that data/languages/ "
            "sits beside the executable, then restart.",
            12, TEXT_DIM, box.centerx, box.bottom - ui.px(66),
            anchor="midtop",
        )
        ui.chips(
            self._screen, [("ESC", "MAIN MENU")], box.bottom - ui.px(28)
        )
