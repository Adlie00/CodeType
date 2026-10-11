"""
Settings — loads from data/settings.json, saves back on change.
"""

import json
import os

from game.constants import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    MAX_WINDOW_HEIGHT,
    MAX_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    SETTINGS_FILE,
)


_DEFAULTS: dict = {
    "width":            DEFAULT_WIDTH,
    "height":           DEFAULT_HEIGHT,
    "fullscreen":       False,
    "master_volume":    0.8,
    "music_volume":     0.5,
    "sfx_volume":       0.8,
    "typing_effects":   True,
    "screen_shake":     True,
}


class Settings:
    def __init__(self) -> None:
        self._data: dict = dict(_DEFAULTS)
        self._load()

    @property
    def width(self) -> int:
        return self._data["width"]

    @width.setter
    def width(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < MIN_WINDOW_WIDTH:
            raise ValueError(f"width must be an integer of at least {MIN_WINDOW_WIDTH}")
        self._data["width"] = min(value, MAX_WINDOW_WIDTH)

    @property
    def height(self) -> int:
        return self._data["height"]

    @height.setter
    def height(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < MIN_WINDOW_HEIGHT:
            raise ValueError(f"height must be an integer of at least {MIN_WINDOW_HEIGHT}")
        self._data["height"] = min(value, MAX_WINDOW_HEIGHT)

    @property
    def fullscreen(self) -> bool:
        return self._data["fullscreen"]

    @fullscreen.setter
    def fullscreen(self, value: bool) -> None:
        self._data["fullscreen"] = value

    @property
    def master_volume(self) -> float:
        return self._data["master_volume"]

    @master_volume.setter
    def master_volume(self, value: float) -> None:
        self._data["master_volume"] = max(0.0, min(1.0, value))

    @property
    def music_volume(self) -> float:
        return self._data["music_volume"]

    @music_volume.setter
    def music_volume(self, value: float) -> None:
        self._data["music_volume"] = max(0.0, min(1.0, value))

    @property
    def sfx_volume(self) -> float:
        return self._data["sfx_volume"]

    @sfx_volume.setter
    def sfx_volume(self, value: float) -> None:
        self._data["sfx_volume"] = max(0.0, min(1.0, value))

    @property
    def typing_effects(self) -> bool:
        return self._data["typing_effects"]

    @typing_effects.setter
    def typing_effects(self, value: bool) -> None:
        self._data["typing_effects"] = value

    @property
    def screen_shake(self) -> bool:
        return self._data["screen_shake"]

    @screen_shake.setter
    def screen_shake(self, value: bool) -> None:
        self._data["screen_shake"] = value

    def _load(self) -> None:
        if not os.path.exists(SETTINGS_FILE):
            self.save()
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key in _DEFAULTS:
                if key in saved:
                    self._data[key] = saved[key]
        except (json.JSONDecodeError, OSError):
            return
        # A hand-edited or stale file can hold a size no desktop can honour, so
        # re-run it through the setters rather than trusting the raw values.
        self._sanitise()

    def _sanitise(self) -> None:
        for axis in ("width", "height"):
            try:
                setattr(self, axis, self._data[axis])
            except (TypeError, ValueError):
                self._data[axis] = _DEFAULTS[axis]
        for axis in ("master_volume", "music_volume", "sfx_volume"):
            try:
                setattr(self, axis, float(self._data[axis]))
            except (TypeError, ValueError):
                self._data[axis] = _DEFAULTS[axis]
        for axis in ("fullscreen", "typing_effects", "screen_shake"):
            self._data[axis] = bool(self._data[axis])

    def save(self) -> None:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
