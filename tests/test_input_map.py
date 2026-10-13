"""Physical-key mapping: dead-key layouts must not need two presses.

United States-International makes '"' a dead key, so the first press arrives
with an empty ``unicode``. Resolving the character from the SDL scancode makes
one press produce one character regardless of the keyboard layout.
"""

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

pygame.init()

from game.input_map import printable_character


def press(scancode: int = 0, mod: int = 0, unicode: str = "", key_code: int = 0):
    return pygame.event.Event(
        pygame.KEYDOWN, key=key_code, mod=mod, scancode=scancode, unicode=unicode
    )


class UsLayoutMappingTests(unittest.TestCase):
    def test_quote_needs_one_press_even_as_a_dead_key(self) -> None:
        # The dead-key press: unicode is empty, but the physical key is the
        # apostrophe key with shift held.
        self.assertEqual(
            printable_character(press(scancode=52, mod=pygame.KMOD_SHIFT)),
            '"',
        )

    def test_apostrophe_and_grave_variants(self) -> None:
        self.assertEqual(printable_character(press(scancode=52)), "'")
        self.assertEqual(
            printable_character(press(scancode=53, mod=pygame.KMOD_SHIFT)), "~"
        )
        self.assertEqual(printable_character(press(scancode=53)), "`")

    def test_shifted_symbols_and_digits(self) -> None:
        self.assertEqual(
            printable_character(press(scancode=31, mod=pygame.KMOD_SHIFT)), "@"
        )
        self.assertEqual(printable_character(press(scancode=31)), "2")
        self.assertEqual(printable_character(press(scancode=39)), "0")
        self.assertEqual(
            printable_character(press(scancode=45, mod=pygame.KMOD_SHIFT)), "_"
        )
        self.assertEqual(
            printable_character(press(scancode=47, mod=pygame.KMOD_SHIFT)), "{"
        )

    def test_letters_respect_shift_and_caps(self) -> None:
        self.assertEqual(printable_character(press(scancode=4)), "a")
        self.assertEqual(
            printable_character(press(scancode=4, mod=pygame.KMOD_SHIFT)), "A"
        )
        self.assertEqual(
            printable_character(press(scancode=4, mod=pygame.KMOD_CAPS)), "A"
        )
        self.assertEqual(
            printable_character(
                press(scancode=4, mod=pygame.KMOD_CAPS | pygame.KMOD_SHIFT)
            ),
            "a",
        )

    def test_space_is_mapable(self) -> None:
        self.assertEqual(printable_character(press(scancode=44)), " ")

    def test_falls_back_to_unicode_without_a_scancode(self) -> None:
        self.assertEqual(printable_character(press(unicode="x")), "x")
        self.assertEqual(printable_character(press(unicode="é")), "é")

    def test_control_keys_are_rejected(self) -> None:
        self.assertIsNone(printable_character(press(scancode=43, unicode="\t")))
        self.assertIsNone(printable_character(press(scancode=40, unicode="\r")))


class DeadKeyIntegrationTests(unittest.TestCase):
    """Both real input paths accept a '"' from a single dead-key press."""

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    def test_name_input_accepts_a_dead_key_quote(self) -> None:
        from screens.name_input_screen import NameInputScreen

        screen = pygame.display.set_mode((1280, 720))
        view = NameInputScreen(
            screen, None, self.FakeAssets(), self.FakeAudio(), None, "competition"
        )
        view._handle_key(
            pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_QUOTE, mod=pygame.KMOD_SHIFT,
                scancode=52, unicode="",
            )
        )
        self.assertEqual(view._name, '"')

    def test_gameplay_accepts_a_dead_key_quote(self) -> None:
        from game.game import Game

        # ``_character_from_event`` uses no instance state, so a bare instance
        # reaches it without standing up the whole content repository.
        game = Game.__new__(Game)
        character = game._character_from_event(
            pygame.event.Event(
                pygame.KEYDOWN, key=pygame.K_QUOTE, mod=pygame.KMOD_SHIFT,
                scancode=52, unicode="",
            )
        )
        self.assertEqual(character, '"')


if __name__ == "__main__":
    unittest.main()
