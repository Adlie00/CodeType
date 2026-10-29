"""
Shared constants for CODETYPE.
Edit values here; do not scatter magic numbers across modules.
"""

# ── Display ──────────────────────────────────────────────────────────────────
# The UI is authored against this design resolution and scaled uniformly to
# whatever the display actually is. A uniform scale applied to every pixel
# distance *and* every pixels-per-second speed leaves the game exactly as fair
# at 4K as it is at 720p: ratios of distance to speed are preserved, so descent
# times do not drift with resolution.
DESIGN_WIDTH   = 1280
DESIGN_HEIGHT  = 720
DEFAULT_WIDTH  = 1920
DEFAULT_HEIGHT = 1080
TARGET_FPS     = 60

# Clamp range for the uniform UI scale. Below MIN_SCALE a panel stops holding a
# useful amount of text; above MAX_SCALE the title and banners dominate. The
# ceiling is high enough that a 4K monitor runs at its native scale rather than
# being letterboxed by a clamp.
MIN_SCALE = 0.55
MAX_SCALE = 3.20

# Sanity bounds for a stored *windowed* size, so a hand-edited settings file or
# an absurd value cannot ask for a surface no desktop can provide.
MIN_WINDOW_WIDTH  = 960
MIN_WINDOW_HEIGHT = 540
MAX_WINDOW_WIDTH  = 7680
MAX_WINDOW_HEIGHT = 4320

# Windowed presets offered on the settings screen, smallest last so arrowing
# right walks up towards full HD. Anything above the desktop is filtered out at
# runtime and replaced by the monitor's own size.
WINDOW_PRESETS = (
    (1280, 720),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
)

# ── Colours (R, G, B) ────────────────────────────────────────────────────────
BLACK        = (0,   0,   0)
WHITE        = (255, 255, 255)
DARK_BG      = (8,   8,   20)
PANEL_BG     = (12,  12,  32)
NEON_CYAN    = (0,   230, 255)
NEON_GREEN   = (0,   255, 128)
NEON_PURPLE  = (160, 32,  240)
NEON_ORANGE  = (255, 140, 0)
NEON_RED     = (255, 40,  40)
NEON_YELLOW  = (255, 230, 0)
NEON_PINK    = (255, 64,  168)
DIM_CYAN     = (0,   120, 140)
DIM_GREEN    = (0,   130, 64)
GREY         = (120, 120, 140)
DARK_GREY    = (40,  40,  60)
PB_HIGHLIGHT = (0,   46,  72)   # personal-best row fill in leaderboard

# Elevated surfaces and hairlines. Kept separate from PANEL_BG so a screen can
# stack a raised card on a panel without hand-picking another dark grey.
SURFACE         = (18,  20,  48)
SURFACE_RAISED  = (28,  31,  70)
HAIRLINE        = (66,  74, 128)
HAIRLINE_DIM    = (38,  42,  80)
TEXT_DIM        = (132, 140, 172)
TEXT_BRIGHT     = (232, 240, 255)

# Typed / remaining text colours
TYPED_COLOUR     = NEON_GREEN
REMAINING_COLOUR = WHITE
ERROR_COLOUR     = NEON_RED
CURSOR_COLOUR    = NEON_CYAN

# Syntax highlighting palette, keyed by the token kinds emitted by
# game/syntax.py. Green is deliberately absent: it is reserved for TYPED_COLOUR
# so the typed/untyped boundary stays readable at a glance.
SYNTAX_COLOURS = {
    "keyword":   NEON_PINK,        # if / for / SELECT / def
    "type":      NEON_CYAN,        # int / str / MyError
    "string":    NEON_YELLOW,      # "text" / 'x' / #0ff-ish constants
    "number":    NEON_ORANGE,      # 42 / 1.5 / 200ms
    "comment":   (92, 100, 145),   # dim so it recedes behind the code
    "function":  (200, 130, 255),  # open() / COUNT(...)
    "operator":  (124, 134, 178), # = + -> ::
    "tag":       NEON_CYAN,        # <div>
    "attribute": NEON_YELLOW,      # class=
    "property":  (120, 220, 255),  # color:
    "selector":  NEON_PINK,        # .btn / #main
    "value":     (200, 215, 255),  # bare words in CSS values
    "plain":     REMAINING_COLOUR,
}

# ── Layout geometry ──────────────────────────────────────────────────────────
# All values below are expressed in DESIGN_WIDTH x DESIGN_HEIGHT space and are
# multiplied by the uniform UI scale (see game/ui.py:Layout) before use.
HUD_HEIGHT            = 78
# The field runs to the bottom of the surface. The warning line still sits a
# margin above the edge so the hazard band is fully visible.
FIELD_BOTTOM_MARGIN   = 26
ENEMY_WIDTH           = 390
ENEMY_MAX_HEIGHT      = 195
ENEMY_MAX_LINES       = 6
ENEMY_MIN_GAP         = 150
# The field is split into evenly spaced lanes and every spawn takes a random
# free one, so code arrives from across the screen instead of a single column.
# ENEMY_COLUMN_X stays the leftmost lane.
ENEMY_COLUMN_X        = 60
ENEMY_COLUMNS         = 3
ENEMY_HEADER_HEIGHT   = 33
ENEMY_LINE_HEIGHT     = 22
# Strip under the code lines that holds the health meter.
ENEMY_FOOTER_HEIGHT   = 21
# Sideways drift amplitudes. A Special sweeps far enough that the target keeps
# moving under the caret; a Fast just shivers. Both are design-space distances.
ENEMY_SWAY_SPECIAL    = 46
ENEMY_SWAY_FAST       = 5
BOSS_INTRO_SECONDS    = 2.2
# A boss card is the longest in the game and falls at the slowest base speed.
# It descends to the warning line like any other enemy, but the fairness cap in
# Enemy.limit_speed_for bounds it against its own typing time so it cannot cross
# before the player could reasonably have finished it.
BOSS_SWAY             = 6
BOSS_WIDTH_BONUS      = 70
WARNING_BAND_HEIGHT   = 26

# How far below the HUD the field has to be clear before another enemy is
# allowed to spawn, so a fresh code card never materialises on top of a
# half-typed one.
SPAWN_CLEARANCE_MARGIN = 150

# ── Difficulty ────────────────────────────────────────────────────────────────
DIFFICULTY_EASY   = "EASY"
DIFFICULTY_MEDIUM = "MEDIUM"
DIFFICULTY_HARD   = "HARD"
DIFFICULTY_EXPERT = "EXPERT"

DIFFICULTY_ORDER = [DIFFICULTY_EASY, DIFFICULTY_MEDIUM,
                    DIFFICULTY_HARD, DIFFICULTY_EXPERT]

# ── Snippets ───────────────────────────────────────────────────────────────────
# Every shipped snippet is a single line, and a single line has to fit the
# code area of an enemy card. The card is ENEMY_WIDTH wide and the renderer
# draws text inside a padding, leaving roughly 370px. At the smallest font the
# renderer will fall back to (see _CODE_SIZE_MIN in game/game.py) that fits
# about 56 characters; past that the text is clipped rather than made small
# enough to read. Content is authored to this budget so difficulty comes from
# what the code does, not from squeezing a long line onto a small card.
MAX_SNIPPET_LENGTH = 56

# ── Enemy types ───────────────────────────────────────────────────────────────
ENEMY_NORMAL  = "normal"
ENEMY_FAST    = "fast"
ENEMY_TANK    = "tank"
ENEMY_SPECIAL = "special"
ENEMY_BOSS    = "boss"

# Display colour per enemy type (README enemy table).
ENEMY_COLOURS = {
    ENEMY_NORMAL:  NEON_CYAN,
    ENEMY_FAST:    NEON_GREEN,
    ENEMY_TANK:    NEON_ORANGE,
    ENEMY_SPECIAL: NEON_PURPLE,
    ENEMY_BOSS:    NEON_RED,
}

# Base fall speed in pixels per second before the difficulty multiplier. Tuned
# against the design travel, so these are really "seconds to the warning line".
# Bumped ~10% across the board to tighten the pace; long snippets still fall
# under the fairness cap in Enemy.limit_speed_for, so only short enemies sped up.
ENEMY_BASE_SPEEDS = {
    ENEMY_NORMAL:  42.0,
    ENEMY_FAST:    68.0,
    ENEMY_TANK:    27.5,
    ENEMY_SPECIAL: 52.0,
    ENEMY_BOSS:    18.0,
}

# Challenge length preference per enemy type: how many picks are taken from the
# shortest end or the longest end of a difficulty tier's challenge pool.
ENEMY_LENGTH_BIAS = {
    ENEMY_NORMAL:  0.5,
    ENEMY_FAST:    0.0,
    ENEMY_TANK:    1.0,
    ENEMY_SPECIAL: 0.5,
    ENEMY_BOSS:    0.5,
}

# ── Boss ──────────────────────────────────────────────────────────────────────
DIFFICULTY_BOSS = "BOSS"
# Health-ratio thresholds crossed in order as the boss is typed out. The
# README bands are 0-33% red, 33-66% orange, 66-100% yellow, so phase 2
# begins at 0.66 remaining health and phase 3 at 0.33.
BOSS_PHASE_BREAKS = (0.66, 0.33)
BOSS_PHASE_COLOURS = (NEON_RED, NEON_ORANGE, NEON_YELLOW)

# ── Game modes ────────────────────────────────────────────────────────────────
MODE_CAMPAIGN    = "campaign"
MODE_ENDLESS     = "endless"
MODE_COMPETITION = "competition"
MODE_TOURNAMENT  = "tournament"
MODE_WARMUP      = "warmup"
MODE_ARCADE      = "arcade"
# Warmup is a timed, unscored practice session: no lives, and the clock is the
# only thing that ends it. Runs are never recorded on the leaderboard.
WARMUP_SECONDS   = 30.0
# Arcade is the timed score attack: 120s on the clock, no lives, and every kill
# buys seconds back. The bonus is deliberately generous so an elite player can
# chain kills into a much longer run — that chain *is* the skill ceiling — while
# a run that never keeps up ends at the starting clock. Runs are recorded on
# the leaderboard's arcade board.
ARCADE_SECONDS     = 120.0
ARCADE_KILL_SECONDS = 2.0
ARCADE_BOSS_SECONDS = 8.0
# Competition runs a shorter ladder than the ten-wave campaign: five waves fit
# one representative attempt inside a tournament round.
COMPETITION_WAVE_COUNT = 5

# ── Scoring ───────────────────────────────────────────────────────────────────
#   total = (base + wave + speed + accuracy) x difficulty x combo x boss
BASE_SCORE_PER_CHAR      = 10
DIFFICULTY_MULTIPLIERS   = {
    DIFFICULTY_EASY:   1.0,
    DIFFICULTY_MEDIUM: 1.5,
    DIFFICULTY_HARD:   2.5,
    DIFFICULTY_EXPERT: 4.0,
}
COMBO_MULTIPLIER_STEP   = 0.1
COMBO_MULTIPLIER_CAP    = 5.0
SPEED_BONUS_THRESHOLD   = 60
SPEED_BONUS_PER_WPM     = 5
WAVE_BONUS_PER_WAVE     = 50
PERFECT_ACCURACY_BONUS  = 500
ACCURACY_BONUS_RATE     = 0.1
BOSS_MULTIPLIER         = 3.0

# Combo counts that trigger a milestone burst and the combo sound effect.
COMBO_MILESTONES        = (5, 10, 20, 35, 50)
# HUD combo colour shifts at each milestone threshold (combo count → colour).
COMBO_COLOURS = {
    0:  (232, 240, 255),   # TEXT_BRIGHT
    5:  (0,   230, 255),   # NEON_CYAN
    10: (0,   255, 128),   # NEON_GREEN
    20: (255, 140, 0),     # NEON_ORANGE
    35: (255, 230, 0),     # NEON_YELLOW
    50: (255, 64,  168),   # NEON_PINK
}

# ── Metrics ───────────────────────────────────────────────────────────────────
WPM_WINDOW_SECONDS      = 5.0
WPM_WORD_LENGTH         = 5

# ── Endless mode ──────────────────────────────────────────────────────────────
ENDLESS_BOSS_EVERY      = 20

# ── Pacing ────────────────────────────────────────────────────────────────────
# Two independent knobs. Enemy descent is governed by DESCENT_REFERENCE_CPS and
# is deliberately generous: it guarantees any single enemy can be typed out
# before it reaches the line. Spawn pacing is governed by SPAWN_PACING_CPS and
# controls how brisk the waves feel. Keeping them separate means tightening the
# pace no longer makes enemies unfairly fast.
#
# waves.json supplies the *minimum* interval for a wave; both floors are derived
# from the actual snippet length so a 380-character EXPERT snippet gets the time
# it needs instead of the nominal 1.6s the wave config asks for.
DESCENT_REFERENCE_CPS  = 8.0
SPAWN_PACING_CPS       = 12.0
MIN_SPAWN_INTERVAL     = 0.6

# ── Lives ─────────────────────────────────────────────────────────────────────
STARTING_LIVES = 3
MAX_LIVES      = 5

# ── Paths ─────────────────────────────────────────────────────────────────────
import os
import sys

BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR       = os.path.join(BASE_DIR, "data")
LANGUAGES_DIR  = os.path.join(DATA_DIR, "languages")
ASSETS_DIR     = os.path.join(BASE_DIR, "assets")
FONTS_DIR      = os.path.join(ASSETS_DIR, "fonts")
SOUNDS_DIR     = os.path.join(ASSETS_DIR, "sounds")
IMAGES_DIR     = os.path.join(ASSETS_DIR, "images")
WAVES_FILE     = os.path.join(DATA_DIR, "waves.json")

# Bundled content (languages, assets, waves) lives beside the code in every
# build. The two *writable* files — settings and the leaderboard — do not:
# inside a frozen build BASE_DIR is PyInstaller's _internal folder, which lives
# inside the game directory. Writing there breaks the moment a player installs
# to Program Files (UAC blocks it silently) and loses the leaderboard whenever
# the game folder is replaced by an update. So in a frozen build they move to
# %APPDATA%\CODETYPE, which is writable and survives updates. Running from
# source keeps the old layout, so development is unchanged.
if getattr(sys, "frozen", False):
    SAVE_DIR = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "CODETYPE"
    )
    DATABASE_DIR  = os.path.join(SAVE_DIR, "database")
    SETTINGS_FILE = os.path.join(SAVE_DIR, "settings.json")
else:
    DATABASE_DIR  = os.path.join(BASE_DIR, "database")
    SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DB_FILE        = os.path.join(DATABASE_DIR, "codetype.db")
# Tournament constants
TOURNAMENT_NAME = "COMPETITION"
TOURNAMENT_TEAM_COUNT = 5
TOURNAMENT_PLAYERS_PER_TEAM = 5
TOURNAMENT_TEAM_NUMBERS = (1, 2, 3, 4, 5)
TOURNAMENT_PLAYER_NUMBERS = (1, 2, 3, 4, 5)
TOURNAMENT_DIFFICULTY = DIFFICULTY_EASY
TOURNAMENT_RESULTS_FILE = os.path.join(DATABASE_DIR, "tournament_results.csv")
