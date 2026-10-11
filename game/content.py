"""Local JSON content loading for CODETYPE."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game.constants import (
    DIFFICULTY_BOSS,
    DIFFICULTY_ORDER,
    LANGUAGES_DIR,
    MAX_SNIPPET_LENGTH,
    WAVES_FILE,
)


class ContentError(ValueError):
    pass


@dataclass(frozen=True)
class Challenge:
    text: str
    language: str
    difficulty: str
    boss: bool = False

    @property
    def length(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class WaveConfig:
    wave_number: int
    language: str
    display_name: str
    difficulty_progression: tuple[str, ...]
    enemy_count: int
    boss_wave: bool
    boss_language: str | None
    spawn_interval: float
    description: str


class ContentRepository:
    def __init__(
        self,
        waves_path: str | Path = WAVES_FILE,
        languages_dir: str | Path = LANGUAGES_DIR,
    ) -> None:
        self._waves_path = Path(waves_path)
        self._languages_dir = Path(languages_dir)
        self._waves = self._load_waves()
        self._challenges = self._load_languages()
        self._endless_base_interval = self._read_float(
            self._wave_document, "endless_base_interval", 4.0
        )
        self._endless_interval_decay = self._read_float(
            self._wave_document, "endless_interval_decay", 0.05
        )
        self._endless_min_interval = self._read_float(
            self._wave_document, "endless_min_interval", 1.0
        )

    @property
    def waves(self) -> tuple[WaveConfig, ...]:
        return self._waves

    @property
    def available_waves(self) -> tuple[WaveConfig, ...]:
        return tuple(wave for wave in self._waves if self.has_wave_content(wave))

    @property
    def endless_base_interval(self) -> float:
        return self._endless_base_interval

    @property
    def endless_interval_decay(self) -> float:
        return self._endless_interval_decay

    @property
    def endless_min_interval(self) -> float:
        return self._endless_min_interval

    def get_wave(self, wave_number: int) -> WaveConfig:
        for wave in self._waves:
            if wave.wave_number == wave_number:
                return wave
        raise ContentError(f"Wave {wave_number} is not configured")

    def has_wave_content(self, wave: WaveConfig) -> bool:
        language_data = self._challenges.get(wave.language, {})
        return all(language_data.get(difficulty) for difficulty in wave.difficulty_progression)

    def get_challenges(self, language: str, difficulty: str) -> tuple[Challenge, ...]:
        language = language.lower()
        difficulty = difficulty.upper()
        if difficulty not in (*DIFFICULTY_ORDER, DIFFICULTY_BOSS):
            raise ContentError(f"Unknown difficulty: {difficulty}")

        items = self._challenges.get(language, {}).get(difficulty, [])
        if not items:
            raise ContentError(f"No {difficulty} challenges available for {language}")

        return tuple(
            Challenge(
                text=item,
                language=language,
                difficulty=difficulty,
                boss=difficulty == DIFFICULTY_BOSS,
            )
            for item in items
        )

    def get_challenges_by_length(
        self,
        language: str,
        difficulty: str,
        bias: float = 0.5,
    ) -> tuple[Challenge, ...]:
        """A length-appropriate band of challenges, best match first.

        ``bias`` 0.0 returns only the short half of the pool (shortest first),
        1.0 only the long half (longest first), and 0.5 the middle band. The
        result is a *band* rather than the whole pool so that indexing through
        it stays on the intended side: a Fast enemy drawing from a short-only
        band can never pick up a Tank-sized snippet.
        """
        challenges = sorted(self.get_challenges(language, difficulty), key=lambda c: c.length)
        count = len(challenges)
        if count < 3:
            return tuple(challenges)

        half = max(1, count // 2)
        if bias <= 0.0:
            return tuple(challenges[:half])
        if bias >= 1.0:
            return tuple(reversed(challenges[count - half :]))

        # The middle band is centred on the median *length*, not on the number of
        # challenges. Ranking the whole pool by distance from the midpoint and
        # then keeping the closest half keeps every member of the band nearer to
        # the median than anything left out, so a Normal enemy is never handed
        # the shortest or the longest snippet in the pool.
        lengths = [c.length for c in challenges]
        midpoint = (
            float(lengths[half]) if count % 2 else (lengths[half - 1] + lengths[half]) / 2.0
        )
        band = sorted(challenges, key=lambda c: (abs(c.length - midpoint), c.length))
        return tuple(band[:half])

    def _load_waves(self) -> tuple[WaveConfig, ...]:
        document = self._read_json(self._waves_path)
        self._wave_document = document
        raw_waves = document.get("waves")
        if not isinstance(raw_waves, list) or not raw_waves:
            raise ContentError("waves.json must contain a non-empty waves list")

        waves: list[WaveConfig] = []
        for index, raw in enumerate(raw_waves, start=1):
            if not isinstance(raw, dict):
                raise ContentError(f"Wave {index} must be an object")
            language = self._required_string(raw, "language", f"wave {index}").lower()
            progression = raw.get("difficulty_progression")
            if not isinstance(progression, list) or not progression:
                raise ContentError(f"Wave {index} needs a difficulty progression")
            progression_tuple = tuple(
                str(item).upper()
                for item in progression
                if isinstance(item, str) and item.strip()
            )
            if len(progression_tuple) != len(progression):
                raise ContentError(f"Wave {index} contains an invalid difficulty")
            if any(item not in DIFFICULTY_ORDER for item in progression_tuple):
                raise ContentError(f"Wave {index} contains an unknown difficulty")
            enemy_count = self._required_int(raw, "enemy_count", f"wave {index}")
            if enemy_count < 1:
                raise ContentError(f"Wave {index} must contain at least one enemy")
            spawn_interval = self._required_float(raw, "spawn_interval", f"wave {index}")
            if spawn_interval <= 0:
                raise ContentError(f"Wave {index} spawn interval must be positive")
            boss_wave = bool(raw.get("boss_wave", False))
            boss_language = raw.get("boss_language")
            if boss_language is not None:
                boss_language = str(boss_language).lower()
            waves.append(
                WaveConfig(
                    wave_number=self._required_int(raw, "wave_number", f"wave {index}"),
                    language=language,
                    display_name=self._required_string(raw, "display_name", f"wave {index}"),
                    difficulty_progression=progression_tuple,
                    enemy_count=enemy_count,
                    boss_wave=boss_wave,
                    boss_language=boss_language,
                    spawn_interval=spawn_interval,
                    description=str(raw.get("description", "")),
                )
            )
        return tuple(sorted(waves, key=lambda wave: wave.wave_number))

    def _load_languages(self) -> dict[str, dict[str, list[str]]]:
        if not self._languages_dir.exists() or not self._languages_dir.is_dir():
            raise ContentError(f"Language directory does not exist: {self._languages_dir}")

        result: dict[str, dict[str, list[str]]] = {}
        for path in sorted(self._languages_dir.glob("*.json")):
            document = self._read_json(path)
            language = str(document.get("language", path.stem)).lower()
            raw_challenges = document.get("challenges")
            if not isinstance(raw_challenges, dict):
                raise ContentError(f"{path.name} must contain a challenges object")
            normalized: dict[str, list[str]] = {}
            for difficulty in (*DIFFICULTY_ORDER, DIFFICULTY_BOSS):
                items = raw_challenges.get(difficulty)
                if not isinstance(items, list):
                    raise ContentError(
                        f"{path.name} is missing the {difficulty} challenge list"
                    )
                normalized[difficulty] = [self._challenge_text(item, path, difficulty) for item in items]
            result[language] = normalized
        if not result:
            raise ContentError(f"No language files found in {self._languages_dir}")
        return result

    def _challenge_text(self, item: Any, path: Path, difficulty: str) -> str:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = item.get("text", item.get("code", ""))
        else:
            text = ""
        if not isinstance(text, str) or not text:
            raise ContentError(f"Invalid {difficulty} challenge in {path.name}")
        if "\n" in text or "\r" in text:
            raise ContentError(
                f"{path.name} {difficulty} challenge spans more than one line: {text!r}"
            )
        if len(text) > MAX_SNIPPET_LENGTH:
            raise ContentError(
                f"{path.name} {difficulty} challenge is {len(text)} characters, "
                f"over the {MAX_SNIPPET_LENGTH} a card can show: {text!r}"
            )
        return text

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except FileNotFoundError as exc:
            raise ContentError(f"Content file does not exist: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ContentError(f"Unable to read content file {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise ContentError(f"Content file must contain an object: {path}")
        return document

    @staticmethod
    def _required_string(data: dict[str, Any], key: str, context: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ContentError(f"{context} requires a non-empty {key}")
        return value

    @staticmethod
    def _required_int(data: dict[str, Any], key: str, context: str) -> int:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContentError(f"{context} requires an integer {key}")
        return value

    @staticmethod
    def _required_float(data: dict[str, Any], key: str, context: str) -> float:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContentError(f"{context} requires a numeric {key}")
        return float(value)

    @staticmethod
    def _read_float(document: dict[str, Any], key: str, default: float) -> float:
        value = document.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)
