"""Language-aware tokenisation for the code cards.

The cards already colour code by *progress* — everything before the cursor is
green, everything after it is white. That is the signal the player actually
plays against, so it is not replaced here: this module supplies a second,
underlying layer. :meth:`TokenStream.between` returns token spans that align
exactly with the characters of the snippet, so the renderer can lay them out in
order and let the progress colour win for the typed half.

It is deliberately a scanner rather than a parser. Nothing here needs to
understand what the code *means*; it only has to be right about where a string
ends, so a keyword in a comment is not painted as one, and it has to cover every
character so the renderer can walk the snippet without gaps. Pygments or a real
parser would be a large dependency for a cosmetic layer on a 16px font, and the
snippets are short.

Every language in ``data/languages`` is covered, ``mixed`` included: a snippet
there can be a shell loop, Rust, Go, YAML or a fragment of CSS, so it gets the
union of the comment and string forms plus the CSS and HTML rules, resolved
per token rather than guessed from the file.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from functools import lru_cache
from typing import NamedTuple

# Token kinds. These are the keys of ``constants.SYNTAX_COLOURS``; anything the
# scanner does not recognise falls back to "plain", which is the card's normal
# untyped colour, so a gap in the rules is invisible rather than broken.
PLAIN = "plain"
KEYWORD = "keyword"
TYPE = "type"
STRING = "string"
NUMBER = "number"
COMMENT = "comment"
FUNCTION = "function"
OPERATOR = "operator"
TAG = "tag"
ATTRIBUTE = "attribute"
PROPERTY = "property"
SELECTOR = "selector"
VALUE = "value"


class Token(NamedTuple):
    """Half-open ``[start, end)`` character span and what it is."""

    start: int
    end: int
    kind: str


# ── Shared scanner fragments ──────────────────────────────────────────────────
# Order matters: ``re`` takes the leftmost match and, at that position, the first
# alternative that fits. Comments and strings therefore come first so that a
# ``#`` or ``//`` inside a string stays part of the string.

_C_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
_CSS_IDENT = r"[-A-Za-z_$][-\w$]*"
_NUMBER = (
    r"\b(?:0[xXbB][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"(?:px|em|rem|pt|ex|ch|vh|vw|ms|s|deg|fr|%)?\b"
)
# The closing quote is optional, so a snippet with a stray quote colours up to
# the end of its line instead of leaving the quote unpainted — but never past
# the newline, so one unterminated string cannot swallow the rest of the snippet.
_STRINGS = r"\"(?:\\.|[^\"\\\n])*\"?|\'(?:\\.|[^\'\\\n])*\'?"
_TRIPLE_STRINGS = r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''"
# An explicit character set, not a negated one: a run like ``(`` immediately
# followed by a string must stop before the quote, or the opening delimiter is
# eaten as punctuation and the string lexes as three loose words.
_OPERATORS = r"[+\-*/%=<>!&|^~?:.,;()\[\]{}$@#\\]+"
_BLOCK_COMMENT = r"/\*[\s\S]*?\*/"
_HTML_COMMENT = r"<!--[\s\S]*?-->"
_SLASH_COMMENT = r"//[^\n]*"
_HASH_COMMENT = r"#[^\n]*"
# ``--`` only opens an SQL comment when a space follows, so ``git log --oneline``
# in a mixed snippet is not swallowed to end of line.
_DASH_COMMENT = r"(?<!\S)--(?=[ \t])[^\n]*"
_AT_RULE = r"@[-A-Za-z_][-\w]*"
_HEX_COLOUR = r"#[0-9a-fA-F]{3,8}\b"
# A dotted or hashed token only reads as a selector when a rule or a pseudo-class
# follows it; otherwise ``#0ff`` is a colour, not an id.
_SELECTOR = r"[.#][-\w]+(?=\s*[,{:])"
# Tightened against mixed snippets, where ``<class T>`` is a C++ template and not
# a tag: a tag is closed, self-closed, or carries at least one ``name=`` pair.
_TAG = r"</?[A-Za-z][\w:.\-]*(?=\s*/?>|[\s(]+[\w:.\-]+\s*=)"
_DOCTYPE = r"<!DOCTYPE[^>\n]*>"
_HTML_ATTRIBUTE = r"[\w:.\-]+(?=\s*=)"
_HTML_PUNCT = r"[<>/=]+"


# ── Vocabularies ──────────────────────────────────────────────────────────────

# Type names are kept out of the keyword sets so ``int`` reads as a type in C
# rather than winning the keyword test first. Resolution order is keyword, then
# call, then type, so a name is only ever classified one way.

_C_KEYWORDS = frozenset("""
break case const continue default do else enum extern for goto if inline
register restrict return sizeof static struct switch typedef union while
""".split())

_CPP_KEYWORDS = _C_KEYWORDS | frozenset("""
class namespace template typename public private protected virtual override
new delete this try catch throw using nullptr true false operator friend
constexpr decltype explicit mutable
""".split())

_JAVA_KEYWORDS = frozenset("""
abstract assert break case catch class const continue default do else enum
extends final finally for goto if implements import instanceof interface
native new package private protected public return static strictfp super
switch synchronized this throw throws transient try volatile while var record
sealed yield
""".split())

_CSHARP_KEYWORDS = frozenset("""
abstract as base break case catch checked class const continue default
delegate do else enum event explicit extern false finally fixed for foreach
goto if implicit in interface internal is lock namespace new null operator
out override params private protected public readonly ref return sealed
sizeof stackalloc static struct switch this throw true try typeof unchecked
unsafe using virtual void volatile while async await yield get set partial
when record
""".split())

_JS_KEYWORDS = frozenset("""
async await break case catch class const continue debugger default delete do
else export extends finally for function if import in instanceof let new of
return static super switch this throw try typeof var while with yield
true false null undefined NaN
""".split())

_PYTHON_KEYWORDS = frozenset("""
and as assert async await break class continue def del elif else except
finally for from global if import in is lambda None nonlocal not or pass raise
return True False try while with yield self cls match case
""".split())

_SQL_KEYWORDS = frozenset("""
SELECT FROM WHERE INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE ALTER
DROP INDEX VIEW JOIN INNER LEFT RIGHT OUTER FULL CROSS ON USING GROUP BY ORDER
HAVING LIMIT OFFSET DISTINCT AS AND OR NOT NULL IS IN BETWEEN LIKE EXISTS
UNION ALL ANY SOME CASE WHEN THEN ELSE END WITH RECURSIVE OVER PARTITION ROWS
RANGE ASC DESC
""".split())

# The grab-bag tier: shell, Lua, Rust, Go, TypeScript, Elixir and YAML all turn
# up in ``mixed``, so the keyword set is the union of every dialect.
_MIXED_KEYWORDS = frozenset().union(
    _C_KEYWORDS, _CPP_KEYWORDS, _JAVA_KEYWORDS, _CSHARP_KEYWORDS,
    _JS_KEYWORDS, _PYTHON_KEYWORDS, _SQL_KEYWORDS,
) | frozenset("""
fn let mut impl pub struct enum trait use mod crate where move ref
func range chan go defer package select fallthrough
interface type namespace readonly declare
def defp end do then nil echo local elseif until export require
autocmd filetype true false done esac fi function
""".split())

_C_TYPES = frozenset("int char float double void long short unsigned signed size_t bool auto".split())
_CPP_TYPES = _C_TYPES | frozenset("string vector map set pair".split())
_JAVA_TYPES = frozenset("""
int long double float boolean char byte short String StringBuilder List Map
ArrayList HashMap Set void var Object Exception Integer Double Boolean Long
""".split())
_CSHARP_TYPES = frozenset("""
int string bool object double float decimal char byte long var uint ulong
ushort List Dictionary ArrayList IEnumerable void Task
""".split())
_PYTHON_TYPES = frozenset(
    "int str float bool list dict set tuple bytes object type range frozenset".split()
)

# Rust, Go and the alias forms, on top of every other dialect's type names.
_MIXED_TYPES = frozenset("""
i8 i16 i32 i64 u8 u16 u32 u64 usize isize f32 f64 str String Vec Option
Result char slice
int8 uint8 uint16 uint32 uint64 float32 float64
list map channel
""".split()).union(
    _C_TYPES, _CPP_TYPES, _JAVA_TYPES, _CSHARP_TYPES, _PYTHON_TYPES
)

# Bare words that are meaningful as CSS values. Only consulted in ``css`` and
# ``mixed``; in a real code language an unknown identifier stays plain so a
# variable called ``flex`` is not suddenly a style keyword.
_CSS_VALUES = frozenset("""
red blue green black white grey gray yellow orange purple pink cyan magenta
solid none center centre absolute relative fixed sticky hidden block inline
flex grid column row auto bold italic uppercase lowercase ease linear infinite
both normal wrap pre pointer cover contain border-box content-box baseline
subtract screen hover focus active visited
""".split())

# ``mixed`` also carries Python, Java and shell, where any name in front of a
# colon is an annotation, a dict key or a YAML key rather than a style. In pure
# CSS every such name is a property, so this list only gates the mixed tier.
_CSS_PROPERTIES = frozenset("""
align-content align-items animation appearance aspect-ratio backdrop background
background-color border border-radius bottom box-shadow box-sizing caret-color
clear color column-gap columns content cursor direction display empty-cells
filter flex flex-basis flex-direction flex-flow flex-grow flex-shrink flex-wrap
float font font-family font-size font-style font-variant font-weight gap grid
grid-area grid-auto-flow grid-column grid-gap grid-row grid-template
grid-template-columns grid-template-rows height inset justify-content left
letter-spacing line-height list-style margin mask max-height max-width min-height
min-width object-fit opacity order outline outline-color overflow padding
perspective place-content place-items place-self position resize right row-gap
scroll-behavior text-align text-decoration text-overflow text-shadow
text-transform top transform transition transition-delay unicode-bidi
user-select vertical-align visibility white-space width word-break z-index
""".split())


class _Spec(NamedTuple):
    """One language's scanner: a combined regex plus how to resolve names."""

    pattern: re.Pattern
    kinds: dict[int, str]
    keywords: frozenset
    types: frozenset
    mode: str           # "code", "css", "html" or "mixed"
    fold: bool          # vocabulary is compared case-insensitively


def _compile(rules: list[tuple[str, str]]) -> tuple[re.Pattern, dict[int, str]]:
    """Combine ``(kind, pattern)`` rules into one leftmost-match alternation."""
    parts = []
    kinds: dict[int, str] = {}
    for index, (kind, pattern) in enumerate(rules, start=1):
        parts.append(f"(?P<t{index}>{pattern})")
        kinds[index] = kind
    return re.compile("|".join(parts)), kinds


def _spec(
    rules: list[tuple[str, str]],
    keywords: frozenset,
    types: frozenset = frozenset(),
    *,
    mode: str = "code",
    fold: bool = False,
) -> _Spec:
    pattern, kinds = _compile(rules)
    if fold:
        # SQL and the mixed tier carry mixed-case dialects, so the vocabularies
        # are normalised once here and lookups fold the word the same way.
        keywords = frozenset(word.upper() for word in keywords)
        types = frozenset(word.upper() for word in types)
    return _Spec(pattern, kinds, keywords, types, mode, fold)


def _c_like(keywords: frozenset, types: frozenset) -> _Spec:
    """C, C++, Java, C# and JavaScript: same lexemes, different vocabularies."""
    return _spec(
        [
            (COMMENT, _BLOCK_COMMENT),
            (COMMENT, _SLASH_COMMENT),
            (STRING, _TRIPLE_STRINGS),
            (STRING, _STRINGS),
            (NUMBER, _NUMBER),
            ("ident", _C_IDENT),
            (OPERATOR, _OPERATORS),
        ],
        keywords,
        types,
    )


_CSS_RULES: list[tuple[str, str]] = [
    (COMMENT, _BLOCK_COMMENT),
    (STRING, _TRIPLE_STRINGS),
    (STRING, _STRINGS),
    (KEYWORD, _AT_RULE),
    (NUMBER, _HEX_COLOUR),
    (NUMBER, _NUMBER),
    (SELECTOR, _SELECTOR),
    ("ident", _CSS_IDENT),
    (OPERATOR, _OPERATORS),
]

_HTML_RULES: list[tuple[str, str]] = [
    (COMMENT, _HTML_COMMENT),
    (KEYWORD, _DOCTYPE),
    (TAG, _TAG),
    (ATTRIBUTE, _HTML_ATTRIBUTE),
    (STRING, _STRINGS),
    (OPERATOR, _HTML_PUNCT),
]

# For ``mixed`` the hex-colour rule sits above the ``#`` comment so ``#0ff``
# stays a colour, while ``# note`` still reads as a comment. The attribute rule
# is left out on purpose: ``src=`` only follows a name inside a tag, but in a
# Python line ``x = 1`` would satisfy it and paint the variable as a tag name.
_MIXED_RULES: list[tuple[str, str]] = [
    (COMMENT, _HTML_COMMENT),
    (COMMENT, _BLOCK_COMMENT),
    (COMMENT, _SLASH_COMMENT),
    (COMMENT, _DASH_COMMENT),
    (STRING, _TRIPLE_STRINGS),
    (STRING, _STRINGS),
    (NUMBER, _HEX_COLOUR),
    (COMMENT, _HASH_COMMENT),
    (KEYWORD, _AT_RULE),
    (KEYWORD, _DOCTYPE),
    (NUMBER, _NUMBER),
    (SELECTOR, _SELECTOR),
    (TAG, _TAG),
    ("ident", _C_IDENT),
    (OPERATOR, _OPERATORS),
]

_SPECS: dict[str, _Spec] = {
    "c": _c_like(_C_KEYWORDS, _C_TYPES),
    "cpp": _c_like(_CPP_KEYWORDS, _CPP_TYPES),
    "csharp": _c_like(_CSHARP_KEYWORDS, _CSHARP_TYPES),
    "java": _c_like(_JAVA_KEYWORDS, _JAVA_TYPES),
    "javascript": _c_like(_JS_KEYWORDS, frozenset()),
    "python": _spec(
        [
            (COMMENT, _HASH_COMMENT),
            (STRING, _TRIPLE_STRINGS),
            (STRING, _STRINGS),
            (NUMBER, _NUMBER),
            ("ident", _C_IDENT),
            (OPERATOR, _OPERATORS),
        ],
        _PYTHON_KEYWORDS,
        _PYTHON_TYPES,
    ),
    "sql": _spec(
        [
            (COMMENT, _DASH_COMMENT),
            (STRING, _STRINGS),
            (NUMBER, _NUMBER),
            ("ident", _C_IDENT),
            (OPERATOR, _OPERATORS),
        ],
        _SQL_KEYWORDS,
        fold=True,
    ),
    "css": _spec(_CSS_RULES, frozenset(), mode="css"),
    "html": _spec(_HTML_RULES, frozenset(), mode="html"),
    "mixed": _spec(_MIXED_RULES, _MIXED_KEYWORDS, _MIXED_TYPES, mode="mixed", fold=True),
}

# An unknown language still renders; it just renders flat.
_FLAT = _spec(
    [
        (STRING, _STRINGS),
        (NUMBER, _NUMBER),
        ("ident", _C_IDENT),
        (OPERATOR, _OPERATORS),
    ],
    frozenset(),
)


def _peek(text: str, end: int) -> str:
    """The next non-space character after ``end``, or ``""`` at the end."""
    index = end
    while index < len(text) and text[index] in " \t":
        index += 1
    return text[index] if index < len(text) else ""


def _resolve(spec: _Spec, text: str, token: Token) -> Token:
    """Classify a bare name from its spelling and what follows it.

    ``if`` stays a keyword even though a call follows it, and a name in front of
    a ``:`` reads as a CSS property only where CSS is plausible — which is what
    keeps ``class Stack:`` in a mixed snippet from turning into a style rule.
    """
    if token.kind != "ident":
        return token
    word = text[token.start : token.end]
    probe = word.upper() if spec.fold else word
    if probe in spec.keywords:
        return token._replace(kind=KEYWORD)
    following = _peek(text, token.end)
    if following == "(":
        return token._replace(kind=FUNCTION)
    if probe in spec.types:
        return token._replace(kind=TYPE)
    if spec.mode == "css":
        # Everything that is not a selector, a number or a string is either the
        # name of a declaration or a bare value, so there is nothing left to
        # leave plain.
        if following == ":":
            return token._replace(kind=PROPERTY)
        return token._replace(kind=VALUE)
    if spec.mode == "mixed" and word.lower() in _CSS_PROPERTIES and following == ":":
        return token._replace(kind=PROPERTY)
    if spec.mode == "mixed" and word.lower() in _CSS_VALUES:
        return token._replace(kind=VALUE)
    # Anything left is an ordinary name. It has to land back on "plain" rather
    # than on the scanner's internal placeholder, so every token the renderer
    # sees is a kind that SYNTAX_COLOURS can actually paint.
    return token._replace(kind=PLAIN)


def _merge(tokens: list[Token]) -> tuple[Token, ...]:
    """Fuse neighbouring spans of the same kind.

    Indentation and the punctuation runs between two names would otherwise be
    a blit each, which is the difference between a dozen cached surfaces per
    line and two.
    """
    merged: list[Token] = []
    for token in tokens:
        if merged and merged[-1].kind == token.kind and merged[-1].end == token.start:
            previous = merged[-1]
            merged[-1] = Token(previous.start, token.end, previous.kind)
        else:
            merged.append(token)
    return tuple(merged)


@lru_cache(maxsize=256)
def tokenize(text: str, language: str) -> tuple[Token, ...]:
    """Split ``text`` into syntax spans that cover it exactly once.

    The result always tiles ``range(len(text))`` with no gaps, overlaps or
    out-of-range ends, whatever the language, so a caller can walk it and read
    the original characters back out. Cached per snippet: the same challenge is
    tokenised once at spawn and then re-rendered every frame.
    """
    if not text:
        return ()
    spec = _SPECS.get((language or "").lower(), _FLAT)
    spans: list[Token] = []
    position = 0
    for match in spec.pattern.finditer(text):
        if match.start() > position:
            spans.append(Token(position, match.start(), PLAIN))
        token = Token(match.start(), match.end(), spec.kinds[match.lastindex])
        spans.append(_resolve(spec, text, token))
        position = match.end()
    if position < len(text):
        spans.append(Token(position, len(text), PLAIN))
    return _merge(spans)


class TokenStream:
    """A tokenised snippet, with a lookup for the tokens inside one line."""

    __slots__ = ("text", "language", "tokens", "_starts")

    def __init__(self, text: str, language: str) -> None:
        self.text = text
        self.language = language
        self.tokens = tokenize(text, language)
        self._starts = [token.start for token in self.tokens]

    def between(self, start: int, end: int) -> list[Token]:
        """Tokens overlapping ``[start, end)``, clipped to it and in order.

        ``Game._draw_code`` walks this a line at a time, so the search starts at
        the first token that can reach ``start`` rather than at the top.
        """
        if end <= start or not self._starts:
            return []
        index = bisect_right(self._starts, start) - 1
        if index < 0:
            index = 0
        clipped: list[Token] = []
        for token in self.tokens[index:]:
            if token.start >= end:
                break
            if token.end > start:
                clipped.append(
                    Token(max(token.start, start), min(token.end, end), token.kind)
                )
        return clipped


def kinds_in(text: str, language: str, kind: str) -> list[str]:
    """The substrings of ``text`` tokenised as ``kind``.

    Test and diagnostic helper: it turns a span list back into readable source,
    which is how the tokenizer is checked against the real snippets.
    """
    return [
        text[token.start : token.end]
        for token in tokenize(text, language)
        if token.kind == kind
    ]
