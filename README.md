# CODETYPE

A neon arcade typing game. Code snippets descend from the top of the screen; type
them exactly, character for character, before they cross the warning line. Miss
one and they escape. Let too many through and the run is over.

Written in Python with Pygame.

---

## Quick start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Requires Python 3.11+ and Pygame 2.5+.

## Controls

| Key | Action |
| --- | --- |
| any character | Type the next expected character |
| `Backspace` | Delete the last character you typed |
| `Tab` | Type a literal tab character |
| `Space` | Type a space |
| `Enter` | Type a literal newline |
| `Esc` | Pause / resume during a run |
| `M` | Abandon the run and return to the main menu |
| `F11` | Anywhere: toggle borderless fullscreen at the monitor's own resolution |
| `F12` | Leaderboard only: clear the stored scores (asks for confirmation) |

Menus accept both arrow keys and `WASD`. `Enter`, `Space`, or `Return` confirms;
`N` renames a leaderboard entry; `Esc` backs out.

`F11` works on every screen, including mid-run, and is intercepted before the game
sees the key so it is never typed into a snippet. Toggling it off returns to the
window size you had chosen rather than to the fullscreen resolution.

You do not need to aim or click. The game always targets one enemy at a time,
so the whole game is played from the home row.

---

## The core loop

1. Pick a mode and, if you want, a difficulty tier.
2. Code snippets spawn at the top and fall toward the **warning line**.
3. A target is chosen automatically; type its characters in order. The active
   card is marked in place, on the card itself, with an `ACTIVE` pill, a thicker
   border, and corner ticks.
   - Correct characters turn green.
   - Wrong characters flash red, break the combo, and cost accuracy.
   - A card shows its code on **one line**, set as large as it will fit on the
     card. The renderer still tracks lines, so a card would page through a
     multi-line snippet with Enter — but no shipped snippet needs that.
4. Clear a snippet to destroy it and bank score. Let it fall past the line and
   you lose a life.
5. Clear every snippet in a wave to advance. Lose all lives and the run ends.

Lives: 3

### Enemies

Every enemy is a code snippet, and its *length* drives how hard it is to handle.

| Type | Colour | Behaviour |
| --- | --- | --- |
| **Normal** | Cyan | Descends at a steady rate in a straight line. |
| **Fast** | Green | Falls faster and shivers rapidly side to side (±5 px). |
| **Special** | Purple | Drifts widely side to side as it falls (±46 px), so the target keeps moving. |
| **Tank** | Orange | Falls slowest, sits still, and pulses gently. Has the longest health bar, since it is assigned the longest snippets. |
| **Boss** | Red → Orange → Yellow | See below. |

Enemies are assigned types by snippet length, so a long snippet is usually a
Tank and a short one is usually a Fast. Waves pick from a length-biased pool
depending on difficulty, which keeps a tier's workload in a sane band.

### Bosses

Waves 3, 5, 7, 9, and 10 each end in a boss, and endless mode spawns one every
20 kills.

A boss announces itself, slides in, and then **descends slowly toward the warning
line** in one of the field's lanes. Its snippet is the longest in the game, so
its base speed is the slowest of any enemy and the fairness cap slows it further
so it cannot cross before you could reasonably type it out. It is still a threat:
let it reach the line and you lose a life. While a boss is on screen, normal
enemies stop spawning, so the fight is a single, wide typing test. Bosses have
three health phases (full → 66% → 33%), each change recolouring the boss and
triggering a flash. Boss kills are worth 3× score.

---

## Modes

| Mode | Description |
| --- | --- |
| **Campaign** | The 10-wave ladder below. Clearing wave 10 wins the run. |
| **Endless** | Procedurally generated waves that keep getting faster (spawn interval decays from 4.0s toward a 1.0s floor), drawing a random language each wave. A boss appears every 20 kills. Survive as long as you can. |
| **Arcade** | A 2-minute score attack on the endless wave schedule. No lives — the clock is the only thing that ends the run — and every kill buys seconds back (+2s, +8s for a boss) so a fast chain can stretch a 120s run much longer. Recorded on its own leaderboard board. |
| **Competition** | The same 10 waves as Campaign, scored and recorded separately on the leaderboard. |
| **Warmup** | A 30-second, unscored practice run with no lives, drawing a random language each wave. When the clock runs out it shows a summary; runs are never recorded on the leaderboard. |

## The campaign ladder

| Wave | Language | Tiers | Enemies | Boss |
| --- | --- | --- | --- | --- |
| 1 | HTML | Easy, Medium | 12 | — |
| 2 | CSS | Easy, Medium | 14 | — |
| 3 | JavaScript | Easy, Medium, Hard | 16 | yes |
| 4 | Python | Medium, Hard | 16 | — |
| 5 | Java | Medium, Hard | 18 | yes |
| 6 | C | Medium, Hard | 18 | — |
| 7 | C++ | Medium, Hard, Expert | 20 | yes |
| 8 | C# | Hard, Expert | 20 | — |
| 9 | SQL | Medium, Hard, Expert | 20 | yes |
| 10 | MIXED | Hard, Expert | 25 | yes |

Wave definitions live in `data/waves.json`; the snippets themselves live in
`data/languages/`. There are 386 snippets across ten languages, and every
tier pool is large enough to cover the enemies its wave draws from it — so a
wave never recycles the same snippet just because the pool was small.

**Every snippet is a single line, and at most 56 characters long.** That is a
hard limit enforced in three places, not a style preference:

- `MAX_SNIPPET_LENGTH` in `game/constants.py` is the single budget.
- `ContentRepository` refuses to load a snippet that contains a newline or
  exceeds the budget, so a bad content file fails at startup with a clear
  message rather than rendering clipped text.
- `test_every_snippet_fits_on_one_line` asserts both rules for all 386 entries.

The reason is the card. A card is 390px wide, and the text area inside it is
about 370px. Even the smallest font the renderer will fall back to fits only
roughly 56 characters; past that the text is *clipped*, not shrunk to fit.
Keeping the whole snippet on one line is what lets the card show it complete at
a size you can actually read, and it is why `print("hello world")` is a valid
Hard-tier challenge.

Snippets are otherwise written to be typeable rather than idiomatic: short
names, at most one level of nesting, and as few shift-layer characters
(`_ ~ | < > { }`) as the language allows. Difficulty comes from snippet length
and wave pacing, not from punishing punctuation.

### Difficulty tiers

| Tier | Score multiplier | Max enemies on screen | Relative pace |
| --- | --- | --- | --- |
| Easy | 1.0× | 2 | Slower fall, wider gaps |
| Medium | 1.5× | 2 | Baseline |
| Hard | 2.5× | 2 | Faster fall, tighter gaps |
| Expert | 4.0× | 3 | Fastest fall, tightest gaps |

A tier scales score, how fast enemies fall, how tightly they are packed, and the
enemy type mix. Waves list the tiers they draw from, and the tier **escalates
across the wave** as enemies are destroyed — a wave marked `Easy, Medium` opens
on Easy and steps up to Medium partway through. Endless mode uses a single
tier that steps up one level per wave, starting at Easy.

---

## Scoring

Every cleared snippet is worth, in order:

```
base        = character_count × 10
wave bonus  = wave_number × 50
speed bonus = (WPM − 60) × 5            capped at 2500
accuracy    = 500 if accuracy is a perfect 100%
              otherwise base × accuracy% × 0.1
```

The subtotal is then multiplied:

```
total = subtotal × difficulty × combo × boss
```

- **difficulty** — from the tier table above.
- **combo** — `1.0 + (combo − 1) × 0.1`, capped at **5.0×**.
- **boss** — `3.0` for a boss, otherwise `1.0`.

A 100-character Expert snippet cleared at 120 WPM with a 40 combo and no
mistakes is worth roughly `100×10 + 400 + 300 + 500 = 2200`, multiplied by
`4.0 × 4.9 × 1.0 ≈ 43,120`. Accuracy and combo are the real levers.

**Combo milestones** fire a banner and a sound at 5, 10, 20, 35, and 50
consecutive clean snippets.

**WPM** is a 5-second rolling window measured in 5-character "words". The
window ignores the first second of typing so the very first keystrokes cannot
report an absurd speed.

---

## Leaderboard

Scores are stored in a local SQLite database at `database/codetype.db` — no
account, no network. Each row keeps the player name, score, WPM, accuracy, max
combo, waves cleared, enemies destroyed, mode, and timestamp.

| Key | Action |
| --- | --- |
| `S` | Cycle the sort column (score, WPM, accuracy) |
| `R` | Refresh the list |
| `F12` | Clear all stored scores, then confirm with `Y` / `Enter` (or cancel with `N`) |
| `Esc` | Back to the main menu |

## Settings

Persisted to `data/settings.json`, adjustable in-game from the settings screen:

| Setting | Key in `settings.json` | Default | Notes |
| --- | --- | --- | --- |
| Window size | `width`, `height` | 1920×1080 | Remembered across runs. Clamped to the monitor when the game starts. |
| Fullscreen | `fullscreen` | `false` | Borderless at the monitor's own resolution, not a letterboxed desktop. |
| Master volume | `master_volume` | 0.8 | |
| Music volume | `music_volume` | 0.5 | No music is bundled yet, so this is a placeholder until a track is added. |
| SFX volume | `sfx_volume` | 0.8 | |
| Typing effects | `typing_effects` | `true` | Particles and floating score popups. |
| Screen shake | `screen_shake` | `true` | Camera shake on impacts. |

Turning typing effects or screen shake off takes effect immediately and clears
anything already in flight.

### Resolution independence

The UI is authored against a 1280×720 design grid and scaled uniformly to the
window, so the game looks the same on a 720p laptop and a 4K monitor instead of
growing text and panels by hand. Two consequences are worth knowing:

- **Scaling is uniform, not per-axis.** A 1024×600 window is width-limited, so
  it scales by width and keeps a 16:9 letterbox rather than stretching
  horizontally.
- **Difficulty does not depend on window size.** Speeds are derived from the
  distance an enemy actually travels, not from the raw scale, so a 4:3 window
  that has spare vertical space also gets proportionally faster enemies. The
  time from spawn to the warning line is the same at every size, which
  `tests/test_stage5.py` asserts for each supported resolution.

Presets offered on the settings screen are 1280×720, 1600×900, 1920×1080, and
2560×1440, filtered to those that fit the current monitor.

The window can be resized at any time, including mid-run, and `F11` toggles
borderless fullscreen from any screen. Both hand the live screens a new surface,
so each one re-derives its UI, and the running game re-derives its layout and
re-scales the enemies in flight.

## Audio

All sound is generated locally as WAV files by `tools/generate_sounds.py` —
there are no third-party audio assets to license. `boss.wav` plays both when a
boss arrives and when one is destroyed.

---

## Project layout

```
main.py               entry point
game/                 engine
  constants.py        geometry, colours, scoring and pacing knobs
  game.py             run orchestration, spawning, collision, rendering
  enemy.py            the falling-enemy model
  boss.py             boss behaviour and phases
  wave_manager.py     campaign / endless wave sequencing
  content.py          loads and biases the snippet pools
  difficulty.py       per-tier profiles
  scoring.py          the score formula
  wpm.py              rolling words-per-minute
  game_state.py       lives, combo, accuracy, stats
  typing_engine.py    per-enemy character matching
  effects.py          particles, popups, screen shake
  audio_manager.py    sound loading and mixing
  settings.py         persisted settings
  leaderboard.py      SQLite storage
  asset_manager.py    font and image loading
  display.py          display creation, fullscreen, resolution presets
  player.py           the typing target
  ui.py               shared UI vocabulary and the scaled Layout
screens/              one module per screen
data/                 waves.json, languages/, settings.json
assets/               fonts/, images/, sounds/
tools/                sound and icon generators
tests/                unittest suite
```

### Pacing constants

Three values in `game/constants.py` govern fairness, and they are deliberately
independent so they can be tuned separately:

| Constant | Default | Effect |
| --- | --- | --- |
| `DESCENT_REFERENCE_CPS` | 8.0 | How fast an enemy may fall, in characters-per-second of snippet. Long snippets fall slowly. |
| `SPAWN_PACING_CPS` | 12.0 | Minimum time between spawns, derived from the queued snippet's length. |
| `MIN_SPAWN_INTERVAL` | 0.6 | Floor on that interval, in seconds. |

Enemies also cap their speed against the typing time of the whole queue ahead of
them, because you can only type one snippet at a time. That cap uses the *actual*
summed length of the snippets already on the field plus the one arriving, not an
average: a short snippet behind a long one would otherwise be given too little
time and cost you a life however well you typed it. These three knobs are what
make every tier winnable at a realistic WPM instead of demanding impossible
throughput, and `tests/test_stage5.py` pins the guarantee.

---

## Building a standalone executable

```bat
build.bat
```

Runs PyInstaller in `--onedir` mode and writes `dist\CODETYPE\CODETYPE.exe`.
It bundles `data/`, `assets/`, and `database/`, and uses
`assets/images/icon.ico`.

The icon is generated, not hand-drawn:

```bash
python tools/generate_icon.py
```

Same for the audio:

```bash
python tools/generate_sounds.py
```

## Tests

```bash
python -m unittest discover -s tests -t .
```

148 tests covering scoring, WPM, difficulty, wave sequencing, boss behaviour,
enemy movement, spawn lanes, content loading and depth, effects, audio, end-to-end
runs of a single wave, display layout, and code-card syntax highlighting. They run
headless (dummy SDL drivers), so no window is required.

`tests/test_stage5.py` guards the resolution-independence work specifically:
geometry containment, the uniform-scale contract, and the pacing invariant that
keeps time-to-danger-line constant across window sizes and aspect ratios. It also
draws every screen at every window preset plus two awkward off-preset aspect
ratios, and checks each one actually put pixels on the surface and is holding a UI
built for the surface it is drawing on.

One thing that per-screen check cannot see is what was on the surface *before* the
screen drew. Every menu sits on a full-bleed gradient wash, and that wash is
opaque: it is what keeps a finished run from showing through the main menu when
you press Esc. `BackdropTests` pins that down, by filling a surface with a sentinel
colour and requiring the wash to cover all of it, and by requiring the main menu
drawn over a live gameplay frame to be byte-identical to the same menu drawn over
black.

`tests/test_syntax.py` guards the syntax highlighting. The tokenizer has to be
exactly right in a way that is easy to get subtly wrong: if its tokens do not
tile the source, the typing index stops lining up with the character under the
caret. So it asserts that every shipped snippet's tokens cover it with no gaps,
no overlaps and no out-of-range spans, that `TokenStream.between()` rebuilds any
slice, and that the renderer emits its runs left to right in order at every
cursor position, including the ones landing mid-token. It also draws all 386
snippets at five cursor positions each, so no language or tier slips past an
unexercised branch in the renderer.

Because a card only ever shows one line, the same file also pins the things that
one-line-at-a-time makes easy to get wrong: that exactly one line is drawn and it
is the cursor's line, that a line stays on screen until its own newline has been
typed (this is what makes the card advance on Enter), that the fitted font never
lets a line spill past the card's edge, and that a short line really does get set
larger than a long one on a card of the same height.

---

## Notes on the design

A few decisions worth calling out, because they are not obvious from the code:

- **Bosses descend, just slowly.** Boss snippets run roughly 240–400
  characters. A boss that fell at a normal enemy's pace would pass the warning
  line while you were still halfway through it, which is neither a threat nor a
  fair challenge. So a boss uses the slowest base speed in the game and is
  bounded by the same fairness cap as every other enemy: the cap divides the
  remaining travel by the real typing time of its snippet, so it reaches the
  line only once you could reasonably have finished it. Normal spawns pause
  while it lasts, so the fight is a single, wide typing test — but a boss you
  ignore still costs a life.
- **Cards take a lane, not a fixed column.** The field is split into three
  evenly spaced lanes and each spawn takes a random one, so code arrives from
  across the screen instead of always sliding down the left edge. A lane is
  stored as a fraction of the usable band, which keeps a card in the same place
  relative to the field across a resize. A new card never takes a lane that is
  already occupied, because the cards are drawn opaque and would hide each other.
- **`Esc` pauses, `M` quits to the menu.** A single key cannot do both without
  ambiguity, and losing a run to a stray keypress is worse than one extra key.
- **Content depth is enforced, not assumed.** Every tier pool must cover the
  number of enemies its wave actually draws from that tier, computed with the
  same tier-distribution function the game uses at spawn time, so no wave
  recycles a snippet just because the pool was small. Snippets are also split
  into length bands so a Fast enemy never draws a Tank-sized snippet.
- **There is no target panel.** The active card is identified in place, by the
  `ACTIVE` pill, the thicker border, and the corner ticks, rather than by a
  read-out of its text along the bottom edge. That strip used to be 112 px of
  reserved height; the field now runs down to a 26 px margin, so a card has to
  travel further before it reaches the warning line. The typed/remaining split
  and the progress meter are still drawn on the card itself.
- **Combo is a per-snippet streak**, not a per-character one. It increments once
  a snippet is destroyed and resets on any wrong character or on letting a
  snippet escape.
