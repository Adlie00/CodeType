"""
AssetManager — centralises font and image loading.
Falls back gracefully if custom assets are missing.
"""

import os
import pygame
from game.constants import FONTS_DIR, IMAGES_DIR


# pygame.font.Font takes no bold= argument, so weight has to come from a real
# bold face: prefer the matching file, then the bold sibling of whatever was
# found (Windows ships cour.ttf / courbd.ttf side by side).
_FONT_FILES = (("JetBrainsMono-Regular.ttf", "JetBrainsMono-Bold.ttf"),
               ("ShareTechMono-Regular.ttf", "ShareTechMono-Bold.ttf"),
               ("Courier.ttf", "courbd.ttf"),
               ("cour.ttf", "courbd.ttf"))


def _bold_sibling(path: str) -> str | None:
    stem, ext = os.path.splitext(path)
    name = f"{stem[:-len('regular')]}bold{ext}" if stem.lower().endswith("regular") else f"{stem}bd{ext}"
    return name if os.path.exists(name) else None


class AssetManager:
    def __init__(self) -> None:
        self._fonts: dict[tuple, pygame.font.Font] = {}
        self._images: dict[str, pygame.Surface] = {}

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = self._load_font(size, bold)
        return self._fonts[key]

    def _load_font(self, size: int, bold: bool) -> pygame.font.Font:
        for regular, heavy in _FONT_FILES:
            path = os.path.join(FONTS_DIR, heavy if bold else regular)
            if os.path.exists(path):
                try:
                    return pygame.font.Font(path, size)
                except Exception:
                    pass
        mono = pygame.font.match_font("couriernew,courier,mono,freemono,consolas")
        if mono:
            sibling = _bold_sibling(mono) if bold else None
            if sibling:
                return pygame.font.Font(sibling, size)
            font = pygame.font.Font(mono, size)
            font.set_bold(bold)  # TrueType faces have no bold variant: this is near enough
            return font
        return pygame.font.SysFont("monospace", size, bold=bold)

    def image(self, name: str) -> pygame.Surface | None:
        if name in self._images:
            return self._images[name]
        path = os.path.join(IMAGES_DIR, name)
        if not os.path.exists(path):
            return None
        try:
            surf = pygame.image.load(path).convert_alpha()
            self._images[name] = surf
            return surf
        except Exception:
            return None