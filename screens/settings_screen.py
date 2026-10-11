"""Settings screen — resolution, audio, and effect toggles.

This screen is the one that can change the surface out from under itself, so it
rebuilds its ``UI``/``Stage`` after every successful display change rather than
assuming a fixed size.
"""

from __future__ import annotations

import pygame

from game.constants import (
    GREY,
    HAIRLINE_DIM,
    NEON_CYAN,
    NEON_GREEN,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.display import (
    DisplayError,
    available_presets,
    create_display,
    describe_size,
    toggle_fullscreen,
)
from game.ui import UI, Stage, pulse


# Rows are grouped so the screen reads as three short forms rather than one
# undifferentiated list.
_GROUPS = (
    ("DISPLAY", ("resolution", "fullscreen")),
    ("AUDIO", ("master_volume", "music_volume", "sfx_volume")),
    ("FEEL", ("typing_effects", "screen_shake")),
)

_LABELS = {
    "resolution": "WINDOW SIZE",
    "fullscreen": "BORDERLESS FULLSCREEN",
    "master_volume": "MASTER VOLUME",
    "music_volume": "MUSIC VOLUME",
    "sfx_volume": "SFX VOLUME",
    "typing_effects": "TYPING EFFECTS",
    "screen_shake": "SCREEN SHAKE",
}

_HINTS = {
    "resolution": "LEFT / RIGHT CHANGE",
    "fullscreen": "ENTER TOGGLE",
    "master_volume": "LEFT / RIGHT CHANGE",
    "music_volume": "LEFT / RIGHT CHANGE",
    "sfx_volume": "LEFT / RIGHT CHANGE",
    "typing_effects": "ENTER TOGGLE",
    "screen_shake": "ENTER TOGGLE",
}

_VOLUMES = ("master_volume", "music_volume", "sfx_volume")
_TOGGLES = ("typing_effects", "screen_shake")


def _flatten(groups) -> tuple[str, ...]:
    return tuple(item for _title, items in groups for item in items)


class SettingsScreen:
    _items = _flatten(_GROUPS)

    def __init__(self, screen, settings, assets, audio, leaderboard=None):
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._selected = 0
        self._error = ""
        self._notice = ""
        self._notice_timer = 0.0
        self._tick = 0.0
        self._rebuild(screen)

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=140, horizon_fraction=0.5, grid=True)
        self._presets = available_presets()

    def run(self, clock: pygame.time.Clock):
        from screens.main_menu import MainMenuScreen

        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt
            self._notice_timer = max(0.0, self._notice_timer - dt)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._settings.save()
                    return None
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue
                if event.key == pygame.K_ESCAPE:
                    self._settings.save()
                    return MainMenuScreen(
                        self._screen,
                        self._settings,
                        self._assets,
                        self._audio,
                        self._leaderboard,
                    )
                if event.key in (pygame.K_UP, pygame.K_w):
                    self._selected = (self._selected - 1) % len(self._items)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    self._selected = (self._selected + 1) % len(self._items)
                elif event.key in (pygame.K_LEFT, pygame.K_a):
                    self._adjust(-1)
                elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_RETURN):
                    self._adjust(1)
            self._draw()
            pygame.display.flip()

    def _adjust(self, direction: int) -> None:
        item = self._items[self._selected]
        if item == "resolution":
            self._change_resolution(direction)
        elif item == "fullscreen":
            self._change_fullscreen()
        elif item in _VOLUMES:
            setattr(
                self._settings, item, getattr(self._settings, item) + direction * 0.1
            )
            self._audio.update_volumes()
        else:
            setattr(self._settings, item, not getattr(self._settings, item))
        self._settings.save()

    def _change_resolution(self, direction: int) -> None:
        current = (self._settings.width, self._settings.height)
        if current not in self._presets:
            index = 0
        else:
            index = self._presets.index(current)
        width, height = self._presets[(index + direction) % len(self._presets)]
        self._settings.width = width
        self._settings.height = height
        if self._apply_display():
            self._notice = f"WINDOW  {width}x{height}"
            self._notice_timer = 1.6
        self._settings.save()

    def _change_fullscreen(self) -> None:
        # toggle_fullscreen owns the rollback, so a refused display mode cannot
        # leave the saved setting disagreeing with what is actually on screen.
        try:
            self._screen = toggle_fullscreen(self._settings)
        except DisplayError:
            self._error = "DISPLAY MODE UNAVAILABLE"
            self._settings.save()
            return
        self._rebuild(self._screen)
        self._error = ""
        self._notice = f"FULLSCREEN  {describe_size(self._settings)}"
        self._notice_timer = 1.6
        self._settings.save()

    def set_surface(self, screen: pygame.Surface) -> None:
        """Adopt a new surface after a display-mode change."""
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        """F11: the same toggle the menu offers, without the confirm step."""
        self._change_fullscreen()

    def _apply_display(self) -> bool:
        """Rebuild the surface, rolling the setting back if SDL refuses it."""
        try:
            self._screen = create_display(self._settings)
        except DisplayError:
            self._error = "DISPLAY MODE UNAVAILABLE"
            return False
        self._rebuild(self._screen)
        self._error = ""
        return True

    def _value_text(self, item: str) -> str:
        if item == "resolution":
            return f"{self._settings.width} x {self._settings.height}"
        if item == "fullscreen":
            state = "ON" if self._settings.fullscreen else "OFF"
            # Show what turning it on would actually give you.
            return f"{state}   //   {describe_size(self._settings)}"
        if item in _VOLUMES:
            return f"{int(round(getattr(self._settings, item) * 100))}%"
        return "ON" if getattr(self._settings, item) else "OFF"

    def _ratio(self, item: str) -> float:
        if item in _VOLUMES:
            return max(0.0, min(1.0, float(getattr(self._settings, item))))
        return 1.0 if getattr(self._settings, item) else 0.0

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            # The window was resized under us; rebuild for the new size.
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)
        self._draw_panel()
        self._draw_footer()

    def _draw_panel(self) -> None:
        ui = self._ui
        width = min(ui.width - ui.px(80), ui.px(720))
        top = max(ui.px(40), int(ui.height * 0.10))
        height = min(ui.height - top - ui.px(90), ui.px(560))
        panel = pygame.Rect((ui.width - width) // 2, top, width, height)

        accent = NEON_CYAN if not self._error else NEON_RED
        ui.panel(
            self._screen, panel,
            fill=PANEL_BG, alpha=232, border=HAIRLINE_DIM,
            accent=accent, glow=0.3 + 0.2 * pulse(self._tick, 1.4),
        )
        ui.text(
            self._screen, "SETTINGS", 34, TEXT_BRIGHT, panel.centerx, panel.y + ui.px(26),
            bold=True, anchor="midtop", glow=NEON_CYAN,
        )
        ui.text(
            self._screen, describe_size(self._settings), 13, TEXT_DIM,
            panel.centerx, panel.y + ui.px(70), anchor="midtop",
        )

        cursor = panel.y + ui.px(100)
        item_index = 0
        for group_index, (title, items) in enumerate(_GROUPS):
            if group_index:
                ui.divider(
                    self._screen, panel.x + ui.px(28), panel.right - ui.px(28),
                    cursor - ui.px(8), HAIRLINE_DIM,
                )
            ui.section_label(
                self._screen, title, panel.x + ui.px(28), cursor + ui.px(10)
            )
            cursor += ui.px(28)
            for item in items:
                cursor = self._draw_row(
                    panel, item, cursor, item_index == self._selected
                )
                item_index += 1

    def _draw_row(
        self, panel: pygame.Rect, item: str, top: int, selected: bool
    ) -> int:
        ui = self._ui
        row_height = max(30, ui.px(40))
        row = pygame.Rect(
            panel.x + ui.px(16), top, panel.width - ui.px(32), row_height
        )
        colour = NEON_CYAN if selected else TEXT_BRIGHT
        if selected:
            ui.select_row(self._screen, row, selected=True, colour=NEON_CYAN)

        label_x = row.x + ui.px(18)
        value_x = row.right - ui.px(18)
        value = self._value_text(item)
        width = ui.measure(value, 20, True)[0]

        if item in _VOLUMES:
            # A meter plus a number: the bar is the glanceable part, the
            # percentage is the precise part.
            ui.text(
                self._screen, value, 20, colour if selected else TEXT_BRIGHT,
                value_x, row.centery, bold=True, anchor="midright",
            )
            bar_right = value_x - width - ui.px(18)
            bar = pygame.Rect(
                label_x + ui.px(190),
                row.centery - max(2, ui.px(4)),
                max(10, bar_right - label_x - ui.px(190)),
                max(3, ui.px(7)),
            )
            ratio = self._ratio(item)
            tint = NEON_GREEN if ratio > 0.5 else NEON_YELLOW if ratio > 0.15 else NEON_RED
            ui.meter(self._screen, bar, ratio, tint, track=HAIRLINE_DIM)
        else:
            on = value == "ON" or value.startswith("ON")
            state_colour = (NEON_GREEN if on else GREY) if item in _TOGGLES else colour
            ui.text(
                self._screen, value, 20, state_colour, value_x, row.centery,
                bold=True, anchor="midright",
            )
            if item in _TOGGLES:
                # A pill that is either lit or hollow — the state is legible
                # without reading the word.
                track = pygame.Rect(
                    value_x - width - ui.px(40), row.centery - ui.px(6),
                    ui.px(22), ui.px(12),
                )
                pygame.draw.rect(
                    self._screen,
                    state_colour if on else HAIRLINE_DIM,
                    track, 1, border_radius=track.height // 2,
                )
                knob = pygame.Rect(
                    track.x + (track.width // 2 if on else 0),
                    track.y + ui.px(2),
                    track.width // 2 - ui.px(2),
                    track.height - ui.px(4),
                )
                pygame.draw.rect(
                    self._screen, state_colour, knob,
                    border_radius=knob.height // 2,
                )
                # A pill that is either lit or hollow — the state is legible
                # without reading the word.
                track = pygame.Rect(
                    value_x - width - ui.px(40), row.centery - ui.px(6),
                    ui.px(22), ui.px(12),
                )
                pygame.draw.rect(
                    self._screen,
                    state_colour if on else HAIRLINE_DIM,
                    track, 1, border_radius=track.height // 2,
                )
                knob = pygame.Rect(
                    track.x + (track.width // 2 if on else 0),
                    track.y + ui.px(2),
                    track.width // 2 - ui.px(2),
                    track.height - ui.px(4),
                )
                pygame.draw.rect(
                    self._screen, state_colour, knob,
                    border_radius=knob.height // 2,
                )

        ui.text(
            self._screen, _LABELS[item], 18, colour, label_x, row.centery,
            bold=selected, anchor="midleft",
        )
        if selected:
            ui.text(
                self._screen, _HINTS[item], 11, TEXT_DIM,
                label_x + ui.px(190), row.centery, anchor="midleft",
            )
        return row.bottom + ui.px(6)

    def _draw_footer(self) -> None:
        ui = self._ui
        y = ui.height - ui.px(30)
        if self._error:
            ui.text(
                self._screen, self._error, 13, NEON_RED, ui.width // 2,
                y - ui.px(20), bold=True, anchor="midtop",
            )
        elif self._notice and self._notice_timer > 0:
            ui.text(
                self._screen, self._notice, 13, NEON_GREEN, ui.width // 2,
                y - ui.px(20), bold=True, anchor="midtop",
            )
        ui.chips(
            self._screen,
            [
                ("↑ ↓", "SELECT"),
                ("← →", "CHANGE"),
                ("ESC", "SAVE + BACK"),
            ],
            y,
        )
