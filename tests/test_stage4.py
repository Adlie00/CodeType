"""Stage 4 coverage: vertical enemies, bosses, pacing, WPM, effects, audio."""

import os
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.boss import Boss
from game.constants import (
    BOSS_INTRO_SECONDS,
    BOSS_PHASE_BREAKS,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    ENDLESS_BOSS_EVERY,
    ENEMY_BOSS,
    ENEMY_FAST,
    ENEMY_NORMAL,
    ENEMY_SPECIAL,
    ENEMY_TANK,
    FIELD_BOTTOM_MARGIN,
    SPEED_BONUS_PER_WPM,
)
from game.content import ContentRepository
from game.effects import EffectsManager
from game.enemy import Enemy, base_speed_for
from game.game_state import GameState
from game.scoring import Scoring
from game.wave_manager import WaveManager
from game.wpm import WpmTracker

ROOT = Path(__file__).resolve().parents[1]
# The design-space danger line: the bottom of the field, above its margin.
DANGER = 720.0 - FIELD_BOTTOM_MARGIN


def make_challenge(text: str, boss: bool = False):
    from game.content import Challenge

    return Challenge(
        text=text,
        language="python",
        difficulty=DIFFICULTY_EASY,
        boss=boss,
    )


class EnemyMovementTests(unittest.TestCase):
    def test_enemy_descends_vertically_and_escapes(self) -> None:
        enemy = Enemy(make_challenge("a" * 40), DIFFICULTY_EASY, ENEMY_NORMAL)
        self.assertLess(enemy.y, 0, "enemies must start above the play field")
        start = enemy.y
        enemy.update(0.5, DANGER)
        self.assertGreater(enemy.y, start, "enemies must fall downward")
        for _ in range(400):
            enemy.update(0.5, DANGER)
        self.assertTrue(enemy.escaped)
        self.assertGreater(enemy.y, DANGER)

    def test_special_drifts_sideways_while_others_do_not(self) -> None:
        normal = Enemy(make_challenge("a" * 40), DIFFICULTY_EASY, ENEMY_NORMAL)
        special = Enemy(make_challenge("a" * 40), DIFFICULTY_EASY, ENEMY_SPECIAL)
        start_normal = normal.x
        start_special = special.x
        for _ in range(40):
            normal.update(0.1, DANGER)
            special.update(0.1, DANGER)
        self.assertAlmostEqual(normal.x, start_normal, places=5)
        self.assertNotAlmostEqual(special.x, start_special, places=3)

    def test_tank_pulses(self) -> None:
        tank = Enemy(make_challenge("a" * 40), DIFFICULTY_EASY, ENEMY_TANK)
        self.assertEqual(tank.pulse, 0.0)
        for _ in range(20):
            tank.update(0.1, DANGER)
        self.assertGreater(tank.pulse, 0.0)

    def test_fast_is_quicker_than_a_tank(self) -> None:
        self.assertGreater(
            base_speed_for(ENEMY_FAST, DIFFICULTY_EASY),
            base_speed_for(ENEMY_TANK, DIFFICULTY_EASY),
        )

    def test_health_tracks_typing(self) -> None:
        enemy = Enemy(make_challenge("abc"), DIFFICULTY_EASY, ENEMY_NORMAL)
        self.assertEqual(enemy.health, 3)
        self.assertEqual(enemy.type_character("a"), "correct")
        self.assertEqual(enemy.health, 2)
        self.assertEqual(enemy.type_character("x"), "wrong")
        self.assertTrue(enemy.alive)
        enemy.type_character("b")
        self.assertEqual(enemy.type_character("c"), "complete")
        self.assertFalse(enemy.alive)

    def test_a_card_keeps_its_lane_across_a_resize(self) -> None:
        """A resize re-derives the lane from the station, not back to the left."""
        from game.ui import Layout

        layout = Layout(1920, 1080)
        enemy = Enemy(
            make_challenge("a" * 40), DIFFICULTY_EASY, ENEMY_NORMAL,
            station=0.5, layout=layout,
        )
        station = enemy.station
        self.assertAlmostEqual(
            enemy.x, layout.column_x(enemy.width, station), places=5
        )
        smaller = Layout(1280, 720)
        enemy.rebase(smaller)
        self.assertAlmostEqual(enemy.station, station, places=5)
        self.assertAlmostEqual(
            enemy.x, smaller.column_x(enemy.width, station), places=5
        )

    def test_a_lane_never_puts_a_card_off_screen(self) -> None:
        from game.ui import Layout

        for width, height in ((1920, 1080), (1280, 720), (800, 600)):
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                for station in layout.lane_stations():
                    for enemy_type in (ENEMY_NORMAL, ENEMY_SPECIAL):
                        enemy = Enemy(
                            make_challenge("a" * 40), DIFFICULTY_EASY, enemy_type,
                            station=station, layout=layout,
                        )
                        for _ in range(20):
                            enemy.update(0.05, DANGER)
                        self.assertGreaterEqual(
                            enemy.x, -layout.enemy_sway_special,
                            "a swaying card must not cross the left edge",
                        )
                        self.assertLessEqual(
                            enemy.x + enemy.width, width + layout.enemy_sway_special,
                            "a swaying card must not cross the right edge",
                        )


class PacingTests(unittest.TestCase):
    def test_long_code_falls_slowly_enough_to_type(self) -> None:
        short = Enemy(make_challenge("a" * 20), DIFFICULTY_EASY, ENEMY_NORMAL)
        long = Enemy(make_challenge("a" * 260), DIFFICULTY_EASY, ENEMY_TANK)
        for enemy in (short, long):
            enemy.limit_speed_for(DANGER)
        self.assertTrue(long.speed_limited, "a 260-char enemy must be speed capped")
        self.assertLess(long.speed, short.speed)
        # Enough travel time to type the snippet at the reference pace.
        travel = DANGER - long.y
        self.assertGreaterEqual(travel / long.speed, 260 / 8.0)

    def test_a_boss_is_speed_capped_to_its_own_typing_time(self) -> None:
        boss = Boss(make_challenge("a" * 500, boss=True), start_y=0.0)
        boss.limit_speed_for(DANGER)
        self.assertTrue(boss.speed_limited, "a 500-char boss must be speed capped")
        # Enough travel time to type the snippet at the reference pace.
        travel = DANGER - boss.y
        self.assertGreaterEqual(travel / boss.speed, 500 / 8.0)


class BossTests(unittest.TestCase):
    def setUp(self) -> None:
        self.boss = Boss(make_challenge("a" * 300, boss=True))
        self.boss.begin_intro()

    def test_intro_holds_the_boss_above_the_field(self) -> None:
        y = self.boss.y
        self.assertLess(y, 0)
        self.boss.update(BOSS_INTRO_SECONDS / 2, DANGER)
        self.assertTrue(self.boss.intro_active)
        self.assertAlmostEqual(self.boss.y, y, places=5)
        self.boss.update(BOSS_INTRO_SECONDS, DANGER)
        self.assertFalse(self.boss.intro_active)

    def test_boss_keeps_descending_and_escapes(self) -> None:
        self.boss.update(BOSS_INTRO_SECONDS + 0.1, DANGER)
        start = self.boss.y
        self.boss.update(0.5, DANGER)
        self.assertGreater(self.boss.y, start, "a boss must keep descending")
        for _ in range(4000):
            self.boss.update(0.5, DANGER)
        self.assertTrue(
            self.boss.escaped, "a boss that is not typed must reach the line"
        )

    def test_phases_track_remaining_health(self) -> None:
        self.boss.update(BOSS_INTRO_SECONDS + 0.1, DANGER)
        self.assertEqual(self.boss.phase, 1)
        for threshold in BOSS_PHASE_BREAKS:
            self.boss.health = int(self.boss.max_health * threshold) - 1
            self.boss._update_phase()
            self.assertEqual(self.boss.phase, BOSS_PHASE_BREAKS.index(threshold) + 2)

    def test_boss_counts_as_a_boss(self) -> None:
        self.assertTrue(self.boss.is_boss)
        self.assertEqual(self.boss.enemy_type, ENEMY_BOSS)


class WpmTests(unittest.TestCase):
    def test_rate_is_stable_over_a_full_window(self) -> None:
        now = [0.0]
        tracker = WpmTracker(window_seconds=5.0, clock=lambda: now[0])
        for i in range(60):  # 60 chars over 60s == 12 wpm
            now[0] = i
            tracker.sample(i)
        self.assertAlmostEqual(tracker.wpm, 12.0, delta=0.5)

    def test_early_samples_do_not_report_absurd_rates(self) -> None:
        now = [0.0]
        tracker = WpmTracker(window_seconds=5.0, clock=lambda: now[0])
        for i in range(3):  # 3 chars in 0.2s is 180 wpm at most
            now[0] = i * 0.1
            tracker.sample(i + 1)
            self.assertLess(tracker.wpm, 400, "window must not divide by a fraction of a second")

    def test_no_samples_reports_zero(self) -> None:
        self.assertEqual(WpmTracker(clock=lambda: 0.0).wpm, 0.0)

    def test_peak_is_retained(self) -> None:
        now = [0.0]
        tracker = WpmTracker(window_seconds=5.0, clock=lambda: now[0])
        for i in range(30):
            now[0] = i
            tracker.sample(i)
        self.assertGreaterEqual(tracker.peak, tracker.wpm)


class EndlessBossTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = ContentRepository(
            ROOT / "data" / "waves.json", ROOT / "data" / "languages"
        )

    def test_boss_arrives_every_twenty_kills(self) -> None:
        # The step has to stay under MIN_SPAWN_INTERVAL so a single update can
        # spawn at most one enemy, which is what a real frame does: the game
        # ticks at 60fps and a kill is one keystroke. Batching several seconds
        # into one update killed up to three enemies at once, so the counter
        # stepped over a multiple of 20 without ever landing on it and the
        # measured gap came out at 21 -- a property of the fake clock rather
        # than of the boss cadence. The step is 0.25s and the run is long
        # enough to see three bosses.
        manager = WaveManager(self.content, "endless")
        seen = []
        kills = 0
        for _ in range(2000):
            spawned = manager.update(0.25, 0, total_kills=kills)
            for enemy in spawned:
                if enemy.is_boss:
                    seen.append(kills)
                enemy.alive = False
                kills += 1
            if manager.remaining_enemies == 0 and not spawned:
                manager.advance(kills)
        self.assertTrue(seen, "endless must produce bosses")
        self.assertGreaterEqual(len(seen), 3, "expected at least three bosses in the run")
        for kill_count in seen:
            self.assertGreaterEqual(kill_count, ENDLESS_BOSS_EVERY)
        gaps = [b - a for a, b in zip([0] + seen, seen)]
        for gap in gaps:
            self.assertLessEqual(gap, ENDLESS_BOSS_EVERY, "bosses must not be spaced out")

    def test_only_one_boss_is_ever_queued(self) -> None:
        manager = WaveManager(self.content, "endless")
        for kills in range(0, 200, 4):
            manager.update(5.0, 0, total_kills=kills)
            self.assertLessEqual(sum(1 for o in manager._queue if o.is_boss), 1)


class EffectsTests(unittest.TestCase):
    def setUp(self) -> None:
        pygame.init()
        self.screen = pygame.Surface((320, 240))
        self.effects = EffectsManager()

    def test_particles_expire(self) -> None:
        self.effects.particles.explosion(100, 100, (255, 0, 0), 12)
        self.assertGreater(len(self.effects.particles), 0)
        for _ in range(200):
            self.effects.update(0.05)
        self.assertEqual(len(self.effects.particles), 0)

    def test_shake_decays_to_rest(self) -> None:
        self.effects.add_shake(10.0, 0.2)
        self.assertTrue(self.effects.shake.active)
        # The per-frame offset is random and truncated to whole pixels, so any one
        # frame is allowed to round to (0, 0) even at full strength. Sampling a
        # single frame made this test fail about one run in eighty; the shake
        # displacing the scene at all is the behaviour worth pinning down.
        offsets = set()
        for _ in range(60):
            self.effects.update(1 / 60)
            offsets.add(self.effects.shake.offset)
        self.assertTrue(
            any(offset != (0, 0) for offset in offsets),
            f"a fresh shake never moved the scene: {sorted(offsets)[:5]}",
        )
        for _ in range(200):
            self.effects.update(0.05)
        self.assertFalse(self.effects.shake.active)
        self.assertEqual(self.effects.shake.offset, (0, 0))

    def test_settings_disable_effects(self) -> None:
        quiet = EffectsManager(typing_effects=False, screen_shake=False)
        quiet.particles.explosion(10, 10, (255, 0, 0), 8)
        quiet.add_shake(12.0, 0.3)
        self.assertEqual(len(quiet.particles), 0)
        self.assertFalse(quiet.shake.active)
        self.assertFalse(quiet.effects_enabled)

    def test_reenabling_clears_then_restores(self) -> None:
        self.effects.configure(typing_effects=False, screen_shake=False)
        self.effects.particles.explosion(10, 10, (255, 0, 0), 8)
        self.assertEqual(len(self.effects.particles), 0)
        self.effects.configure(typing_effects=True, screen_shake=True)
        self.effects.particles.explosion(10, 10, (255, 0, 0), 8)
        self.assertGreater(len(self.effects.particles), 0)
        self.effects.add_shake(5.0, 0.1)
        self.assertTrue(self.effects.shake.active)

    def test_popups_expire(self) -> None:
        self.effects.popups.add("+100", 50, 50, (0, 255, 0))
        self.assertGreater(len(self.effects.popups), 0)
        for _ in range(200):
            self.effects.update(0.05)
        self.assertEqual(len(self.effects.popups), 0)


class AudioTests(unittest.TestCase):
    def test_every_documented_effect_has_a_file(self) -> None:
        from game.constants import SOUNDS_DIR

        expected = [
            "type_correct", "type_wrong", "destroy", "combo",
            "boss", "wave_clear", "game_over", "menu_select", "menu_move",
        ]
        for name in expected:
            path = os.path.join(SOUNDS_DIR, f"{name}.wav")
            self.assertTrue(os.path.exists(path), f"missing sound {name}.wav")
            self.assertGreater(os.path.getsize(path), 44, f"empty sound {name}.wav")


class BossScoreTests(unittest.TestCase):
    def test_boss_kill_is_worth_three_times(self) -> None:
        scoring = Scoring()
        args = ("a" * 300, DIFFICULTY_HARD, 3)
        normal = scoring.calculate(*args, combo=1, wpm=100, accuracy=100)
        boss = scoring.calculate(*args, combo=1, wpm=100, accuracy=100, boss=True)
        self.assertEqual(boss.total, normal.total * 3)

    def test_speed_bonus_rate_matches_spec(self) -> None:
        breakdown = Scoring().calculate("a" * 50, DIFFICULTY_EASY, 1, 1, 100, 95)
        self.assertEqual(breakdown.speed, int(40 * SPEED_BONUS_PER_WPM))

    def test_boss_counted_in_stats(self) -> None:
        state = GameState(clock=lambda: 0.0)
        state.record_destroy("a" * 100, "BOSS", 3, 120, 100, boss=True)
        stats = state.stats()
        self.assertEqual(stats["bosses"], 1)
        self.assertEqual(stats["enemies"], 1)


if __name__ == "__main__":
    unittest.main()
