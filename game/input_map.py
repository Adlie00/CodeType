"""Translate key presses to characters by physical key, not by keyboard layout.

Why this exists: both the game field and the name field used to read
``event.unicode`` directly. On layouts where ``"`` (and ``'``, `` ` ``, ``^``,
``~``) are *dead keys* — most visibly ``United States-International`` — the first
press carries an empty ``unicode`` while it arms an accent, so a player had to
press the key twice before a character appeared. Reading the SDL *scancode*
(which is layout- and dead-key-independent) and mapping it to the equivalent US
character makes one press produce one character everywhere.

The US table is only consulted for scancodes it knows. Anything else — and any
event without a scancode, such as the synthetic events the tests build — falls
back to ``event.unicode``, so other layouts keep working and a genuine non-US
symbol can still be typed.
"""

from __future__ import annotations

import pygame

# SDL scancodes for the printable keys on a US layout. pygame numbers its
# constants by *keycode* (``event.key``), which the operating system remaps per
# layout, so the physical scancodes are spelled out here instead.
_LETTER_FIRST = 4    # SDL_SCANCODE_A
_LETTER_LAST = 29    # SDL_SCANCODE_Z
_DIGIT_FIRST = 30    # SDL_SCANCODE_1
_DIGIT_LAST = 39     # SDL_SCANCODE_0

_DIGITS = {
    30: ("1", "!"), 31: ("2", "@"), 32: ("3", "#"), 33: ("4", "$"),
    34: ("5", "%"), 35: ("6", "^"), 36: ("7", "&"), 37: ("8", "*"),
    38: ("9", "("), 39: ("0", ")"),
}

_PUNCTUATION = {
    44: (" ", " "),   # SDL_SCANCODE_SPACE
    45: ("-", "_"),   # MINUS
    46: ("=", "+"),   # EQUALS
    47: ("[", "{"),   # LEFTBRACKET
    48: ("]", "}"),   # RIGHTBRACKET
    49: ("\\", "|"),  # BACKSLASH
    51: (";", ":"),   # SEMICOLON
    52: ("'", '"'),   # APOSTROPHE
    53: ("`", "~"),   # GRAVE
    54: (",", "<"),   # COMMA
    55: (".", ">"),   # PERIOD
    56: ("/", "?"),   # SLASH
}


def printable_character(event: pygame.event.Event) -> str | None:
    """The single printable character a KEYDOWN represents, or ``None``.

    Resolution order: the physical scancode against the US layout first, then
    ``event.unicode`` for anything the table does not cover.
    """
    scancode = getattr(event, "scancode", 0) or 0
    mods = getattr(event, "mod", 0) or 0
    shift = bool(mods & pygame.KMOD_SHIFT)

    if _LETTER_FIRST <= scancode <= _LETTER_LAST:
        letter = chr(ord("a") + scancode - _LETTER_FIRST)
        caps = bool(mods & pygame.KMOD_CAPS)
        return letter.upper() if shift ^ caps else letter

    pair = _DIGITS.get(scancode) or _PUNCTUATION.get(scancode)
    if pair is not None:
        return pair[1] if shift else pair[0]

    character = getattr(event, "unicode", "")
    if (
        isinstance(character, str)
        and len(character) == 1
        and ord(character) >= 32
    ):
        return character
    return None
