import json
import os
import random
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from game.constants import DIFFICULTY_EASY, LANGUAGES_DIR, MAX_SNIPPET_LENGTH
from game.content import ContentError, ContentRepository
from game.difficulty import difficulty_for_progress, get_profile
from game.game_state import GameState
from game.scoring import Scoring
from game.typing_engine import TypingEngine
from game.ui import Layout
from game.wave_manager import WaveManager
from screens.game_over_screen import GameOverScreen
from screens.leaderboard_screen import LeaderboardScreen
from screens.name_input_screen import NameInputScreen
from screens.settings_screen import SettingsScreen


class TypingEngineTests(unittest.TestCase):
    def test_correct_and_incorrect_characters(self) -> None:
        engine = TypingEngine("if x:")
        self.assertTrue(engine.handle_character("i"))
        self.assertFalse(engine.handle_character("x"))
        self.assertEqual(engine.index, 1)
        self.assertEqual(engine.mistakes, 1)
        self.assertAlmostEqual(engine.accuracy, 50.0)

    def test_backspace_undoes_a_correct_character(self) -> None:
        engine = TypingEngine("()")
        self.assertTrue(engine.handle_character("("))
        self.assertTrue(engine.backspace())
        self.assertEqual(engine.index, 0)
        self.assertTrue(engine.handle_character("("))

    def test_wpm_uses_five_character_words(self) -> None:
        now = [0.0]
        engine = TypingEngine("abcde", clock=lambda: now[0])
        for character in "abcde":
            self.assertTrue(engine.handle_character(character))
        now[0] = 60.0
        self.assertAlmostEqual(engine.wpm, 1.0)

    def test_punctuation_and_newlines_are_supported(self) -> None:
        engine = TypingEngine("a = {\n}\n")
        for character in engine.target:
            self.assertTrue(engine.handle_character(character))
        self.assertTrue(engine.completed)


class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.content = ContentRepository(root / "data" / "waves.json", root / "data" / "languages")

    def test_full_campaign_content_is_available(self) -> None:
        self.assertEqual(len(self.content.available_waves), 10)
        languages = [wave.language for wave in self.content.available_waves]
        self.assertEqual(
            languages,
            ["html", "css", "javascript", "python", "java", "c", "cpp", "csharp", "sql", "mixed"],
        )
        for wave in self.content.available_waves:
            for difficulty in wave.difficulty_progression:
                self.assertGreaterEqual(
                    len(self.content.get_challenges(wave.language, difficulty)), 2
                )

    def test_every_tier_has_enough_content_to_avoid_repeats(self) -> None:
        """Each wave/tier pool must cover every enemy that wave draws from it.

        Waves escalate the tier as they progress, so a wave that lists three
        tiers asks its top tier for roughly a third of the wave. Pools smaller
        than that make the same snippet reappear within a single wave. This was
        2-3 snippets for the late languages, which repeated visibly in waves
        7-10. The demand is computed with the same distribution the game uses,
        so the test cannot drift from the real spawn logic.
        """
        for wave in self.content.available_waves:
            demand: dict[str, int] = {}
            for index in range(wave.enemy_count):
                tier = difficulty_for_progress(
                    wave.difficulty_progression, index, wave.enemy_count
                )
                demand[tier] = demand.get(tier, 0) + 1
            for tier, needed in sorted(demand.items()):
                with self.subTest(wave=wave.wave_number, tier=tier):
                    pool = len(self.content.get_challenges(wave.language, tier))
                    self.assertGreaterEqual(
                        pool, needed, f"wave {wave.wave_number} {tier} repeats snippets"
                    )

    def test_late_wave_expert_pools_are_no_longer_thin(self) -> None:
        """Guards the specific pools that used to be 2-3 snippets."""
        thin = {
            wave.language: len(self.content.get_challenges(wave.language, "EXPERT"))
            for wave in self.content.available_waves
            if "EXPERT" in wave.difficulty_progression
        }
        self.assertTrue(thin, "expected at least one wave to use EXPERT")
        for language, count in thin.items():
            with self.subTest(language=language):
                self.assertGreaterEqual(count, 6)

    def test_all_snippet_ids_are_unique(self) -> None:
        seen: set[str] = set()
        for path in sorted(Path(LANGUAGES_DIR).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for tier, items in data["challenges"].items():
                for item in items:
                    with self.subTest(language=data["language"], tier=tier, id=item["id"]):
                        self.assertNotIn(item["id"], seen, "duplicate snippet id")
                        self.assertTrue(item["code"].strip(), "empty snippet")
                        self.assertTrue(item["hint"].strip(), "missing hint")
                    seen.add(item["id"])
        self.assertGreaterEqual(len(seen), 380)

    def test_every_snippet_fits_on_one_line(self) -> None:
        for path in sorted(Path(LANGUAGES_DIR).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for tier, items in data["challenges"].items():
                for item in items:
                    with self.subTest(language=data["language"], tier=tier, id=item["id"]):
                        code = item["code"]
                        self.assertNotIn("\n", code, "snippet spans more than one line")
                        self.assertNotIn("\r", code, "snippet spans more than one line")
                        # A card is 370px wide, and even the smallest font the
                        # renderer will fall back to cannot set more than this.
                        # Anything longer silently overflows the card instead of
                        # just being hard to read.
                        self.assertLessEqual(
                            len(code), MAX_SNIPPET_LENGTH, f"snippet is {len(code)} chars"
                        )

    def test_boss_content_exists_for_every_boss_wave(self) -> None:
        for wave in self.content.available_waves:
            if not wave.boss_wave:
                continue
            language = wave.boss_language or wave.language
            challenges = self.content.get_challenges(language, "BOSS")
            self.assertTrue(challenges)
            self.assertTrue(all(c.boss for c in challenges))

    def test_unknown_language_raises_a_clear_error(self) -> None:
        with self.assertRaises(ContentError):
            self.content.get_challenges("cobol", "EASY")

    def test_length_bands_separate_fast_from_tank(self) -> None:
        fast = self.content.get_challenges_by_length("python", "HARD", 0.0)
        tank = self.content.get_challenges_by_length("python", "HARD", 1.0)
        self.assertLessEqual(max(c.length for c in fast), min(c.length for c in tank))
        # A short-only band must never hand out a long snippet.
        self.assertTrue(all(c.length <= sorted(x.length for x in tank)[0] for c in fast))

    def test_middle_band_centres_on_the_median_length(self) -> None:
        """A 0.5 bias must return a band around the median length.

        Regression test: this once ranked the pool by distance from
        ``len(pool) / 2`` -- a challenge *count*, not a length -- so the middle
        band was silently the entire pool ordered shortest-first.
        """
        for language, difficulty in (("python", "HARD"), ("java", "MEDIUM")):
            pool = sorted(
                self.content.get_challenges(language, difficulty), key=lambda c: c.length
            )
            band = self.content.get_challenges_by_length(language, difficulty, 0.5)
            with self.subTest(language=language, difficulty=difficulty):
                self.assertLess(len(band), len(pool), "band must be narrower than the pool")
                lengths = [c.length for c in pool]
                midpoint = lengths[len(pool) // 2]
                kept = [c.length for c in band]
                dropped = [c.length for c in pool if c.length not in kept]
                if dropped:
                    self.assertLessEqual(
                        max(abs(v - midpoint) for v in kept),
                        min(abs(v - midpoint) for v in dropped),
                        "band members must be the closest to the median",
                    )
                self.assertNotIn(min(lengths), kept, "shortest snippet is not 'middle'")
                self.assertNotIn(max(lengths), kept, "longest snippet is not 'middle'")


class ScoringTests(unittest.TestCase):
    def test_perfect_easy_score_is_deterministic(self) -> None:
        breakdown = Scoring().calculate("abc", DIFFICULTY_EASY, 1, 1, 0, 100)
        self.assertEqual(breakdown.base, 30)
        self.assertEqual(breakdown.accuracy, 500)
        self.assertEqual(breakdown.wave, 50)
        self.assertEqual(breakdown.speed, 0)
        self.assertEqual(breakdown.subtotal, 580)
        self.assertEqual(breakdown.difficulty_mult, 1.0)
        self.assertEqual(breakdown.combo_mult, 1.0)
        self.assertEqual(breakdown.boss_mult, 1.0)
        self.assertEqual(breakdown.total, 580)

    def test_speed_bonus_starts_above_the_threshold(self) -> None:
        self.assertEqual(Scoring().calculate("a" * 10, DIFFICULTY_EASY, 1, 1, 60, 100).speed, 0)
        self.assertEqual(Scoring().calculate("a" * 10, DIFFICULTY_EASY, 1, 1, 80, 100).speed, 100)

    def test_combo_multiplier_grows_and_caps(self) -> None:
        scoring = Scoring()
        self.assertEqual(scoring.calculate("a", DIFFICULTY_EASY, 1, 5, 0, 100).combo_mult, 1.4)
        self.assertEqual(scoring.calculate("a", DIFFICULTY_EASY, 1, 1000, 0, 100).combo_mult, 5.0)

    def test_boss_triples_the_total(self) -> None:
        scoring = Scoring()
        normal = scoring.calculate("a" * 20, DIFFICULTY_EASY, 1, 1, 100, 100)
        boss = scoring.calculate("a" * 20, DIFFICULTY_EASY, 1, 1, 100, 100, boss=True)
        self.assertEqual(boss.boss_mult, 3.0)
        self.assertEqual(boss.total, normal.total * 3)

    def test_difficulty_changes_score(self) -> None:
        easy = Scoring().score("print('x')", DIFFICULTY_EASY, 1, 1, 0, 100)
        hard = Scoring().score("print('x')", "EXPERT", 1, 1, 0, 100)
        self.assertGreater(hard, easy)


class StateTests(unittest.TestCase):
    def test_combo_accuracy_and_lives(self) -> None:
        now = [0.0]
        state = GameState(clock=lambda: now[0])
        state.record_attempt(1, 1)
        state.record_attempt(0, 1)
        state.record_mistake()
        self.assertEqual(state.combo, 0)
        self.assertAlmostEqual(state.accuracy, 50.0)
        state.record_destroy("abc", DIFFICULTY_EASY, 1, 60, 50)
        self.assertEqual(state.combo, 1)
        self.assertEqual(state.max_combo, 1)
        self.assertFalse(state.record_missed_enemy())
        self.assertEqual(state.player.lives, 2)

    def test_boss_kills_are_counted_separately(self) -> None:
        state = GameState(clock=lambda: 0.0)
        state.record_destroy("abc", DIFFICULTY_EASY, 1, 60, 100)
        self.assertEqual(state.enemies_destroyed, 1)
        self.assertEqual(state.bosses_destroyed, 0)
        state.record_destroy("abc", "BOSS", 3, 60, 100, boss=True)
        self.assertEqual(state.enemies_destroyed, 2)
        self.assertEqual(state.bosses_destroyed, 1)

    def test_combo_milestones_are_reported_once(self) -> None:
        state = GameState(clock=lambda: 0.0)
        for _ in range(5):
            state.record_destroy("a", DIFFICULTY_EASY, 1, 0, 100)
        self.assertEqual(state.take_combo_milestone(), 5)
        self.assertEqual(state.take_combo_milestone(), 0)

    def test_difficulty_progression(self) -> None:
        progression = ("EASY", "MEDIUM")
        self.assertEqual(difficulty_for_progress(progression, 0, 12), "EASY")
        self.assertEqual(difficulty_for_progress(progression, 6, 12), "MEDIUM")
        self.assertEqual(get_profile("EASY").max_active, 2)


class WaveManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.content = ContentRepository(root / "data" / "waves.json", root / "data" / "languages")

    def test_first_campaign_wave_has_mvp_queue(self) -> None:
        manager = WaveManager(self.content)
        self.assertEqual(manager.total_waves, 10)
        self.assertEqual(manager.wave_number, 1)
        self.assertEqual(manager.language_name, "HTML")
        self.assertEqual(manager.remaining_enemies, 12)
        self.assertEqual(manager.current_difficulty, "EASY")
        spawned = manager.update(0.0, 0)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].difficulty, "EASY")

    def test_clearing_html_advances_to_css(self) -> None:
        manager = WaveManager(self.content)
        while manager.remaining_enemies:
            spawned = manager.update(10.0, 0)
            self.assertTrue(spawned)
            for enemy in spawned:
                enemy.alive = False
        self.assertTrue(manager.is_wave_complete([]))
        self.assertTrue(manager.advance())
        self.assertEqual(manager.wave_number, 2)
        self.assertEqual(manager.language_name, "CSS")
        self.assertEqual(manager.remaining_enemies, 14)
        self.assertEqual(manager.current_difficulty, "EASY")
        spawned = manager.update(0.0, 0)
        self.assertEqual(len(spawned), 1)
        self.assertEqual(spawned[0].difficulty, "EASY")

    def test_competition_plays_the_campaign(self) -> None:
        manager = WaveManager(self.content, "competition")
        self.assertTrue(manager.is_campaign)
        self.assertEqual(manager.total_waves, 10)
        self.assertEqual(manager.language_name, "HTML")

    def test_endless_is_unbounded_and_names_the_mode(self) -> None:
        manager = WaveManager(self.content, "endless")
        self.assertFalse(manager.is_campaign)
        self.assertIn("ENDLESS", manager.language_name)
        for _ in range(30):
            self.assertTrue(manager.advance(0))

    def test_endless_rolls_a_fresh_language_each_wave(self) -> None:
        # The old bug froze generated waves on the ladder's first language (HTML).
        # Over sixty waves a ten-language pool will not come up identical.
        manager = WaveManager(self.content, "endless")
        ladder = {wave.language for wave in self.content.available_waves}
        seen = {manager.current_wave.language}
        for _ in range(60):
            self.assertTrue(manager.advance(0))
            language = manager.current_wave.language
            self.assertIn(language, ladder)
            for order in manager._queue:
                self.assertEqual(order.challenge.language, language)
            seen.add(language)
        self.assertGreater(len(seen), 1, "endless waves must not stay on one language")

    def test_endless_display_name_tracks_the_language(self) -> None:
        manager = WaveManager(self.content, "endless")
        names = {wave.language: wave.display_name for wave in self.content.available_waves}
        for _ in range(20):
            language = manager.current_wave.language
            self.assertEqual(manager.language_name, f"{names[language]} ENDLESS")
            self.assertTrue(manager.advance(0))

    def test_boss_waves_queue_exactly_one_boss(self) -> None:
        manager = WaveManager(self.content)
        boss_waves = []
        for _ in range(10):
            if manager.current_wave.boss_wave:
                bosses = [o for o in manager._queue if o.is_boss]
                self.assertEqual(len(bosses), 1)
                boss_waves.append(manager.wave_number)
                self.assertEqual(manager._build_enemy(bosses[0]).__class__.__name__, "Boss")
            if manager.wave_number == manager.total_waves:
                break
            self.assertTrue(manager.advance(0))
        self.assertEqual(boss_waves, [3, 5, 7, 9, 10])
        self.assertFalse(manager.advance(0), "advancing past the last wave must fail")

    def test_wave_waits_for_an_introducing_boss(self) -> None:
        manager = WaveManager(self.content)
        while manager.wave_number < 3:
            self.assertTrue(manager.advance(0))
        # Drain the wave's regular enemies, leaving the boss order queued.
        while any(not o.is_boss for o in manager._queue):
            spawned = manager.update(10.0, 0)
            self.assertTrue(spawned)
            for enemy in spawned:
                enemy.alive = False
        self.assertEqual(manager.remaining_enemies, 1)
        boss = manager.update(10.0, 0)[0]
        self.assertTrue(boss.is_boss)
        self.assertTrue(boss.intro_active)
        # A boss still arriving must keep the wave open, or victory can be
        # declared while the final boss is on screen.
        self.assertFalse(manager.is_wave_complete([boss]))
        boss.intro_active = False
        self.assertFalse(manager.is_wave_complete([boss]))
        boss.alive = False
        self.assertTrue(manager.is_wave_complete([]))

    def test_a_busy_field_keeps_new_spawns_in_different_lanes(self) -> None:
        """Cards must never land in the same lane and hide each other."""
        from game.constants import DIFFICULTY_EXPERT

        layout = Layout(1280, 720)
        lanes = layout.lane_stations()
        manager = WaveManager(
            self.content, layout=layout, difficulty=DIFFICULTY_EXPERT
        )

        # Each call sees the lanes the previous ones took, so filling the field
        # one spawn at a time is the occupied case; a batch of two in one call is
        # the same rule applied to cards spawned in the same instant.
        field: list = []
        while len(field) < len(lanes):
            spawned = manager.update(
                10.0, len(field), occupied=[enemy.station for enemy in field]
            )
            self.assertTrue(spawned, "the field has room for another card")
            field.extend(spawned)
        self.assertEqual(sorted(enemy.station for enemy in field), sorted(lanes))
        for enemy in field:
            self.assertEqual(
                enemy.x, layout.column_x(enemy.width, enemy.station),
                "a card has to be drawn in the lane it was given",
            )

    def test_spawn_lanes_vary_instead_of_always_being_the_first(self) -> None:
        random.seed(20240501)
        manager = WaveManager(self.content, layout=Layout(1280, 720))
        stations = []
        while manager.remaining_enemies:
            spawned = manager.update(10.0, 0)
            self.assertTrue(spawned)
            for enemy in spawned:
                enemy.alive = False
                stations.append(enemy.station)
        self.assertGreater(
            len(set(stations)), 1,
            "a whole wave in one lane is the bug this replaced",
        )


class _FakeSettings:
    def __init__(self) -> None:
        self.width = 640
        self.height = 480
        self.fullscreen = False
        self.master_volume = 0.8
        self.music_volume = 0.5
        self.sfx_volume = 0.8
        self.typing_effects = True
        self.screen_shake = True
        self.saved = False

    def save(self) -> None:
        self.saved = True


class _FakeAssets:
    def font(self, size: int, bold: bool = False):
        return pygame.font.Font(None, size)


class _FakeAudio:
    def __init__(self) -> None:
        self.played = []
        self.volume_updates = 0

    def play(self, slot: str) -> None:
        self.played.append(slot)

    def update_volumes(self) -> None:
        self.volume_updates += 1


class _FakeLeaderboard:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []
        self.saved = []

    def get_top(self, limit: int = 20, sort_by: str = "score"):
        return self.rows[:limit]

    def save_score(self, **values) -> None:
        self.saved.append(values)


class ShellScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        cls.screen = pygame.display.set_mode((640, 480))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.settings = _FakeSettings()
        self.assets = _FakeAssets()
        self.audio = _FakeAudio()
        self.leaderboard = _FakeLeaderboard(
            [
                {
                    "player_name": "ACE",
                    "score": 4200,
                    "wpm": 71.5,
                    "accuracy": 98.0,
                    "mode": "campaign",
                }
            ]
        )

    def test_name_input_edits_and_submits(self) -> None:
        from screens.game_screen import GameScreen

        view = NameInputScreen(
            self.screen,
            self.settings,
            self.assets,
            self.audio,
            self.leaderboard,
            "competition",
        )
        for character in "ABC":
            view._handle_key(pygame.event.Event(pygame.KEYDOWN, key=ord(character), unicode=character))
        view._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE))
        result = view._handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertIsInstance(result, GameScreen)
        self.assertEqual(result._player_name, "AB")

    def test_game_over_saves_the_run_once(self) -> None:
        stats = {
            "player_name": "ACE",
            "mode": "campaign",
            "score": 1234,
            "wpm": 72.0,
            "accuracy": 98.5,
            "max_combo": 8,
            "waves": 2,
            "enemies": 26,
        }
        view = GameOverScreen(
            self.screen,
            self.settings,
            self.assets,
            self.audio,
            self.leaderboard,
            stats,
        )
        self.assertTrue(view._save_status)
        self.assertEqual(len(self.leaderboard.saved), 1)
        self.assertEqual(self.leaderboard.saved[0]["score"], 1234)
        self.assertEqual(self.leaderboard.saved[0]["mode"], "campaign")

    def test_leaderboard_renders_rows(self) -> None:
        view = LeaderboardScreen(
            self.screen,
            self.settings,
            self.assets,
            self.audio,
            self.leaderboard,
        )
        view._draw()
        self.assertEqual(len(view._rows), 1)

    def test_settings_adjusts_volume_and_toggle(self) -> None:
        view = SettingsScreen(
            self.screen,
            self.settings,
            self.assets,
            self.audio,
            self.leaderboard,
        )
        view._selected = 2
        view._adjust(1)
        self.assertAlmostEqual(self.settings.master_volume, 0.9)
        view._selected = 6
        view._adjust(1)
        self.assertFalse(self.settings.screen_shake)
        self.assertTrue(self.settings.saved)
        self.assertEqual(self.audio.volume_updates, 1)

    def test_main_menu_exit_returns_to_application_loop(self) -> None:
        from screens.main_menu import MainMenuScreen

        view = MainMenuScreen(
            self.screen,
            self.settings,
            self.assets,
            self.audio,
            self.leaderboard,
        )
        pygame.event.clear()
        for _ in range(6):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, unicode=""))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))

        class Clock:
            def tick(self, fps):
                return 16

        self.assertIsNone(view.run(Clock()))
        pygame.event.clear()


if __name__ == "__main__":
    unittest.main()
