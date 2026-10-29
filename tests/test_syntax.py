"""Syntax highlighting on the code cards.

The cards carry two colour layers at once: the flat green of what has been
typed, and the token colours of what has not. These tests pin the properties
that make that safe rather than the exact colours, because a bug in either shows
up as unreadable code in the middle of a live wave:

* tokens must tile the snippet exactly, for every language and every tier in
  ``data/languages`` — a gap would drop characters off the card and shift the
  cursor away from what the player is looking at;
* the card renderer must hand pygame the characters of each line in order,
  whatever the cursor position, so the split at the cursor cannot eat or repeat
  a character;
* typed text must still be painted in ``TYPED_COLOUR``, since that is the
  signal the player is playing against.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402  (must follow the dummy drivers above)

from game.constants import (  # noqa: E402
    DESIGN_HEIGHT,
    DESIGN_WIDTH,
    DIFFICULTY_EXPERT,
    ENEMY_LINE_HEIGHT,
    LANGUAGES_DIR,
    REMAINING_COLOUR,
    SYNTAX_COLOURS,
    TYPED_COLOUR,
)
from game.content import Challenge  # noqa: E402
from game.enemy import Enemy  # noqa: E402
from game.syntax import TokenStream, tokenize  # noqa: E402

TIERS = ("EASY", "MEDIUM", "HARD", "EXPERT", "BOSS")


def load_snippets() -> dict[str, list[tuple[str, str]]]:
    """Every challenge in the game, as ``language -> [(tier, code), ...]``."""
    found: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(Path(LANGUAGES_DIR).glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        language = str(document["language"])
        challenges = document["challenges"]
        for tier in TIERS:
            for item in challenges.get(tier, []):
                found.setdefault(language, []).append((tier, item["code"]))
    return found


def kinds_of(text: str, language: str) -> dict[str, list[str]]:
    """``{kind: [source, ...]}`` for a snippet, for readable assertions."""
    grouped: dict[str, list[str]] = {}
    for token in tokenize(text, language):
        grouped.setdefault(token.kind, []).append(text[token.start : token.end])
    return grouped


class TokenCoverageTests(unittest.TestCase):
    """Every character of every snippet belongs to exactly one token."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snippets = load_snippets()

    def test_every_language_file_is_covered(self) -> None:
        # The feature promises highlighting for each language the game ships.
        self.assertEqual(
            set(self.snippets),
            {
                "c", "cpp", "csharp", "css", "html", "java",
                "javascript", "mixed", "python", "sql",
            },
        )
        for language, entries in self.snippets.items():
            self.assertTrue(entries, f"{language} has no challenges")

    def test_every_tier_of_every_language_is_present(self) -> None:
        for language, entries in self.snippets.items():
            tiers = {tier for tier, _ in entries}
            self.assertEqual(tiers, set(TIERS), f"{language} is missing a tier")

    def test_tokens_tile_every_snippet_exactly(self) -> None:
        for language, entries in self.snippets.items():
            for tier, text in entries:
                with self.subTest(language=language, tier=tier, text=text):
                    position = 0
                    for token in tokenize(text, language):
                        self.assertEqual(
                            token.start, position,
                            "a token must begin where the previous one ended",
                        )
                        self.assertLessEqual(token.start, token.end)
                        self.assertLessEqual(token.end, len(text))
                        position = token.end
                    self.assertEqual(
                        position, len(text),
                        "the last token must reach the end of the snippet",
                    )

    def test_no_token_kind_is_left_unpainted(self) -> None:
        # A kind with no colour would fall back to the remaining-text white,
        # silently. Catch it here rather than on screen.
        for language, entries in self.snippets.items():
            for tier, text in entries:
                for token in tokenize(text, language):
                    self.assertIn(
                        token.kind, SYNTAX_COLOURS,
                        f"{token.kind!r} has no entry in SYNTAX_COLOURS",
                    )

    def test_cached_tokenisation_returns_the_same_spans(self) -> None:
        for language, entries in self.snippets.items():
            for tier, text in entries:
                with self.subTest(language=language, tier=tier):
                    self.assertEqual(tokenize(text, language), tokenize(text, language))


class TokenKindTests(unittest.TestCase):
    """The scanner has to know where a string ends and a block ends."""

    def test_keywords_strings_numbers_and_calls(self) -> None:
        grouped = kinds_of("def add(a, b):\n  return a + b", "python")
        self.assertEqual(grouped["keyword"], ["def", "return"])
        self.assertEqual(grouped["function"], ["add"])

        grouped = kinds_of('n = "7" + 1', "python")
        self.assertEqual(grouped["string"], ['"7"'])
        # The 7 is inside the string, so it is not a number token.
        self.assertEqual(grouped["number"], ["1"])

    def test_a_type_name_reads_as_a_type_but_a_call_reads_as_a_call(self) -> None:
        # ``int`` alone is a type; ``int(`` is a conversion call, and painting it
        # as a type would be a lie about what the code does.
        self.assertEqual(kinds_of("x = int", "python")["type"], ["int"])
        self.assertEqual(kinds_of("x = int(y)", "python")["function"], ["int"])
        self.assertIn("str", kinds_of("def f(x: str):", "python")["type"])

    def test_a_hash_inside_a_string_is_not_a_comment(self) -> None:
        grouped = kinds_of('print("a # b")', "python")
        self.assertNotIn("comment", grouped)
        self.assertEqual(grouped["string"], ['"a # b"'])

    def test_a_triple_quoted_string_spans_newlines(self) -> None:
        text = 'q = """SELECT name\n  FROM runs"""'
        grouped = kinds_of(text, "python")
        self.assertEqual(grouped["string"], ['"""SELECT name\n  FROM runs"""'])
        # The SQL inside must not be split into keywords.
        self.assertNotIn("keyword", grouped)

    def test_c_types_and_comments(self) -> None:
        grouped = kinds_of('int main(void) { /* bye */ return 0; }', "c")
        self.assertEqual(grouped["type"], ["int", "void"])
        self.assertEqual(grouped["comment"], ["/* bye */"])
        self.assertEqual(grouped["number"], ["0"])

    def test_a_slash_run_does_not_swallow_a_string(self) -> None:
        # ``(`` immediately before a string used to be lexed as punctuation that
        # included the opening quote, which left the string as loose words.
        grouped = kinds_of('printf("%d\\n", i);', "mixed")
        self.assertEqual(grouped["string"], ['"%d\\n"'])

    def test_sql_is_case_insensitive_and_dashes_need_a_space(self) -> None:
        self.assertIn("select", kinds_of("select 1", "sql")["keyword"])
        self.assertEqual(
            kinds_of("SELECT a FROM t -- note", "sql")["comment"], ["-- note"]
        )
        # A git flag is not an SQL comment.
        self.assertNotIn("comment", kinds_of("git log --oneline", "mixed"))

    def test_html_tags_attributes_and_text(self) -> None:
        grouped = kinds_of('<a href="#">Link</a>', "html")
        self.assertEqual(grouped["tag"], ["<a", "</a"])
        self.assertEqual(grouped["attribute"], ["href"])
        self.assertEqual(grouped["string"], ['"#"'])
        # Element content is prose, not code, and must stay plain.
        self.assertIn("Link", grouped.get("plain", []))

    def test_css_properties_selectors_values_and_colours(self) -> None:
        grouped = kinds_of(".btn:hover {\n  color: #0ff;\n  padding: 8px;\n}", "css")
        self.assertEqual(grouped["selector"], [".btn"])
        self.assertEqual(grouped["property"], ["color", "padding"])
        self.assertEqual(grouped["value"], ["hover"])
        self.assertEqual(grouped["number"], ["#0ff", "8px"])

    def test_css_custom_properties_and_at_rules(self) -> None:
        grouped = kinds_of("@media (max-width: 600px) { .n { display: none; } }", "css")
        self.assertEqual(grouped["keyword"], ["@media"])
        self.assertEqual(grouped["property"], ["max-width", "display"])
        self.assertEqual(grouped["value"], ["none"])

    def test_mixed_reads_shell_rust_go_and_yaml(self) -> None:
        self.assertEqual(kinds_of("for x in a do\n done", "mixed")["keyword"],
                         ["for", "in", "do", "done"])
        self.assertIn("fn", kinds_of("fn total(a: &[i32]) -> i32 {", "mixed")["keyword"])
        self.assertIn("i32", kinds_of("fn total(a: &[i32]) -> i32 {", "mixed")["type"])
        self.assertIn("chan", kinds_of("make(chan int, 2)", "mixed")["keyword"])
        # A YAML key is not a CSS property, even though it precedes a colon.
        self.assertNotIn("property", kinds_of("name: test", "mixed"))

    def test_mixed_css_lines_still_get_style_colours(self) -> None:
        grouped = kinds_of(".row {\n  display: flex;\n  gap: 8px;\n}", "mixed")
        self.assertEqual(grouped["selector"], [".row"])
        self.assertEqual(grouped["property"], ["display", "gap"])
        self.assertEqual(grouped["value"], ["flex"])

    def test_mixed_does_not_mistake_a_template_for_a_tag(self) -> None:
        # ``<class T>`` is C++, not an HTML element, and ``class`` is a keyword.
        grouped = kinds_of("template <class T>", "mixed")
        self.assertIn("class", grouped["keyword"])
        self.assertNotIn("tag", grouped)


class TokenEdgeCaseTests(unittest.TestCase):
    """Degenerate input must not raise or produce a broken span list."""

    def test_empty_text_has_no_tokens(self) -> None:
        self.assertEqual(tokenize("", "python"), ())

    def test_an_unknown_language_still_tiles(self) -> None:
        text = "def f(): return 'x'"
        spans = tokenize(text, "cobol")
        self.assertEqual(spans[0].start, 0)
        self.assertEqual(spans[-1].end, len(text))

    def test_an_unterminated_string_stops_at_the_line_end(self) -> None:
        text = 'a = "open\nb = 2'
        self.assertEqual(tokenize(text, "python")[-1].end, len(text))
        self.assertIn('"open', kinds_of(text, "python")["string"])

    def test_a_snippet_that_is_only_punctuation(self) -> None:
        text = "()[]{};:,"
        spans = tokenize(text, "python")
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0].start, spans[0].end), (0, len(text)))

    def test_an_empty_line_produces_no_token(self) -> None:
        self.assertEqual(tokenize("", "css"), ())
        self.assertEqual(kinds_of("\n\n", "css").get("plain"), ["\n\n"])

    def test_a_snippet_with_no_trailing_newline(self) -> None:
        text = "SELECT 1"
        self.assertEqual(tokenize(text, "sql")[-1].end, len(text))

    def test_tabs_and_non_ascii_are_preserved(self) -> None:
        text = "\tdef f():\n\treturn 'café'"
        spans = tokenize(text, "python")
        self.assertEqual("".join(text[t.start : t.end] for t in spans), text)


class TokenStreamTests(unittest.TestCase):
    """The per-line lookup the card renderer walks."""

    def lines_of(self, text: str) -> list[tuple[int, int]]:
        starts = [0] + [index + 1 for index, char in enumerate(text) if char == "\n"]
        bounds = []
        for position, start in enumerate(starts):
            end = starts[position + 1] - 1 if position + 1 < len(starts) else len(text)
            bounds.append((start, max(start, min(end, len(text)))))
        return bounds

    def test_between_reassembles_every_line(self) -> None:
        for language, entries in load_snippets().items():
            for tier, text in entries:
                stream = TokenStream(text, language)
                for start, end in self.lines_of(text):
                    with self.subTest(language=language, tier=tier, line=text[start:end]):
                        rebuilt = "".join(
                            text[token.start : token.end]
                            for token in stream.between(start, end)
                        )
                        self.assertEqual(rebuilt, text[start:end])

    def test_between_clips_to_the_requested_range(self) -> None:
        text = "SELECT name FROM runs"
        stream = TokenStream(text, "sql")
        for token in stream.between(7, 11):
            self.assertGreaterEqual(token.start, 7)
            self.assertLessEqual(token.end, 11)

    def test_between_on_an_empty_range(self) -> None:
        stream = TokenStream("SELECT 1", "sql")
        self.assertEqual(stream.between(4, 4), [])
        self.assertEqual(stream.between(9, 2), [])

    def test_between_on_empty_text(self) -> None:
        self.assertEqual(TokenStream("", "sql").between(0, 10), [])

    def test_a_token_spanning_a_line_break_is_clipped(self) -> None:
        text = 'a = """one\ntwo"""'
        stream = TokenStream(text, "python")
        self.assertEqual(stream.between(0, 8), stream.between(0, 8))
        for start, end in self.lines_of(text):
            for token in stream.between(start, end):
                self.assertLessEqual(token.end - token.start, end - start)

    def test_the_stream_agrees_with_tokenize(self) -> None:
        text = "def f():\n  return 1"
        self.assertEqual(
            TokenStream(text, "python").tokens, tokenize(text, "python")
        )


class CardRenderTests(unittest.TestCase):
    """A card shows one line at a time, and that line has to come out right.

    The renderer splits each token again at the typing cursor, so these are the
    positions where a slicing mistake would show: the very start, the end, a
    point inside a multi-character token, and either side of a line break.
    """

    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class RecordingUI:
        """A UI that records what it was asked to draw, and still draws it.

        ``_draw_code`` only needs ``px``, ``measure``, ``font``, ``text`` and
        ``blit_run`` off the UI, so the recorder delegates everything else to a
        real one. Blitting for real as well keeps the advance widths honest — a
        fake returning 0 would let a broken split pass by looking correct.
        """

        def __init__(self, real) -> None:
            self._real = real
            self.runs: list[tuple[str, tuple[int, int, int], int, int, int]] = []
            self.labels: list[str] = []

        def px(self, value: float) -> int:
            return self._real.px(value)

        def measure(self, message: str, size: int, bold: bool = False) -> tuple[int, int]:
            return self._real.measure(message, size, bold)

        def font(self, size: int, bold: bool = False):
            return self._real.font(size, bold)

        def text(self, surface, message, size, colour, x, y, **kwargs):
            self.labels.append(message)
            return self._real.text(surface, message, size, colour, x, y, **kwargs)

        def blit_run(self, surface, message, size, colour, x, y, *, bold=False) -> int:
            self.runs.append((message, colour, x, y, size))
            return self._real.blit_run(surface, message, size, colour, x, y, bold=bold)

    def setUp(self) -> None:
        pygame.init()
        from game.game import Game
        from game.ui import DESIGN_LAYOUT, UI

        self.surface = pygame.Surface((DESIGN_WIDTH, DESIGN_HEIGHT))
        self.surface.fill((8, 8, 20))
        self.ui = UI(self.FakeAssets(), DESIGN_WIDTH, DESIGN_HEIGHT)
        self.game = Game.__new__(Game)
        self.game._ui = self.ui
        self.game._layout = DESIGN_LAYOUT

    def _draw(
        self, text: str, language: str, cursor: int
    ) -> tuple[list[tuple[str, tuple[int, int, int], int, int, int]], list[str], pygame.Rect]:
        enemy = Enemy(
            Challenge(text=text, language=language, difficulty=DIFFICULTY_EXPERT),
            DIFFICULTY_EXPERT,
        )
        # The card is the enemy's own size, the way the game draws it, so the
        # font fitting is measured against the box it will really get.
        rect = pygame.Rect(40, 40, enemy.width, enemy.height)
        enemy.y = rect.y
        enemy.typing.index = cursor
        recorder = self.RecordingUI(self.ui)
        self.game._ui = recorder
        self.game._draw_code(self.surface, enemy, rect, True, (0, 0, 0))
        return recorder.runs, recorder.labels, rect

    def _lines(self, text: str) -> list[str]:
        return text.split("\n")

    @staticmethod
    def _line_at(text: str, cursor: int) -> str:
        """The line the cursor is on, worked out independently of the game."""
        start = text.rfind("\n", 0, cursor) + 1
        end = text.find("\n", cursor)
        return text[start:] if end == -1 else text[start:end]

    def test_only_the_cursor_line_is_drawn(self) -> None:
        samples = {
            "python": 'def add(a, b):\n  return a + b',
            "javascript": 'const t = `a${b}`;\nlet s = "x";',
            "sql": "SELECT name, AVG(score) AS a\nFROM runs\nGROUP BY name;",
            "css": ".btn:hover {\n  color: #0ff;\n}",
            "html": '<a href="#">Link</a>\n<br>',
            "c": 'int main(void) {\n  return 0;\n}',
            "mixed": 'q = """SELECT name\n  FROM runs"""',
        }
        for language, text in samples.items():
            for cursor in range(len(text) + 1):
                with self.subTest(language=language, cursor=cursor):
                    runs, _, _ = self._draw(text, language, cursor)
                    self.assertEqual(len({y for _, _, _, y, _ in runs}), 1, "one line only")
                    drawn = "".join(message for message, _, _, _, _ in runs)
                    self.assertEqual(
                        drawn, self._line_at(text, cursor),
                        f"{language} at cursor {cursor}: expected "
                        f"{self._line_at(text, cursor)!r}, drew {drawn!r}",
                    )

    def test_a_line_stays_put_until_its_newline_is_typed(self) -> None:
        # The card advances on Enter, so the newline has to belong to the line it
        # ends — otherwise the view jumps while the player is still on the line.
        text = "alpha\nbeta"
        runs, _, _ = self._draw(text, "python", text.index("\n"))
        self.assertEqual("".join(m for m, _, _, _, _ in runs), "alpha")
        runs, _, _ = self._draw(text, "python", text.index("\n") + 1)
        self.assertEqual("".join(m for m, _, _, _, _ in runs), "beta")

    def test_a_token_split_at_the_cursor_loses_nothing(self) -> None:
        # One long token straddling every cursor position is where an off-by-one
        # in the split would drop or repeat characters.
        text = "a" * 40
        for cursor in range(len(text) + 1):
            with self.subTest(cursor=cursor):
                runs, _, _ = self._draw(text, "python", cursor)
                self.assertEqual("".join(m for m, _, _, _, _ in runs), text)

    def test_typed_characters_are_painted_in_the_typed_colour(self) -> None:
        text = "def add(a, b):\n  return a + b"
        cursor = text.index("add") + 2
        runs, _, _ = self._draw(text, "python", cursor)
        typed = "".join(m for m, colour, _, _, _ in runs if colour == TYPED_COLOUR)
        self.assertEqual(typed, text[:cursor])

    def test_remaining_characters_are_painted_by_token_kind(self) -> None:
        text = "def add(a, b):\n  return a + b"
        runs, _, _ = self._draw(text, "python", 0)
        self.assertEqual("".join(m for m, _, _, _, _ in runs), "def add(a, b):")
        painted = {colour for _, colour, _, _, _ in runs}
        self.assertIn(SYNTAX_COLOURS["keyword"], painted)
        self.assertIn(SYNTAX_COLOURS["function"], painted)
        self.assertNotIn(TYPED_COLOUR, painted)

    def test_an_untouched_snippet_has_no_typed_text(self) -> None:
        text = "SELECT name FROM runs"
        runs, _, rect = self._draw(text, "sql", 0)
        self.assertEqual(runs[0][2], rect.x + self.ui.px(10))
        self.assertNotIn(TYPED_COLOUR, {colour for _, colour, _, _, _ in runs})

    def test_a_fully_typed_snippet_is_all_typed(self) -> None:
        text = "SELECT 1"
        runs, _, _ = self._draw(text, "sql", len(text))
        self.assertEqual({colour for _, colour, _, _, _ in runs}, {TYPED_COLOUR})

    def test_runs_advance_left_to_right_without_gaps(self) -> None:
        # Each run is blitted at the previous run's x plus that run's advance, so
        # the concatenated runs have to line up on the text as a whole.
        text = "def add(a, b):"
        runs, _, _ = self._draw(text, "python", 7)
        for (message, _, x, _, size), (_, _, next_x, _, _) in zip(runs, runs[1:]):
            width = self.ui.measure(message, size, True)[0]
            self.assertEqual(
                next_x, x + width,
                f"{message!r} advanced {width}px but the next run started at "
                f"{next_x - x}px",
            )
        self.assertEqual("".join(m for m, _, _, _, _ in runs), text)

    def test_the_line_never_overflows_the_card(self) -> None:
        # One line at a time buys a bigger font, and a bigger font on a long line
        # is exactly how a card would start spilling text off its own edge.
        for language, entries in load_snippets().items():
            for tier, text in entries:
                with self.subTest(language=language, tier=tier):
                    runs, _, rect = self._draw(text, language, len(text) // 2)
                    widths = [self.ui.measure(m, size, True)[0] for m, _, _, _, size in runs]
                    limit = rect.width - self.ui.px(20)
                    self.assertLessEqual(
                        sum(widths), limit,
                        f"{language} {tier} overflows the card by "
                        f"{sum(widths) - limit}px: {text!r}",
                    )
                    right = min((x + w for (_, _, x, _, _), w in zip(runs, widths)), default=rect.x)
                    self.assertLessEqual(right, rect.right - self.ui.px(10))

    def test_a_short_line_gets_a_bigger_font_than_a_long_one(self) -> None:
        # A card shows one line but is sized for several, so a line with room to
        # spare should be set larger rather than left small in a big empty box.
        # Both snippets are six lines here, so both cards are the same height and
        # the only thing that can differ is the line's own width.
        def size_of(text: str) -> int:
            runs, _, _ = self._draw(text, "python", 0)
            return runs[0][4]

        tall_card = "a\nb\nc\nd\ne\n"
        short = size_of(tall_card + "x = 1")
        long = size_of(tall_card + "x = 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10")
        self.assertGreater(
            short, long,
            f"a short line was set at {short}pt and a long one at {long}pt",
        )
        self.assertEqual(short, 36, "a short line on a tall card should fill it")
        for size in (short, long):
            self.assertGreaterEqual(size, 13)
            self.assertLessEqual(size, 36)

    def test_the_font_fits_the_height_of_the_card(self) -> None:
        for language, entries in load_snippets().items():
            for tier, text in entries:
                with self.subTest(language=language, tier=tier):
                    runs, _, rect = self._draw(text, language, 0)
                    if not runs:
                        continue
                    size = runs[0][4]
                    self.assertLessEqual(
                        self.ui.font(size, True).get_height(),
                        rect.height - self.game._layout.enemy_header_height,
                        f"{language} {tier} at {size}pt is taller than the card",
                    )

    def test_a_multi_line_card_says_which_line_it_is_on(self) -> None:
        text = "alpha\nbeta\ngamma"
        _, labels, _ = self._draw(text, "python", 0)
        self.assertEqual(labels, ["LINE 1 / 3"])
        _, labels, _ = self._draw(text, "python", text.index("beta"))
        self.assertEqual(labels, ["LINE 2 / 3"])
        _, labels, _ = self._draw(text, "python", len(text))
        self.assertEqual(labels, ["LINE 3 / 3"])

    def test_a_single_line_card_has_nothing_to_count(self) -> None:
        _, labels, _ = self._draw("x = 1", "python", 0)
        self.assertEqual(labels, [])

    def test_every_real_snippet_draws_at_several_cursors(self) -> None:
        for language, entries in load_snippets().items():
            for tier, text in entries:
                for cursor in (0, 1, len(text) // 2, len(text) - 1, len(text)):
                    if not 0 <= cursor <= len(text):
                        continue
                    with self.subTest(language=language, tier=tier, cursor=cursor):
                        runs, _, _ = self._draw(text, language, cursor)
                        self.assertEqual(
                            "".join(m for m, _, _, _, _ in runs),
                            self._line_at(text, cursor),
                        )

    def test_the_typing_engine_rejects_an_empty_snippet(self) -> None:
        # A card can never be empty, so Enemy construction is where that is
        # enforced — the renderer only ever sees text with at least one char.
        from game.typing_engine import TypingEngine

        with self.assertRaises(ValueError):
            TypingEngine("")


if __name__ == "__main__":
    unittest.main()
