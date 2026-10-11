"""
Display management — creates the game surface and owns the fullscreen policy.

Fullscreen is *borderless*: a ``(0, 0)`` surface with ``pygame.FULLSCREEN``
resolves to the current desktop resolution, which SDL gives us without a title
bar or border. The user still gets a real window when fullscreen is off, and
the settings screen can switch between the two at runtime.

``pygame.SCALED`` is deliberately not used. It needs a hardware renderer that is
not guaranteed to exist on every machine (it fails outright on some Windows
installs), and the UI already scales itself — see ``game/ui.py``.

Because the interface is authored against a fixed design resolution and scaled
uniformly (see ``game/constants.py``), the surface is free to be any size. That
is what lets fullscreen simply adopt the monitor's own resolution instead of
letterboxing a remembered window size.
"""

from __future__ import annotations

import pygame

from game.constants import (
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    WINDOW_PRESETS,
)


class DisplayError(RuntimeError):
    """Raised when no usable display mode could be created."""


def desktop_size(index: int = 0) -> tuple[int, int]:
    """Resolution of the attached monitor, or ``(0, 0)`` when unknown."""
    try:
        sizes = pygame.display.get_desktop_sizes()
    except (pygame.error, AttributeError):
        return (0, 0)
    if not sizes:
        return (0, 0)
    return tuple(sizes[min(max(0, index), len(sizes) - 1)])  # type: ignore[return-value]


def target_size(settings: object) -> tuple[int, int]:
    """The surface size the current settings ask for.

    Fullscreen ignores the stored window size entirely: the display is the
    monitor, and a remembered 1280x720 would otherwise letterbox a 1080p panel.
    """
    if getattr(settings, "fullscreen", False):
        size = desktop_size()
        if size[0] and size[1]:
            return size
    return (int(getattr(settings, "width", 0)), int(getattr(settings, "height", 0)))


def describe_size(settings: object) -> str:
    """Human-readable size for the settings screen."""
    if getattr(settings, "fullscreen", False):
        width, height = target_size(settings)
        return f"NATIVE {width}x{height}"
    return f"{int(getattr(settings, 'width', 0))}x{int(getattr(settings, 'height', 0))}"


def clamp_window_size(width: int, height: int) -> tuple[int, int]:
    """Pull a window size into the range a desktop can actually honour.

    Two ceilings matter. The desktop is a hard one — a window larger than the
    monitor is either rejected or silently clamped by the window manager, and
    either way the remembered size stops meaning what it says. The absolute
    bounds are a soft one, for the case where the desktop cannot be queried.
    """
    width = int(width)
    height = int(height)
    native = desktop_size()
    if native[0] and native[1]:
        width = min(width, native[0])
        height = min(height, native[1])
    width = max(MIN_WINDOW_WIDTH, min(MAX_WINDOW_WIDTH, width))
    height = max(MIN_WINDOW_HEIGHT, min(MAX_WINDOW_HEIGHT, height))
    return width, height


def available_presets() -> tuple[tuple[int, int], ...]:
    """Windowed presets that fit on this machine, smallest first.

    A 4K-only machine still gets the 720p and 900p options, and a laptop never
    gets offered a 1440p window it cannot show.
    """
    native = desktop_size()
    presets = [
        (w, h)
        for w, h in WINDOW_PRESETS
        if not native[0] or (w <= native[0] and h <= native[1])
    ]
    return tuple(presets) or (WINDOW_PRESETS[0],)


def create_display(settings: object) -> pygame.Surface:
    """Create (or recreate) the game surface from ``settings``.

    Raises :class:`DisplayError` if even a plain window cannot be opened, so
    callers can report the failure instead of crashing inside pygame.
    """
    fullscreen = bool(getattr(settings, "fullscreen", False))
    width = int(getattr(settings, "width", 0))
    height = int(getattr(settings, "height", 0))

    attempts: list[tuple[tuple[int, int], int]] = []
    if fullscreen:
        native = desktop_size()
        # (0, 0) lets pygame pick the desktop size itself, which is the most
        # reliable route to a borderless fullscreen display.
        attempts.append(((0, 0), pygame.FULLSCREEN))
        if native[0] and native[1]:
            attempts.append((native, pygame.FULLSCREEN))
    if width > 0 and height > 0:
        attempts.append(((width, height), 0))
        # Last resort: the desktop itself, so a bad remembered size can never
        # stop the game from starting.
        native = desktop_size()
        if native[0] and native[1]:
            attempts.append((native, 0))

    for size, flags in attempts:
        try:
            return pygame.display.set_mode(size, flags)
        except pygame.error:
            continue

    raise DisplayError("No usable display mode; try a different resolution.")


def toggle_fullscreen(settings: object) -> pygame.Surface:
    """Flip the fullscreen flag and rebuild the display, rolling back on failure.

    Leaving fullscreen returns to the stored window size rather than to whatever
    the fullscreen surface happened to be, so toggling in and out does not
    quietly rewrite the window the user chose.
    """
    previous = bool(getattr(settings, "fullscreen", False))
    settings.fullscreen = not previous  # type: ignore[attr-defined]
    try:
        return create_display(settings)
    except DisplayError:
        settings.fullscreen = previous  # type: ignore[attr-defined]
        return create_display(settings)
