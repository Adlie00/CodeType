"""
AudioManager — loads and plays local sound files.
Silently no-ops when a file is missing or mixer is unavailable.

Files are optional: any slot without a matching file in assets/sounds/ is
skipped, so the game runs silently rather than failing.
"""

import os

import pygame

from game.constants import SOUNDS_DIR
from game.settings import Settings


SFX_TYPE_CORRECT = "type_correct"
SFX_TYPE_WRONG   = "type_wrong"
SFX_DESTROY      = "destroy"
SFX_COMBO        = "combo"
SFX_BOSS         = "boss"
SFX_WAVE_CLEAR   = "wave_clear"
SFX_GAME_OVER    = "game_over"
SFX_MENU_SELECT  = "menu_select"
SFX_MENU_MOVE    = "menu_move"

_SOUND_FILES: dict[str, str] = {
    SFX_TYPE_CORRECT: "type_correct.wav",
    SFX_TYPE_WRONG:   "type_wrong.wav",
    SFX_DESTROY:      "destroy.wav",
    SFX_COMBO:        "combo.wav",
    SFX_BOSS:         "boss.wav",
    SFX_WAVE_CLEAR:   "wave_clear.wav",
    SFX_GAME_OVER:    "game_over.wav",
    SFX_MENU_SELECT:  "menu_select.wav",
    SFX_MENU_MOVE:    "menu_move.wav",
}

_MUSIC_FILE = os.path.join(SOUNDS_DIR, "music.ogg")


class AudioManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sounds: dict[str, pygame.mixer.Sound | None] = {}
        self._mixer_ok = pygame.mixer.get_init() is not None
        self._music_playing = False
        self.muted = False

        if self._mixer_ok:
            self._load_sounds()
            self._start_music()

    @property
    def available_slots(self) -> tuple[str, ...]:
        return tuple(slot for slot, sound in self._sounds.items() if sound is not None)

    @property
    def music_playing(self) -> bool:
        return self._music_playing

    def _load_sounds(self) -> None:
        for slot, filename in _SOUND_FILES.items():
            path = os.path.join(SOUNDS_DIR, filename)
            if not os.path.exists(path):
                self._sounds[slot] = None
                continue
            try:
                self._sounds[slot] = pygame.mixer.Sound(path)
            except Exception:
                self._sounds[slot] = None

    def _start_music(self) -> None:
        if not os.path.exists(_MUSIC_FILE):
            return
        try:
            pygame.mixer.music.load(_MUSIC_FILE)
            pygame.mixer.music.set_volume(self._effective_music_volume())
            pygame.mixer.music.play(-1)
            self._music_playing = True
        except Exception:
            self._music_playing = False

    def _effective_music_volume(self) -> float:
        return max(0.0, min(1.0, self._settings.music_volume * self._settings.master_volume))

    def _effective_sfx_volume(self) -> float:
        return max(0.0, min(1.0, self._settings.sfx_volume * self._settings.master_volume))

    def play(self, slot: str) -> None:
        if not self._mixer_ok or self.muted:
            return
        sound = self._sounds.get(slot)
        if sound is None:
            return
        volume = self._effective_sfx_volume()
        if volume <= 0.0:
            return
        sound.set_volume(volume)
        sound.play()

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        if not self._mixer_ok:
            return
        if self.muted:
            pygame.mixer.music.set_volume(0.0)
        else:
            self.set_music_volume(self._settings.music_volume)

    def set_music_volume(self, volume: float) -> None:
        if not self._mixer_ok or not self._music_playing:
            return
        if self.muted:
            return
        try:
            self._settings.music_volume = volume
            pygame.mixer.music.set_volume(self._effective_music_volume())
        except ValueError:
            pass

    def stop_music(self) -> None:
        if self._mixer_ok and self._music_playing:
            pygame.mixer.music.stop()
            self._music_playing = False

    def toggle_mute(self) -> bool:
        self.set_muted(not self.muted)
        return self.muted

    def update_volumes(self) -> None:
        """Re-apply volumes after a settings change."""
        if not self._mixer_ok:
            return
        volume = self._effective_sfx_volume()
        for sound in self._sounds.values():
            if sound is not None:
                sound.set_volume(volume)
        if self._music_playing and not self.muted:
            pygame.mixer.music.set_volume(self._effective_music_volume())
