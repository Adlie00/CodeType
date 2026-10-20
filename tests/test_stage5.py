"""Stage 5 coverage: display layout is resolution-independent.

These tests exist because the layout has two failure modes that look fine at
1920x1080 and are invisible in a screenshot: geometry that overflows the
surface, and geometry whose *timing* changes with the window. The second is the
nastier one — a bigger window with unscaled speeds is silently an easier game.
"""

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

# This module drives real UI, fonts, and surfaces, so it has to stand on its own
# rather than relying on an earlier test module having called pygame.init().
pygame.init()

from game.constants import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DESCENT_REFERENCE_CPS,
    DIFFICULTY_EASY,
    ENEMY_BASE_SPEEDS,
    ENEMY_COLUMNS,
    ENEMY_MAX_HEIGHT,
    ENEMY_NORMAL,
    FIELD_BOTTOM_MARGIN,
    WINDOW_PRESETS,
)
from game.ui import Layout, UI, scale_for

# The speed the pacing maths is written against: an unmultiplied Normal.
NOMINAL = ENEMY_BASE_SPEEDS[ENEMY_NORMAL]


# The sizes worth checking: 16:9 up to 4K, 16:10, and the 4:3 and small
# windows people actually run this in.
DISPLAY_SIZES = (
    (3840, 2160),
    (2560, 1440),
    (1920, 1080),
    (1600, 900),
    (1366, 768),
    (1280, 800),
    (1024, 768),
    (800, 600),
)

# Fall length at 1:1, from the spawn clearance down to the danger line.
DESIGN_TRAVEL = 720.0 - FIELD_BOTTOM_MARGIN - (78.0 + 150.0)
DESIGN_TIME = DESIGN_TRAVEL / ENEMY_BASE_SPEEDS[ENEMY_NORMAL]


class ScaleTests(unittest.TestCase):
    def test_scale_is_bounded_and_takes_the_limiting_axis(self) -> None:
        self.assertEqual(scale_for(1280, 720), 1.0)
        self.assertEqual(scale_for(1920, 1080), 1.5)
        self.assertAlmostEqual(scale_for(1024, 600), 1024 / 1280)
        for width, height in DISPLAY_SIZES:
            self.assertGreaterEqual(scale_for(width, height), 0.55)
            self.assertLessEqual(scale_for(width, height), 3.2)

    def test_a_degenerate_size_falls_back_to_the_design_surface(self) -> None:
        layout = Layout(0, 0)
        self.assertEqual(layout.width, 1280)
        self.assertEqual(layout.height, 720)
        self.assertEqual(layout.scale, 1.0)
        self.assertAlmostEqual(
            layout.danger_line, 720.0 - FIELD_BOTTOM_MARGIN
        )

    def test_the_default_window_is_large(self) -> None:
        self.assertEqual((DEFAULT_WIDTH, DEFAULT_HEIGHT), (1920, 1080))


class LayoutContainmentTests(unittest.TestCase):
    def test_geometry_stays_inside_every_surface(self) -> None:
        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                self.assertGreaterEqual(layout.danger_line, layout.hud_height)
                self.assertLessEqual(
                    layout.danger_line + layout.warning_band_height // 2, height,
                    "the warning band must not run off the bottom edge",
                )
                self.assertLess(
                    layout.enemy_column_x + layout.enemy_width, width,
                    "an enemy card must fit across",
                )
                self.assertLess(
                    layout.enemy_column_x + layout.enemy_width + layout.boss_width_bonus,
                    width,
                    "a boss card must fit across",
                )

    def test_the_field_always_shows_at_least_two_code_lines(self) -> None:
        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                usable = (
                    layout.enemy_max_height
                    - layout.enemy_header_height
                    - layout.enemy_footer_height
                )
                self.assertGreaterEqual(
                    usable, 2 * layout.enemy_line_height,
                    "a card must have room for two lines of snippet",
                )
                self.assertLessEqual(layout.enemy_max_height, ENEMY_MAX_HEIGHT * 3.2)

    def test_a_shorter_window_shrinks_the_cards_rather_than_overflowing(self) -> None:
        small = Layout(800, 600)
        large = Layout(1920, 1080)
        self.assertLess(small.enemy_max_height, large.enemy_max_height)
        self.assertLess(small.hud_height, large.hud_height)

    def test_every_lane_keeps_a_card_on_screen_at_every_size(self) -> None:
        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                cards = (
                    layout.enemy_width,
                    layout.enemy_width + layout.boss_width_bonus,
                )
                for card_width in cards:
                    for station in layout.lane_stations():
                        x = layout.column_x(card_width, station)
                        self.assertGreaterEqual(
                            x - layout.enemy_sway_special, 0.0,
                            "a card at full sway must stay on the left edge",
                        )
                        self.assertLessEqual(
                            x + card_width + layout.enemy_sway_special, float(width),
                            "a card at full sway must stay on the right edge",
                        )

    def test_lanes_span_the_field_without_overlapping(self) -> None:
        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                lanes = layout.lane_stations()
                self.assertEqual(len(lanes), ENEMY_COLUMNS)
                self.assertAlmostEqual(lanes[0], 0.0)
                self.assertAlmostEqual(lanes[-1], 1.0)
                columns = [layout.column_x(layout.enemy_width, lane) for lane in lanes]
                self.assertEqual(
                    columns[0], float(layout.enemy_column_x),
                    "the leftmost lane is the authored column",
                )
                for left, right in zip(columns, columns[1:]):
                    self.assertGreaterEqual(
                        right - left, float(layout.enemy_width),
                        "two lanes have to be far enough apart to not hide a card",
                    )


class LayoutPacingTests(unittest.TestCase):
    def test_time_to_the_danger_line_is_the_same_at_every_size(self) -> None:
        """The invariant that keeps difficulty honest across resolutions."""
        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                seconds = layout.travel / layout.speed(NOMINAL)
                self.assertAlmostEqual(
                    seconds, DESIGN_TIME, delta=0.05,
                    msg="a 4:3 window must not make the enemy fall more slowly",
                )

    def test_speed_scales_with_travel_not_with_raw_scale(self) -> None:
        """Speed must follow the distance, which is the whole point.

        ``scale`` alone is wrong: a 4:3 surface has spare height that becomes
        extra fall distance, so speed has to grow with it.
        """
        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                self.assertAlmostEqual(
                    layout.speed(NOMINAL),
                    NOMINAL * layout.travel / DESIGN_TRAVEL,
                )
                # Uniform scale is very nearly right on a 16:9 surface — the
                # design target the constants were tuned for. Not exactly, since
                # the layout rounds each band to whole pixels, and a pixel of
                # rounding is a slightly longer fall.
                if abs(width / height - 16 / 9) < 0.02:
                    expected = NOMINAL * layout.scale
                    self.assertLess(
                        abs(layout.speed(NOMINAL) - expected) / expected, 0.01,
                        "16:9 should keep the authored uniform scaling",
                    )

    def test_a_boss_descends_and_escapes_at_every_size(self) -> None:
        from game.boss import Boss

        for width, height in DISPLAY_SIZES:
            with self.subTest(size=f"{width}x{height}"):
                layout = Layout(width, height)
                from tests.test_stage4 import make_challenge

                boss = Boss(
                    make_challenge("a" * 300, boss=True),
                    layout=layout,
                )
                boss.begin_intro()
                from game.constants import BOSS_INTRO_SECONDS

                boss.update(BOSS_INTRO_SECONDS + 0.1, layout.danger_line)
                self.assertLess(boss.y, layout.danger_line)
                start = boss.y
                for _ in range(6000):
                    boss.update(1 / 60, layout.danger_line)
                self.assertGreater(boss.y, start, "a boss must keep descending")
                self.assertTrue(boss.escaped)


class UiScaleTests(unittest.TestCase):
    """``UI`` turns design-space sizes into display pixels for the screens."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    def test_a_design_length_and_font_scale_with_the_surface(self) -> None:
        assets = self.FakeAssets()
        big = UI(assets, 1920, 1080)
        small = UI(assets, 1280, 720)

        self.assertEqual(big.width, 1920)
        self.assertEqual(big.scale, 1.5)
        self.assertEqual(big.px(100), 150, "a design length must scale at 1080p")
        self.assertEqual(small.px(100), 100)

        # A design font size must render physically larger, not just be stored
        # bigger: measure the same string at both scales.
        big_width = big.measure("CODETYPE", 20)[0]
        small_width = small.measure("CODETYPE", 20)[0]
        self.assertGreater(big_width, small_width * 1.3)
        self.assertLess(big_width, small_width * 1.7)

    def test_speed_follows_the_surface_it_was_built_for(self) -> None:
        at_1080p = Layout(1920, 1080)
        self.assertAlmostEqual(at_1080p.speed(NOMINAL), NOMINAL * 1.5, delta=0.2)

        at_720p = Layout(1280, 720)
        self.assertAlmostEqual(at_720p.speed(NOMINAL), NOMINAL, delta=0.05)


class LiveResizeTests(unittest.TestCase):
    """The window can be dragged or the resolution changed mid-run.

    Everything holding pixels has to hear about it, or the screen keeps drawing
    a layout built for a surface that no longer exists.
    """

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeSettings:
        typing_effects = True
        screen_shake = False

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    def _game(self, width, height, seconds=6.0):
        from game.game import Game

        screen = pygame.display.set_mode((width, height))
        game = Game(
            screen=screen,
            settings=self.FakeSettings(),
            assets=self.FakeAssets(),
            audio=self.FakeAudio(),
            mode="campaign",
            player_name="ACE",
        )
        for _ in range(int(seconds * 60)):
            game.update(1 / 60)
        game.draw(screen)
        return screen, game

    def test_a_resize_carries_the_field_with_the_layout(self) -> None:
        screen, game = self._game(1920, 1080, seconds=14.0)
        self.assertTrue(game.enemies, "the field should have enemies to move")
        before_layout = game._layout
        progress = {
            id(enemy): (enemy.y - before_layout.spawn_clearance_y) / before_layout.travel
            for enemy in game.enemies
        }

        game.draw(pygame.display.set_mode((1280, 720)))

        after_layout = game._layout
        # Mutating the layout in place would leave every enemy holding the new
        # scale already, so rebase() would see a ratio of 1.0 and nothing would
        # move: a card mid-field would end up sitting on the new danger line.
        self.assertIsNot(after_layout, before_layout)
        for enemy in game.enemies:
            moved = (enemy.y - after_layout.spawn_clearance_y) / after_layout.travel
            self.assertAlmostEqual(moved, progress[id(enemy)], delta=0.02)
            self.assertLess(enemy.y, after_layout.danger_line)

    def test_the_speed_cap_does_not_ratchet_across_a_resize(self) -> None:
        screen, game = self._game(1920, 1080, seconds=14.0)
        enemy = game.enemies[0]

        def expected_cap():
            queue = max(1.0, game._queue_typing_seconds(enemy))
            travel = max(1.0, game._danger_line - enemy.y)
            return min(enemy.nominal_speed, travel / queue)

        # The cap is a function of where the enemy is and what is queued ahead
        # of it, with no memory of the sizes the window has been through. A cap
        # carried over from the previous size shows up here as a speed below it.
        for size in ((1280, 720), (1920, 1080), (1280, 720), (1920, 1080)):
            game.draw(pygame.display.set_mode(size))
            self.assertAlmostEqual(enemy.speed, expected_cap(), delta=0.01,
                                   msg=f"cap does not match the position at {size}")

    def test_a_boss_keeps_descending_across_a_resize(self) -> None:
        from game.boss import Boss
        from tests.test_stage4 import make_challenge

        _, game = self._game(1920, 1080, seconds=2.0)
        layout = game._layout
        boss = Boss(
            make_challenge("x = compute()" * 30, boss=True),
            layout=layout,
        )
        game._enemies.append(boss)
        boss.begin_intro()
        from game.constants import BOSS_INTRO_SECONDS

        boss.update(BOSS_INTRO_SECONDS + 0.1, layout.danger_line)
        for _ in range(120):
            boss.update(1 / 60, layout.danger_line)

        # Resizing must rescale the boss, keep it inside the new field, and let
        # it carry on descending rather than snapping to a stale position.
        game.draw(pygame.display.set_mode((1280, 720)))
        self.assertLess(boss.y, game._layout.danger_line)
        self.assertGreaterEqual(boss.x, -boss.width)
        self.assertLessEqual(boss.x + boss.width, game._layout.width)

        mid = boss.y
        for _ in range(120):
            boss.update(1 / 60, game._layout.danger_line)
        self.assertGreater(boss.y, mid, "the boss must keep descending after a resize")

    def test_a_run_survives_a_resize_mid_flight(self) -> None:
        screen, game = self._game(1920, 1080)
        self.assertTrue(game.enemies, "the field should have enemies to move")

        pygame.display.set_mode((1280, 720))
        screen = pygame.display.get_surface()
        game.draw(screen)

        self.assertEqual((game._ui.width, game._ui.height), (1280, 720))
        self.assertEqual(game._layout.scale, 1.0)
        # The stage must follow, or the backdrop is still drawn for the old
        # window while everything else is laid out for the new one.
        self.assertFalse(
            game._stage.stale(screen),
            "the stage still points at the pre-resize UI",
        )

        # No card may be left outside the new surface or absurdly sized.
        for enemy in game.enemies:
            self.assertGreaterEqual(enemy.x, -enemy.width)
            self.assertLessEqual(enemy.x + enemy.width, 1280)
            self.assertAlmostEqual(enemy.width, 390, delta=1)
            self.assertGreater(enemy.speed, 0.0)

        # And it must keep running afterwards.
        for _ in range(60):
            game.update(1 / 60)
        game.draw(screen)

    def test_resizing_twice_returns_to_the_authored_scale(self) -> None:
        screen, game = self._game(1920, 1080)
        for width, height in ((1280, 720), (2560, 1440), (1920, 1080)):
            pygame.display.set_mode((width, height))
            screen = pygame.display.get_surface()
            game.draw(screen)
            self.assertEqual(game._layout.scale, scale_for(width, height))
        self.assertAlmostEqual(game._layout.scale, 1.5)
        self.assertAlmostEqual(game._layout.speed(NOMINAL), NOMINAL * 1.5, delta=0.2)

    def test_a_boss_keeps_its_lane_across_a_resize(self) -> None:
        from game.boss import Boss
        from tests.test_stage4 import make_challenge

        layout = Layout(1920, 1080)
        boss = Boss(
            make_challenge("a" * 300, boss=True),
            station=0.5,
            layout=layout,
        )
        lane = boss.station
        boss.begin_intro()

        smaller = Layout(1280, 720)
        boss.rebase(smaller)
        self.assertAlmostEqual(boss.station, lane, places=5)
        self.assertAlmostEqual(
            boss.x, smaller.column_x(boss.width, lane), places=5
        )
        self.assertAlmostEqual(
            boss.width, smaller.enemy_width + smaller.boss_width_bonus, places=5
        )

    def test_a_stage_reports_staleness_and_adopts_a_new_ui(self) -> None:
        from game.ui import Stage

        assets = self.FakeAssets()
        ui = UI(assets, 1920, 1080)
        stage = Stage(ui)
        screen = pygame.display.set_mode((1920, 1080))
        self.assertFalse(stage.stale(screen))

        pygame.display.set_mode((1280, 720))
        screen = pygame.display.get_surface()
        self.assertTrue(stage.stale(screen), "a resize must be noticed")

        # rebind is what the owner calls after rebuilding its own UI.
        new_ui = UI(assets, 1280, 720)
        stage.rebind(new_ui)
        self.assertFalse(stage.stale(screen))
        stage.draw(screen, 1.0)  # must not raise with a mismatched cached size


class ScreenResizeTests(unittest.TestCase):
    """A screen that built its UI once must notice the window moved.

    The screens cannot fix this themselves in the abstract: each one has to ask
    its stage whether it is stale and rebuild. This drives the real screens.
    """

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        width = 1920
        height = 1080
        fullscreen = False
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = False

        def save(self):
            pass

    def _screens(self, screen, assets, audio, settings):
        from screens.game_over_screen import GameOverScreen
        from screens.leaderboard_screen import LeaderboardScreen
        from screens.main_menu import MainMenuScreen
        from screens.name_input_screen import NameInputScreen
        from screens.settings_screen import SettingsScreen

        stats = {
            "player_name": "ACE", "mode": "campaign", "score": 1234, "wpm": 42.5,
            "accuracy": 97.5, "max_combo": 12, "best_wpm": 61.0, "waves": 3,
            "enemies": 7, "bosses": 1, "victory": False,
        }
        return [
            MainMenuScreen(screen, settings, assets, audio, None),
            SettingsScreen(screen, settings, assets, audio),
            LeaderboardScreen(screen, settings, assets, audio, None),
            GameOverScreen(screen, settings, assets, audio, None, stats),
            NameInputScreen(screen, settings, assets, audio, None, "campaign"),
        ]

    def test_every_screen_rebuilds_when_the_window_changes_size(self) -> None:
        screen = pygame.display.set_mode((1920, 1080))
        assets, audio = self.FakeAssets(), self.FakeAudio()
        for view in self._screens(screen, assets, audio, self.FakeSettings()):
            with self.subTest(screen=type(view).__name__):
                self.assertEqual(view._ui.width, 1920)
                view._draw()
                self.assertFalse(view._stage.stale(screen))

                pygame.display.set_mode((1280, 720))
                small = pygame.display.get_surface()
                view._screen = small
                # No rebuild call from the screen: the draw has to notice.
                view._draw()
                self.assertEqual(view._ui.width, 1280)
                self.assertEqual(view._ui.height, 720)
                self.assertFalse(view._stage.stale(small))
                self.assertEqual(view._ui.px(100), 100)

                pygame.display.set_mode((1920, 1080))
                big = pygame.display.get_surface()
                view._screen = big
                view._draw()
                self.assertEqual(view._ui.px(100), 150)


    def test_the_content_error_state_rebuilds_too(self) -> None:
        """The error state is drawn by the screen, so it owns a UI as well."""
        from screens.game_screen import GameScreen

        screen = pygame.display.set_mode((1920, 1080))
        view = GameScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            None, "campaign", "ACE",
        )
        # Force the failure branch; the happy path draws inside Game instead.
        view._game = None
        view._error = "snippet library missing"
        view._draw_error()

        pygame.display.set_mode((1280, 720))
        small = pygame.display.get_surface()
        view._screen = small
        view._draw_error()
        self.assertEqual(view._ui.width, 1280)
        self.assertFalse(view._stage.stale(small))


class BackdropTests(unittest.TestCase):
    """The wash under every menu-type screen has to cover the whole surface.

    It used to be drawn one slanted line per band, so consecutive bands were
    parallel lines a step apart and the surface between them was never painted.
    At 1080p that left 96% of the surface showing whatever had been drawn
    before: invisible on a fresh launch, because the window behind is black, and
    glaring the moment a menu was composited over a gameplay frame.
    """

    SENTINEL = (255, 0, 255)
    SIZES = WINDOW_PRESETS + ((1024, 768), (960, 540), (3440, 720))

    def _ui(self, width, height):
        class FakeAssets:
            def font(self, size, bold=False):
                return pygame.font.Font(None, max(8, size))

        return UI(FakeAssets(), width, height)

    def _surviving(self, surface, width, height):
        return sum(
            1
            for x in range(0, width, 2)
            for y in range(0, height, 2)
            if surface.get_at((x, y))[:3] == self.SENTINEL
        )

    def test_the_wash_leaves_no_previous_pixels_showing(self) -> None:
        for width, height in self.SIZES:
            with self.subTest(size=f"{width}x{height}"):
                surface = pygame.Surface((width, height))
                surface.fill(self.SENTINEL)
                self._ui(width, height).backdrop_fill(surface)
                self.assertEqual(
                    self._surviving(surface, width, height), 0,
                    f"the wash left the previous screen visible at {width}x{height}",
                )

    def test_the_wash_reaches_both_edges_and_is_opaque(self) -> None:
        """A band drawn short would leave a seam along an edge or a row."""
        width, height = 1920, 1080
        surface = pygame.Surface((width, height))
        surface.fill(self.SENTINEL)
        self._ui(width, height).backdrop_fill(surface)

        for point in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
            self.assertNotEqual(surface.get_at(point)[:3], self.SENTINEL)
        for x in (0, width // 2, width - 1):
            for y in (0, height // 2, height - 1):
                self.assertEqual(
                    surface.get_at((x, y))[3], 255, f"pixel {(x, y)} is not opaque"
                )
        # Top of the wash is lighter than the bottom, and nothing is brighter
        # than the top colour: a band drawn over the wrong rows would break the
        # ordering.
        self.assertGreater(
            sum(surface.get_at((width // 2, 0))[:3]),
            sum(surface.get_at((width // 2, height - 1))[:3]),
        )

    def test_a_menu_drawn_over_a_run_looks_the_same_as_over_black(self) -> None:
        """The symptom, end to end: your HUD bleeding through the main menu.

        Byte comparison rather than a brightness threshold, so there is nothing
        to tune. The starfield is seeded and the animation state pinned because
        both screens have to be otherwise identical for this to mean anything.
        """
        import random

        from game.game import Game
        from screens.main_menu import MainMenuScreen, _MENU_ITEMS

        class FakeAssets:
            def font(self, size, bold=False):
                return pygame.font.Font(None, max(8, size))

        class FakeAudio:
            def play(self, slot):
                pass

            def update_volumes(self):
                pass

        class FakeSettings:
            fullscreen = False
            width, height = 1920, 1080
            master_volume = 0.8
            music_volume = 0.5
            sfx_volume = 0.8
            typing_effects = True
            screen_shake = True

            def save(self):
                pass

        width, height = 1920, 1080
        assets, audio, settings = FakeAssets(), FakeAudio(), FakeSettings()

        # A real gameplay frame, enemies and HUD included.
        played = pygame.Surface((width, height))
        game = Game(
            screen=played, settings=settings, assets=assets, audio=audio,
            mode="campaign", player_name="ACE",
        )
        for _ in range(240):
            game.update(1 / 60)
        game.draw(played)
        self.assertTrue(game.enemies, "the run produced no enemies to ghost")

        black = pygame.Surface((width, height))

        def draw_menu_onto(surface):
            random.seed(1234)
            menu = MainMenuScreen(surface, settings, assets, audio, None)
            menu._selected = 1
            menu._tick = 0.5
            menu._warmth = [1.0 if i == 1 else 0.0 for i in range(len(_MENU_ITEMS))]
            menu._draw()
            return pygame.image.tobytes(surface, "RGB")

        over_run = draw_menu_onto(played)
        over_black = draw_menu_onto(black)
        self.assertEqual(
            over_run, over_black,
            "the main menu let the finished run show through it",
        )


class ScreenDrawTests(unittest.TestCase):
    """Every screen has to survive being drawn on any window the app allows.

    Resizing tells you a screen *rebuilds*; it does not tell you that what it
    then draws is on-screen and inside the surface. This is the draw pass over
    the whole set of screens, at every preset plus two awkward aspect ratios
    that are deliberately not presets: a 4:3 window is much shorter than the
    design surface, and a very wide one is mostly empty.
    """

    SIZES = WINDOW_PRESETS + ((1024, 768), (3440, 720))

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        fullscreen = False
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = True

        def __init__(self, width, height):
            self.width, self.height = width, height

        def save(self):
            pass

    class FakeLeaderboard:
        def get_top(self, limit=10, sort_by="score"):
            return [
                {"player_name": "ACE", "score": 184320, "wpm": 118.4,
                 "accuracy": 97.2, "mode": "campaign"},
                {"player_name": "BYTEWITCH", "score": 141002, "wpm": 104.0,
                 "accuracy": 99.1, "mode": "endless"},
                {"player_name": "Kai", "score": 98450, "wpm": 96.7,
                 "accuracy": 94.0, "mode": "competition"},
            ][:limit]

        def save_score(self, **kwargs):
            pass

        def reset(self):
            pass

    STATS = {
        "player_name": "ACE", "mode": "campaign", "score": 184320, "wpm": 118.4,
        "accuracy": 97.2, "max_combo": 23, "best_wpm": 141.0, "waves": 7,
        "enemies": 96, "bosses": 3, "victory": True,
    }

    # Measured across the sizes above, the quietest screen is the live game
    # letterboxed into 3440x720: the field is a 1280-wide column in a very wide,
    # very short surface, so almost everything on it is empty. With the starfield
    # and enemy placement unseeded it lands anywhere in 0.3-0.7% of sampled
    # pixels, where every other screen is above 1.8% and the busiest is 2.7%.
    # 0.2% therefore sits clear of the noisy floor without being loose enough to
    # stop catching a screen that drew nothing. This is a "did anything reach
    # the surface" check only: it cannot see one element missing from an
    # otherwise-drawn screen, and it says nothing about what was under the screen
    # beforehand, which is what BackdropTests covers.
    MIN_LIT = 0.002

    @classmethod
    def _lit_ratio(cls, surface) -> float:
        """Fraction of sampled pixels bright enough to be drawn content.

        Sampled on a grid rather than pixel by pixel: this is a smoke check for
        "did anything reach the surface", not an image comparison, and the grid
        keeps it fast enough to run on every screen at every size.
        """
        small = pygame.transform.smoothscale(surface, (80, 45))
        width, height = small.get_size()
        total = lit = 0
        for x in range(0, width, 2):
            for y in range(0, height, 2):
                red, green, blue = small.get_at((x, y))[:3]
                total += 1
                if red + green + blue > 90:
                    lit += 1
        return lit / total

    def test_every_screen_draws_at_every_size(self) -> None:
        from screens.game_over_screen import GameOverScreen
        from screens.game_screen import GameScreen
        from screens.leaderboard_screen import LeaderboardScreen
        from screens.main_menu import MainMenuScreen
        from screens.name_input_screen import NameInputScreen
        from screens.settings_screen import SettingsScreen

        assets, audio = self.FakeAssets(), self.FakeAudio()
        for width, height in self.SIZES:
            screen = pygame.display.set_mode((width, height))
            settings = self.FakeSettings(width, height)
            leaderboard = self.FakeLeaderboard()
            views = [
                ("menu", MainMenuScreen(screen, settings, assets, audio, leaderboard)),
                ("settings", SettingsScreen(screen, settings, assets, audio)),
                (
                    "leaderboard",
                    LeaderboardScreen(screen, settings, assets, audio, leaderboard),
                ),
                (
                    "gameover",
                    GameOverScreen(
                        screen, settings, assets, audio, leaderboard, dict(self.STATS)
                    ),
                ),
                (
                    "name",
                    NameInputScreen(
                        screen, settings, assets, audio, leaderboard, "competition"
                    ),
                ),
            ]
            for name, view in views:
                with self.subTest(size=f"{width}x{height}", screen=name):
                    # Drive each screen into its busiest state, not its default
                    # one: a reset prompt, a typed name, a highlighted row.
                    if name == "menu":
                        view._selected = 1
                    elif name == "settings":
                        view._selected = 3
                    elif name == "leaderboard":
                        view._confirm_reset = True
                    elif name == "name":
                        view._name = "ACE"
                    view._draw()
                    pygame.display.flip()
                    self.assertGreater(
                        self._lit_ratio(screen), self.MIN_LIT,
                        f"{name} drew nothing visible at {width}x{height}",
                    )
                    # The pixel check above cannot tell "laid out for this
                    # surface" from "drew something in roughly the right place",
                    # so state the layout invariant directly: a screen holding a
                    # UI for another resolution still draws, just wrongly.
                    self.assertEqual(
                        (view._ui.width, view._ui.height), (width, height),
                        f"{name} kept a UI built for another surface",
                    )
            # The live game draws itself, so it needs a few seconds of run first
            # for there to be enemies, particles, and a HUD worth drawing.
            with self.subTest(size=f"{width}x{height}", screen="play"):
                view = GameScreen(
                    screen, settings, assets, audio, leaderboard, "campaign", "ACE"
                )
                game = view._game
                self.assertIsNotNone(game, "the live game failed to build")
                for _ in range(360):
                    game.update(1 / 60)
                game.draw(screen)
                game.draw(screen)  # and again, now the UI is warm
                pygame.display.flip()
                self.assertGreater(
                    self._lit_ratio(screen), self.MIN_LIT,
                    f"the live game drew nothing visible at {width}x{height}",
                )
                self.assertEqual(
                    (game._ui.width, game._ui.height), (width, height),
                    "the live game did not lay itself out for the surface",
                )


class LeaderboardFilterTests(unittest.TestCase):
    """The mode filter is a real dropdown: it opens, navigates, clicks, and the
    selection it commits has to actually narrow the rows the screen reads."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        fullscreen = False
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = True

        def __init__(self, width=1280, height=720):
            self.width, self.height = width, height

        def save(self):
            pass

    class ModeAwareBoard:
        """A leaderboard whose get_top accepts the mode keyword."""

        def __init__(self, rows):
            self.rows = rows
            self.calls = []

        def get_top(self, limit=10, sort_by="score", mode=None):
            self.calls.append((limit, sort_by, mode))
            rows = [r for r in self.rows if mode is None or r["mode"] == mode]
            return sorted(rows, key=lambda r: r["score"], reverse=True)[:limit]

    class LegacyBoard:
        """A pre-mode backend; get_top only understands limit and sort_by."""

        def __init__(self, rows):
            self.rows = rows

        def get_top(self, limit=10, sort_by="score"):
            return self.rows[:limit]

    ROWS = (
        {"player_name": "ACE", "score": 900, "wpm": 90.0,
         "accuracy": 99.0, "mode": "campaign"},
        {"player_name": "BOT", "score": 800, "wpm": 80.0,
         "accuracy": 98.0, "mode": "endless"},
        {"player_name": "CAT", "score": 700, "wpm": 70.0,
         "accuracy": 97.0, "mode": "competition"},
    )

    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    def _view(self, board=None):
        from screens.leaderboard_screen import LeaderboardScreen

        if board is None:
            board = self.ModeAwareBoard([dict(r) for r in self.ROWS])
        screen = pygame.display.set_mode((1280, 720))
        return LeaderboardScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(), board
        )

    def test_clicking_the_control_opens_it_and_an_option_filters(self) -> None:
        board = self.ModeAwareBoard([dict(r) for r in self.ROWS])
        view = self._view(board)
        self.assertEqual(len(view._rows), 3, "the board starts unfiltered")

        self.assertTrue(view._handle_click(view._filter_rect().center))
        self.assertTrue(view._filter_open, "clicking the control opens the menu")

        # Option 2 is ENDLESS (index matches _FILTER_OPTIONS).
        view._handle_click(view._filter_option_rects()[2].center)
        self.assertFalse(view._filter_open, "choosing an option closes the menu")
        self.assertEqual(view._filter_index, 2)
        self.assertEqual([r["mode"] for r in view._rows], ["endless"])

    def test_keyboard_opens_navigates_and_commits(self) -> None:
        view = self._view()
        view._open_filter()
        self.assertTrue(view._filter_open)
        self.assertEqual(view._filter_hover, view._filter_index)

        view._move_filter(1)
        view._move_filter(1)
        self.assertEqual(view._filter_hover, 2)
        view._commit_filter(view._filter_hover)

        self.assertFalse(view._filter_open)
        self.assertEqual(view._filter_index, 2)
        self.assertEqual([r["mode"] for r in view._rows], ["endless"])

    def test_a_click_away_dismisses_the_menu_without_changing_the_mode(self) -> None:
        view = self._view()
        view._open_filter()
        view._handle_click((5, 5))
        self.assertFalse(view._filter_open)
        self.assertEqual(view._filter_index, 0, "click-away must not pick a mode")

    def test_a_legacy_board_is_filtered_in_python(self) -> None:
        board = self.LegacyBoard([dict(r) for r in self.ROWS])
        view = self._view(board)
        self.assertEqual(len(view._rows), 3)
        view._commit_filter(2)  # ENDLESS
        self.assertEqual([r["mode"] for r in view._rows], ["endless"])

    def test_escape_closes_the_menu_before_leaving_the_screen(self) -> None:
        view = self._view()
        view._open_filter()
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        result = view.run(pygame.time.Clock())
        self.assertIsNone(
            result, "Escape should close the menu, not return to the main menu"
        )
        self.assertFalse(view._filter_open)

    def test_the_open_menu_draws(self) -> None:
        view = self._view()
        view._open_filter()
        view._draw()  # must not raise with the option list showing


class FullscreenHotkeyTests(unittest.TestCase):
    """F11 has to reach every screen, and must not cost you your window size.

    A display change hands the screens a *new* surface and invalidates the old
    one, so a screen that keeps its old reference is drawing into nothing. And
    toggling in and out has to land back on the window the user chose rather
    than on the size fullscreen happened to be.
    """

    WINDOW = (1280, 720)

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        fullscreen = False
        width, height = 1280, 720
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = True

        def save(self):
            pass

    def _menu(self):
        from screens.main_menu import MainMenuScreen

        screen = pygame.display.set_mode(self.WINDOW)
        settings = self.FakeSettings()
        view = MainMenuScreen(
            screen, settings, self.FakeAssets(), self.FakeAudio(), None
        )
        return view, settings

    def test_f11_adopts_the_new_surface_and_rebuilds(self) -> None:
        view, settings = self._menu()

        view._toggle_fullscreen()
        self.assertTrue(settings.fullscreen)
        self.assertIs(
            view._screen, pygame.display.get_surface(),
            "the screen is still holding the invalidated surface",
        )
        self.assertEqual(
            (view._ui.width, view._ui.height), view._screen.get_size(),
            "the UI was not rebuilt for the new surface",
        )

    def test_toggling_back_returns_to_the_stored_window_size(self) -> None:
        view, settings = self._menu()

        view._toggle_fullscreen()
        view._toggle_fullscreen()

        self.assertFalse(settings.fullscreen)
        self.assertEqual(
            (settings.width, settings.height), self.WINDOW,
            "leaving fullscreen overwrote the window size the user chose",
        )
        self.assertEqual(
            (view._ui.width, view._ui.height), view._screen.get_size(),
            "the UI no longer matches the surface it is drawing on",
        )

    def test_the_menu_keeps_its_selection_across_a_toggle(self) -> None:
        view, _ = self._menu()
        view._selected = 2
        view._tick = 1.5

        view._toggle_fullscreen()
        view._toggle_fullscreen()

        self.assertEqual(view._selected, 2)
        self.assertEqual(view._tick, 1.5)

    def test_every_screen_handles_the_hotkey(self) -> None:
        """Not just the menu: F11 should work wherever the player happens to be."""
        from game.display import toggle_fullscreen
        from screens.game_over_screen import GameOverScreen
        from screens.game_screen import GameScreen
        from screens.leaderboard_screen import LeaderboardScreen
        from screens.name_input_screen import NameInputScreen
        from screens.settings_screen import SettingsScreen

        settings = self.FakeSettings()
        assets, audio = self.FakeAssets(), self.FakeAudio()
        screen = pygame.display.set_mode(self.WINDOW)
        stats = {
            "player_name": "ACE", "mode": "campaign", "score": 10, "wpm": 1.0,
            "accuracy": 1.0, "max_combo": 1, "best_wpm": 1.0, "waves": 1,
            "enemies": 1, "bosses": 0, "victory": False,
        }
        views = [
            SettingsScreen(screen, settings, assets, audio),
            LeaderboardScreen(screen, settings, assets, audio, None),
            GameOverScreen(screen, settings, assets, audio, None, stats),
            NameInputScreen(screen, settings, assets, audio, None, "campaign"),
            GameScreen(screen, settings, assets, audio, None, "campaign", "ACE"),
        ]
        try:
            for view in views:
                with self.subTest(screen=type(view).__name__):
                    settings.fullscreen = False
                    view._toggle_fullscreen()
                    self.assertTrue(settings.fullscreen)
                    self.assertIs(
                        view._screen, pygame.display.get_surface(),
                        "the screen is still holding the invalidated surface",
                    )
                    self.assertEqual(
                        (view._ui.width, view._ui.height),
                        view._screen.get_size(),
                    )
                    settings.fullscreen = True
                    view._toggle_fullscreen()
                    self.assertFalse(settings.fullscreen)
                    self.assertIs(view._screen, pygame.display.get_surface())
        finally:
            settings.fullscreen = False
            # set_mode rather than toggle_fullscreen: toggling would flip the
            # flag back on and leave the next test drawing fullscreen.
            pygame.display.set_mode(self.WINDOW)

    def test_the_key_is_bound_in_every_run_loop(self) -> None:
        """Calling the handler is not the same as pressing the key.

        A screen can have a perfectly good ``_toggle_fullscreen`` and still never
        reach it, because the F11 branch in its run loop is missing or sits
        behind a modal that swallows the event. So post the key and let each
        screen's own loop run.
        """
        from game.display import toggle_fullscreen
        from screens.game_over_screen import GameOverScreen
        from screens.game_screen import GameScreen
        from screens.leaderboard_screen import LeaderboardScreen
        from screens.main_menu import MainMenuScreen
        from screens.name_input_screen import NameInputScreen
        from screens.settings_screen import SettingsScreen

        settings = self.FakeSettings()
        assets, audio = self.FakeAssets(), self.FakeAudio()
        screen = pygame.display.set_mode(self.WINDOW)
        stats = {
            "player_name": "ACE", "mode": "campaign", "score": 10, "wpm": 1.0,
            "accuracy": 1.0, "max_combo": 1, "best_wpm": 1.0, "waves": 1,
            "enemies": 1, "bosses": 0, "victory": False,
        }
        builders = {
            "menu": lambda: MainMenuScreen(screen, settings, assets, audio, None),
            "settings": lambda: SettingsScreen(screen, settings, assets, audio),
            "leaderboard": lambda: LeaderboardScreen(
                screen, settings, assets, audio, None
            ),
            "gameover": lambda: GameOverScreen(
                screen, settings, assets, audio, None, stats
            ),
            "name": lambda: NameInputScreen(
                screen, settings, assets, audio, None, "campaign"
            ),
            "play": lambda: GameScreen(
                screen, settings, assets, audio, None, "campaign", "ACE"
            ),
        }
        clock = pygame.time.Clock()
        try:
            for name, build in builders.items():
                with self.subTest(screen=name):
                    settings.fullscreen = False
                    view = build()
                    pygame.event.clear()
                    # F11 then QUIT: the toggle runs, and the QUIT ends the loop.
                    pygame.event.post(
                        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11)
                    )
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    view.run(clock)
                    self.assertTrue(
                        settings.fullscreen,
                        f"{name} ignored the F11 key event",
                    )
                    self.assertIs(
                        view._screen, pygame.display.get_surface(),
                        f"{name} did not adopt the new surface on F11",
                    )
                    settings.fullscreen = True
                    toggle_fullscreen(settings)
        finally:
            pygame.event.clear()
            settings.fullscreen = False
            pygame.display.set_mode(self.WINDOW)


class QueuePacingTests(unittest.TestCase):
    """A spawn must not be able to outrun the work queued ahead of it.

    The cap divides the available fall by the time the player needs to clear
    this enemy *and everything already on the field*. Estimating that as
    "my own typing time x the tier's concurrency" is only correct when the
    queued snippets are all the same length, so a short enemy behind a long one
    used to arrive early and cost a life however well it was typed.
    """

    CPS = DESCENT_REFERENCE_CPS
    DANGER = 720.0 - FIELD_BOTTOM_MARGIN

    def _enemy(self, length):
        from game.enemy import Enemy
        from tests.test_stage4 import make_challenge

        return Enemy(make_challenge("a" * length), DIFFICULTY_EASY, ENEMY_NORMAL)

    def _game(self):
        from game.game import Game

        class FakeAssets:
            def font(self, size, bold=False):
                return pygame.font.Font(None, max(8, size))

        class FakeAudio:
            def play(self, slot):
                pass

            def update_volumes(self):
                pass

        class FakeSettings:
            typing_effects = True
            screen_shake = False

        screen = pygame.display.set_mode((1920, 1080))
        return Game(
            screen=screen, settings=FakeSettings(), assets=FakeAssets(),
            audio=FakeAudio(), mode="campaign", player_name="ACE",
        )

    def test_a_short_enemy_behind_a_long_one_gets_extra_time(self) -> None:
        long_ahead = self._enemy(200)
        short_behind = self._enemy(40)

        # What the player must clear before the newcomer crosses: both snippets.
        real_work = (len(long_ahead.text) + len(short_behind.text)) / self.CPS
        short_behind.limit_speed_for(self.DANGER, queue_seconds=real_work)
        time_to_line = (self.DANGER - short_behind.y) / short_behind.speed
        self.assertGreaterEqual(
            time_to_line, real_work,
            "a short enemy behind a long one must be given the real queue time",
        )

    def test_the_old_estimate_would_have_been_short(self) -> None:
        """Guards the reason the bug existed: the estimate is not conservative."""
        from game.difficulty import get_profile

        long_ahead = self._enemy(200)
        short_behind = self._enemy(40)
        queued = max(1, get_profile(DIFFICULTY_EASY).max_active)
        estimate = (len(short_behind.text) / self.CPS) * queued
        real_work = (len(long_ahead.text) + len(short_behind.text)) / self.CPS
        self.assertLess(
            estimate, real_work,
            "if this ever holds, the fallback estimate is no longer the weak link",
        )

    def test_an_empty_field_needs_no_extra_time(self) -> None:
        alone = self._enemy(60)
        work = len(alone.text) / self.CPS
        alone.limit_speed_for(self.DANGER, queue_seconds=work)
        time_to_line = (self.DANGER - alone.y) / alone.speed
        # The cap is a ceiling, not a target: an enemy already slower than the
        # work requires keeps its nominal speed and gains slack.
        self.assertGreaterEqual(time_to_line, work)

    def test_a_boss_is_capped_like_any_other_enemy(self) -> None:
        from game.boss import Boss
        from tests.test_stage4 import make_challenge

        boss = Boss(make_challenge("a" * 500, boss=True), start_y=0.0)
        boss.limit_speed_for(self.DANGER)
        self.assertTrue(boss.speed_limited, "a boss must respect the fairness cap")
        self.assertLess(boss.speed, boss.nominal_speed)
        travel = self.DANGER - boss.y
        self.assertGreaterEqual(travel / boss.speed, len(boss.text) / self.CPS)

    def test_the_game_sums_the_live_queue_when_spawning(self) -> None:
        """The caller must pass the real total, not leave it to the fallback.

        Driven through a real ``Game`` so that putting something on the field and
        asking for the queue time actually has to notice it.
        """
        game = self._game()
        long_ahead = self._enemy(200)
        short_behind = self._enemy(40)

        # An empty field: just the newcomer's own work.
        self.assertAlmostEqual(
            game._queue_typing_seconds(short_behind),
            len(short_behind.text) / self.CPS,
            places=5,
        )

        # With something long already falling, the newcomer must be told about it.
        game._enemies.append(long_ahead)
        both = game._queue_typing_seconds(short_behind)
        self.assertAlmostEqual(
            both,
            (len(long_ahead.text) + len(short_behind.text)) / self.CPS,
            places=5,
        )
        self.assertGreater(both, len(short_behind.text) / self.CPS)

        # A dead enemy is no longer work, so it must not be counted.
        long_ahead.alive = False
        self.assertAlmostEqual(
            game._queue_typing_seconds(short_behind),
            len(short_behind.text) / self.CPS,
            places=5,
        )

    def test_rechecking_a_live_enemy_does_not_count_it_twice(self) -> None:
        """The resize path re-checks enemies that are already on the field.

        There the enemy being checked is part of the on-field queue, so counting
        the field *and* adding the enemy again would report more work than
        exists. It would not cost the player a life — the cap is one-sided, so
        the error only ever slows an enemy down — but because the cap is sticky
        that slack accumulates over a session of resizes.
        """
        game = self._game()
        long_ahead = self._enemy(200)
        short_behind = self._enemy(40)
        game._enemies.extend([long_ahead, short_behind])

        self.assertAlmostEqual(
            game._queue_typing_seconds(short_behind),
            (len(long_ahead.text) + len(short_behind.text)) / self.CPS,
            places=5,
        )

    def test_a_real_spawn_behind_a_long_enemy_is_slowed_to_match(self) -> None:
        """The same guarantee, checked through the actual spawn path.

        Rather than trusting that ``_spawn_enemies`` passes the right argument,
        put a long enemy on the field, force the next spawn, and check that
        whatever arrived is slow enough to be clearable behind it.
        """
        from game.game import Game

        class FakeAssets:
            def font(self, size, bold=False):
                return pygame.font.Font(None, max(8, size))

        class FakeAudio:
            def play(self, slot):
                pass

            def update_volumes(self):
                pass

        class FakeSettings:
            typing_effects = True
            screen_shake = False

        screen = pygame.display.set_mode((1920, 1080))
        game = Game(
            screen=screen, settings=FakeSettings(), assets=FakeAssets(),
            audio=FakeAudio(), mode="campaign", player_name="ACE",
        )
        danger = game._danger_line
        long_ahead = self._enemy(300)
        # Put it low in the field so it does not read as "crowded" and block
        # the spawn we are trying to provoke.
        long_ahead.y = danger - 60.0
        game._enemies.append(long_ahead)

        before = len(game._enemies)
        game._wave_manager._spawn_timer = -1.0
        game.update(1 / 60)
        self.assertGreater(
            len(game._enemies), before, "the forced spawn did not happen"
        )

        spawned = game._enemies[-1]
        work = (len(long_ahead.text) + len(spawned.text)) / self.CPS
        time_to_line = (danger - spawned.y) / max(0.001, spawned.speed)
        self.assertGreaterEqual(
            time_to_line, work,
            "a real spawn behind a long enemy must be slow enough to be fair",
        )


class CompetitionTargetTests(unittest.TestCase):
    """Competition mode resolves the score it has to beat, defensively."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        typing_effects = True
        screen_shake = False

    def _game(self, mode, leaderboard, player_name="ACE"):
        from game.game import Game

        screen = pygame.display.set_mode((1920, 1080))
        return Game(
            screen=screen, settings=self.FakeSettings(), assets=self.FakeAssets(),
            audio=self.FakeAudio(), mode=mode, player_name=player_name,
            leaderboard=leaderboard,
        )

    class ModeAwareBoard:
        """A leaderboard whose get_top accepts the mode keyword."""

        def __init__(self, rows):
            self._rows = rows
            self.calls = []

        def get_top(self, limit=10, sort_by="score", mode=None):
            self.calls.append((limit, sort_by, mode))
            rows = [r for r in self._rows if mode is None or r["mode"] == mode]
            return rows[:limit]

    class LegacyBoard:
        """A pre-mode leaderboard; get_top only understands limit and sort_by."""

        def __init__(self, rows):
            self._rows = rows

        def get_top(self, limit=10, sort_by="score"):
            return self._rows[:limit]

    def test_competition_reads_the_top_competition_rival(self) -> None:
        board = self.ModeAwareBoard([
            {"player_name": "CAM", "score": 999999, "mode": "campaign"},
            {"player_name": "RIVAL", "score": 120000, "mode": "competition"},
            {"player_name": "ME", "score": 90000, "mode": "competition"},
        ])
        game = self._game("competition", board)
        self.assertEqual(game._rival_name, "RIVAL")
        self.assertEqual(game._rival_score, 120000)
        self.assertEqual(board.calls, [(10, "score", "competition")])

    def test_the_current_player_is_excluded_from_the_target(self) -> None:
        # The player's own earlier run tops the competition board; the target
        # must fall through to the best score belonging to someone else.
        board = self.ModeAwareBoard([
            {"player_name": "ACE", "score": 250000, "mode": "competition"},
            {"player_name": "RIVAL", "score": 120000, "mode": "competition"},
        ])
        game = self._game("competition", board, player_name="ACE")
        self.assertEqual(game._rival_name, "RIVAL")
        self.assertEqual(game._rival_score, 120000)

    def test_self_only_board_leaves_no_rival(self) -> None:
        board = self.ModeAwareBoard([
            {"player_name": "ace", "score": 250000, "mode": "competition"},
        ])
        game = self._game("competition", board, player_name="ACE")
        self.assertIsNone(game._rival_name)
        self.assertIsNone(game._rival_score)

    def test_a_legacy_board_is_filtered_in_python(self) -> None:
        board = self.LegacyBoard([
            {"player_name": "CAM", "score": 999999, "mode": "campaign"},
            {"player_name": "RIVAL", "score": 120000, "mode": "competition"},
        ])
        game = self._game("competition", board)
        self.assertEqual(game._rival_name, "RIVAL")
        self.assertEqual(game._rival_score, 120000)

    def test_other_modes_never_query_the_board(self) -> None:
        board = self.ModeAwareBoard([
            {"player_name": "RIVAL", "score": 120000, "mode": "competition"},
        ])
        for mode in ("campaign", "endless"):
            game = self._game(mode, board)
            self.assertIsNone(game._rival_name)
            self.assertIsNone(game._rival_score)
        self.assertEqual(board.calls, [], "the board was queried outside competition")

    def test_an_empty_or_absent_board_yields_no_target(self) -> None:
        empty = self.ModeAwareBoard([])
        on_none = self._game("competition", None)
        self.assertIsNone(on_none._rival_name)
        self.assertIsNone(on_none._rival_score)
        game = self._game("competition", empty)
        self.assertIsNone(game._rival_name)
        self.assertIsNone(game._rival_score)


class CompetitionHotSeatTests(unittest.TestCase):
    """Competition's game-over "R" hands the next run to a fresh player."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        width = 1280
        height = 720
        fullscreen = False
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = False

        def save(self):
            pass

    class Clock:
        def tick(self, fps):
            return 16

    def _press_r_on_game_over(self, mode: str):
        from screens.game_over_screen import GameOverScreen

        screen = pygame.display.set_mode((1280, 720))
        stats = {
            "player_name": "ACE", "mode": mode, "score": 1234, "wpm": 42.5,
            "accuracy": 97.5, "max_combo": 12, "best_wpm": 61.0, "waves": 3,
            "enemies": 7, "bosses": 1, "victory": False,
            "start_difficulty": "medium",
        }
        view = GameOverScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            None, stats,
        )
        pygame.event.clear()
        pygame.event.post(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r, unicode="r")
        )
        return view.run(self.Clock())

    def test_competition_play_again_asks_for_the_next_player_name(self) -> None:
        from screens.name_input_screen import NameInputScreen

        result = self._press_r_on_game_over("competition")
        self.assertIsInstance(result, NameInputScreen)
        self.assertEqual(result._mode, "competition")

    def test_other_modes_play_again_reuses_the_same_player(self) -> None:
        from screens.game_screen import GameScreen

        result = self._press_r_on_game_over("campaign")
        self.assertIsInstance(result, GameScreen)
        self.assertEqual(result._player_name, "ACE")


class EndlessNoLivesTests(unittest.TestCase):
    """Endless is endless: escapes never cost a life and never end the run."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        typing_effects = True
        screen_shake = False

    class RecordingBoard:
        def __init__(self):
            self.saved = []

        def save_score(self, **kwargs):
            self.saved.append(kwargs)
            return True

    def _game(self, mode):
        from game.game import Game

        screen = pygame.display.set_mode((1280, 720))
        return Game(
            screen=screen, settings=self.FakeSettings(), assets=self.FakeAssets(),
            audio=self.FakeAudio(), mode=mode, player_name="ACE",
        )

    @staticmethod
    def _escaped():
        import types

        return types.SimpleNamespace(x=10.0, width=20.0, y=100.0)

    def test_endless_omits_the_lives_tile(self) -> None:
        endless = [v[0] for v in self._game("endless")._hud_vitals()]
        self.assertEqual(endless, ["WPM", "ACCURACY"])
        campaign = [v[0] for v in self._game("campaign")._hud_vitals()]
        self.assertIn("LIVES", campaign)

    def test_endless_escapes_never_cost_a_life_or_end_the_run(self) -> None:
        game = self._game("endless")
        starting = game._state.player.lives
        for _ in range(starting + 5):
            game._on_enemy_escaped(self._escaped())
        self.assertEqual(game._state.player.lives, starting)
        self.assertFalse(game.finished, "an endless run must never end on its own")

    def test_campaign_escapes_still_end_the_run(self) -> None:
        game = self._game("campaign")
        for _ in range(game._state.player.lives):
            game._on_enemy_escaped(self._escaped())
        self.assertTrue(game.finished)

    def test_quitting_endless_banks_the_score(self) -> None:
        from screens.game_screen import GameScreen

        screen = pygame.display.set_mode((1280, 720))
        board = self.RecordingBoard()
        view = GameScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            board, "endless", "ACE",
        )
        view._save_run()
        self.assertEqual(len(board.saved), 1)
        self.assertEqual(board.saved[0]["mode"], "endless")
        self.assertEqual(board.saved[0]["player_name"], "ACE")


class WarmupModeTests(unittest.TestCase):
    """Warmup is a 30s, unscored practice run that drops into competition."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        width = 1280
        height = 720
        fullscreen = False
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = False

        def save(self):
            pass

    class Clock:
        def tick(self, fps):
            return 16

    class RecordingBoard:
        def __init__(self):
            self.saved = []

        def save_score(self, **kwargs):
            self.saved.append(kwargs)
            return True

    def _game(self, mode, name="ACE"):
        from game.game import Game

        screen = pygame.display.set_mode((1280, 720))
        return Game(
            screen=screen, settings=self.FakeSettings(), assets=self.FakeAssets(),
            audio=self.FakeAudio(), mode=mode, player_name=name,
        )

    @staticmethod
    def _escaped():
        import types

        return types.SimpleNamespace(x=10.0, width=20.0, y=100.0)

    def test_warmup_omits_lives_and_shows_the_clock(self) -> None:
        labels = [v[0] for v in self._game("warmup")._hud_vitals()]
        self.assertIn("TIME", labels)
        self.assertNotIn("LIVES", labels)

    def test_warmup_escapes_never_cost_a_life_or_end_the_run(self) -> None:
        game = self._game("warmup")
        starting = game._state.player.lives
        for _ in range(starting + 5):
            game._on_enemy_escaped(self._escaped())
        self.assertEqual(game._state.player.lives, starting)
        self.assertFalse(game.finished, "a warmup run must never end on a miss")

    def test_the_clock_running_out_finishes_the_run(self) -> None:
        game = self._game("warmup")
        self.assertFalse(game.finished)
        game._warmup_remaining = 0.05
        game.update(0.1)
        self.assertTrue(game.finished)
        self.assertTrue(game._victory)

    def test_warmup_spawns_without_waves_like_endless(self) -> None:
        game = self._game("warmup")
        manager = game._wave_manager
        self.assertFalse(manager.is_campaign)
        self.assertIn("WARMUP", manager.language_name.upper())
        ladder = {wave.language for wave in manager._campaign_waves}
        self.assertIn(manager.current_wave.language, ladder)

    def test_the_clock_running_out_goes_to_the_summary(self) -> None:
        from screens.game_over_screen import GameOverScreen
        from screens.game_screen import GameScreen

        screen = pygame.display.set_mode((1280, 720))
        view = GameScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            None, "warmup", "ACE", "medium",
        )
        pygame.event.clear()
        view._game._finished = True
        result = view.run(self.Clock())
        self.assertIsInstance(result, GameOverScreen)
        self.assertEqual(result._stats.get("mode"), "warmup")

    def test_quitting_warmup_banks_no_score(self) -> None:
        from screens.game_screen import GameScreen
        from screens.main_menu import MainMenuScreen

        screen = pygame.display.set_mode((1280, 720))
        board = self.RecordingBoard()
        view = GameScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            board, "warmup", "ACE",
        )
        pygame.event.clear()
        view._game._return_to_menu = True
        result = view.run(self.Clock())
        self.assertIsInstance(result, MainMenuScreen)
        self.assertEqual(board.saved, [], "warmup must not be recorded")

    def test_the_menu_offers_warmup_and_starts_it_directly(self) -> None:
        from game.constants import MODE_WARMUP
        from screens.game_screen import GameScreen
        from screens.main_menu import MainMenuScreen, _MENU_ITEMS

        labels = [item[0] for item in _MENU_ITEMS]
        self.assertIn("WARMUP", labels)

        screen = pygame.display.set_mode((1280, 720))
        menu = MainMenuScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            None,
        )
        result = menu._activate(MODE_WARMUP)
        self.assertIsInstance(result, GameScreen)
        self.assertEqual(result._mode, "warmup")
        self.assertEqual(result._player_name, "PLAYER")

    def test_the_warmup_summary_is_never_saved(self) -> None:
        from screens.game_over_screen import GameOverScreen

        screen = pygame.display.set_mode((1280, 720))
        board = self.RecordingBoard()
        stats = {
            "player_name": "PLAYER", "mode": "warmup", "score": 1234, "wpm": 42.5,
            "accuracy": 97.5, "max_combo": 12, "best_wpm": 61.0, "waves": 3,
            "enemies": 7, "bosses": 1, "victory": True,
            "start_difficulty": "medium",
        }
        view = GameOverScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            board, stats,
        )
        self.assertEqual(board.saved, [], "a warmup run must never be recorded")
        self.assertEqual(view._save_status, "skipped")
        self.assertIsNone(view._rank)


class ArcadeModeTests(unittest.TestCase):
    """Arcade is the timed score attack: 120s, no lives, kills buy seconds."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        width = 1280
        height = 720
        fullscreen = False
        master_volume = 0.8
        music_volume = 0.5
        sfx_volume = 0.8
        typing_effects = True
        screen_shake = False

        def save(self):
            pass

    class Clock:
        def tick(self, fps):
            return 16

    class RecordingBoard:
        def __init__(self):
            self.saved = []

        def save_score(self, **kwargs):
            self.saved.append(kwargs)
            return True

    def _game(self, mode="arcade", name="ACE"):
        from game.game import Game

        screen = pygame.display.set_mode((1280, 720))
        return Game(
            screen=screen, settings=self.FakeSettings(), assets=self.FakeAssets(),
            audio=self.FakeAudio(), mode=mode, player_name=name,
        )

    @staticmethod
    def _escaped():
        import types

        return types.SimpleNamespace(x=10.0, width=20.0, y=100.0)

    def test_arcade_omits_lives_and_shows_the_clock(self) -> None:
        labels = [v[0] for v in self._game()._hud_vitals()]
        self.assertIn("TIME", labels)
        self.assertNotIn("LIVES", labels)

    def test_arcade_escapes_never_cost_a_life_or_end_the_run(self) -> None:
        game = self._game()
        starting = game._state.player.lives
        for _ in range(starting + 5):
            game._on_enemy_escaped(self._escaped())
        self.assertEqual(game._state.player.lives, starting)
        self.assertFalse(game.finished, "an arcade run must never end on a miss")

    def test_the_clock_running_out_finishes_the_run_as_a_victory(self) -> None:
        game = self._game()
        self.assertFalse(game.finished)
        game._arcade_remaining = 0.05
        game.update(0.1)
        self.assertTrue(game.finished)
        self.assertTrue(game._victory)

    def test_kills_buy_seconds_and_bosses_buy_more(self) -> None:
        game = self._game()
        before = game._arcade_remaining
        game._grant_arcade_time(100.0, 100.0, is_boss=False)
        self.assertAlmostEqual(game._arcade_remaining, before + 2.0)
        game._grant_arcade_time(100.0, 100.0, is_boss=True)
        self.assertAlmostEqual(game._arcade_remaining, before + 10.0)

    def test_the_bonus_caps_the_clock_so_it_cannot_run_away(self) -> None:
        from game.constants import ARCADE_SECONDS

        game = self._game()
        game._arcade_remaining = ARCADE_SECONDS * 4.0
        game._grant_arcade_time(100.0, 100.0, is_boss=True)
        self.assertEqual(game._arcade_remaining, ARCADE_SECONDS * 4.0)

    def test_other_modes_get_no_arcade_clock_or_bonus(self) -> None:
        endless = self._game("endless")
        self.assertEqual(endless._arcade_remaining, 0.0)
        endless._grant_arcade_time(100.0, 100.0, is_boss=False)
        self.assertEqual(endless._arcade_remaining, 0.0)

    def test_arcade_plays_the_endless_family_waves_named_arcade(self) -> None:
        game = self._game()
        manager = game._wave_manager
        self.assertFalse(manager.is_campaign)
        self.assertIn("ARCADE", manager.language_name)
        ladder = {wave.language for wave in manager._campaign_waves}
        self.assertIn(manager.current_wave.language, ladder)

    def test_the_menu_offers_arcade_and_starts_it_directly(self) -> None:
        from game.constants import MODE_ARCADE
        from screens.game_screen import GameScreen
        from screens.main_menu import MainMenuScreen, _MENU_ITEMS

        labels = [item[0] for item in _MENU_ITEMS]
        self.assertIn("ARCADE", labels)

        screen = pygame.display.set_mode((1280, 720))
        menu = MainMenuScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            None,
        )
        result = menu._activate(MODE_ARCADE)
        self.assertIsInstance(result, GameScreen)
        self.assertEqual(result._mode, "arcade")

    def test_the_arcade_summary_is_saved(self) -> None:
        from screens.game_over_screen import GameOverScreen

        screen = pygame.display.set_mode((1280, 720))
        board = self.RecordingBoard()
        stats = {
            "player_name": "ACE", "mode": "arcade", "score": 5678, "wpm": 88.1,
            "accuracy": 96.4, "max_combo": 21, "best_wpm": 99.0, "waves": 6,
            "enemies": 44, "bosses": 2, "victory": True,
            "start_difficulty": "medium",
        }
        view = GameOverScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            board, stats,
        )
        self.assertEqual(len(board.saved), 1, "an arcade run must be recorded")
        self.assertEqual(board.saved[0]["mode"], "arcade")
        self.assertEqual(view._save_status, "saved")

    def test_quitting_arcade_banks_the_run(self) -> None:
        from screens.game_screen import GameScreen
        from screens.main_menu import MainMenuScreen

        screen = pygame.display.set_mode((1280, 720))
        board = self.RecordingBoard()
        view = GameScreen(
            screen, self.FakeSettings(), self.FakeAssets(), self.FakeAudio(),
            board, "arcade", "ACE",
        )
        pygame.event.clear()
        view._game._return_to_menu = True
        result = view.run(self.Clock())
        self.assertIsInstance(result, MainMenuScreen)
        self.assertEqual(len(board.saved), 1, "quitting arcade must bank the run")

    def test_the_clock_runs_down_in_real_time(self) -> None:
        from game.constants import ARCADE_SECONDS

        game = self._game()
        self.assertEqual(game._arcade_remaining, ARCADE_SECONDS)
        game.update(1.5)
        self.assertAlmostEqual(game._arcade_remaining, ARCADE_SECONDS - 1.5)


class ScreenStateTests(unittest.TestCase):
    """State that must survive a rebuild, because a resize triggers one."""

    def test_the_menu_keeps_its_selection_across_a_resize(self) -> None:
        from screens.main_menu import MainMenuScreen

        class FakeAssets:
            def font(self, size, bold=False):
                return pygame.font.Font(None, max(8, size))

        class FakeAudio:
            def play(self, slot):
                pass

        screen = pygame.display.set_mode((1920, 1080))
        view = MainMenuScreen(screen, None, FakeAssets(), FakeAudio(), None)
        view._handle_key(pygame.K_DOWN)
        view._handle_key(pygame.K_DOWN)
        self.assertEqual(view._selected, 2)

        pygame.display.set_mode((1280, 720))
        small = pygame.display.get_surface()
        view._screen = small
        view._draw()
        self.assertEqual(
            view._selected, 2,
            "a window resize must not throw the menu selection away",
        )
        self.assertEqual(view._ui.width, 1280)


if __name__ == "__main__":
    unittest.main()
