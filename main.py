"""
CODETYPE — Programming Typing Game

Entry point. Initialises Pygame, opens the display, loads settings, and
launches the game loop.

The display is opened through ``game.display`` rather than inline so the
fullscreen policy lives in one place: fullscreen is borderless at the monitor's
own resolution, and a remembered window size is clamped to the desktop. The UI
scales itself to whatever surface it gets — see ``game/ui.py``.
"""

import sys

import pygame

from game.settings import Settings
from game.asset_manager import AssetManager
from game.audio_manager import AudioManager
from game.display import DisplayError, clamp_window_size, create_display
from game.leaderboard import Leaderboard
from screens.main_menu import MainMenuScreen


def main() -> None:
    pygame.init()
    try:
        pygame.mixer.init()
    except pygame.error:
        pass

    settings = Settings()

    # A stored size that no longer fits the monitor would be clamped by the
    # window manager anyway; doing it here keeps settings.json honest.
    width, height = clamp_window_size(settings.width, settings.height)
    if (width, height) != (settings.width, settings.height):
        settings.width = width
        settings.height = height
        settings.save()

    try:
        screen = create_display(settings)
    except DisplayError as exc:
        print(f"CODETYPE: {exc}")
        pygame.quit()
        sys.exit(1)
    pygame.display.set_caption("CODETYPE — Programming Typing Game")

    clock = pygame.time.Clock()

    assets = AssetManager()
    audio = AudioManager(settings)
    leaderboard = Leaderboard()

    try:
        current_screen = MainMenuScreen(screen, settings, assets, audio, leaderboard)
        while current_screen is not None:
            current_screen = current_screen.run(clock)
    finally:
        leaderboard.close()
        pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
