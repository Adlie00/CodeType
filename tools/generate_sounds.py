"""
Generates the placeholder sound effects CODETYPE expects in assets/sounds/.

The game runs silently when these files are absent, so this script exists to
make the audio pipeline audible out of the box. Replace any generated file
with a real sample of the same name and the game will pick it up unchanged.

Usage:
    python tools/generate_sounds.py
    python tools/generate_sounds.py --force
"""

from __future__ import annotations

import argparse
import math
import os
import random
import struct
import sys
import wave


RATE = 22050
CHANNELS = 1
SAMPLE_WIDTH = 2

try:
    from game.constants import SOUNDS_DIR
except ModuleNotFoundError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from game.constants import SOUNDS_DIR


def _envelope(index: int, total: int, attack: float = 0.02, release: float = 0.6) -> float:
    """Simple attack/release shape so samples do not click."""
    if total <= 1:
        return 0.0
    position = index / (total - 1)
    if position < attack:
        return position / attack
    decay_span = max(1e-6, 1.0 - attack)
    relative = (position - attack) / decay_span
    return max(0.0, (1.0 - relative) ** (1.0 / max(0.05, release)))


def _square(phase: float, duty: float = 0.5) -> float:
    return 1.0 if (phase % 1.0) < duty else -1.0


def _saw(phase: float) -> float:
    return 2.0 * (phase % 1.0) - 1.0


def _tone(
    seconds: float,
    start_hz: float,
    end_hz: float | None = None,
    waveform: str = "square",
    duty: float = 0.5,
    volume: float = 0.35,
    attack: float = 0.02,
    release: float = 0.6,
    vibrato_hz: float = 0.0,
    vibrato_depth: float = 0.0,
) -> list[float]:
    total = max(1, int(RATE * seconds))
    end_hz = start_hz if end_hz is None else end_hz
    samples: list[float] = []
    phase = 0.0
    for index in range(total):
        position = index / total
        frequency = start_hz + (end_hz - start_hz) * position
        if vibrato_hz and vibrato_depth:
            frequency *= 1.0 + vibrato_depth * math.sin(math.tau * vibrato_hz * index / RATE)
        phase += frequency / RATE
        if waveform == "square":
            value = _square(phase, duty)
        elif waveform == "saw":
            value = _saw(phase)
        else:
            value = math.sin(math.tau * phase)
        samples.append(value * volume * _envelope(index, total, attack, release))
    return samples


def _noise(
    seconds: float,
    volume: float = 0.3,
    attack: float = 0.005,
    release: float = 0.5,
    low_pass: float = 0.35,
    seed: int = 0,
) -> list[float]:
    rng = random.Random(seed)
    total = max(1, int(RATE * seconds))
    samples: list[float] = []
    previous = 0.0
    for index in range(total):
        raw = rng.uniform(-1.0, 1.0)
        previous += (raw - previous) * low_pass
        samples.append(previous * volume * _envelope(index, total, attack, release))
    return samples


def _mix(*layers: list[float]) -> list[float]:
    length = max((len(layer) for layer in layers), default=0)
    mixed = [0.0] * length
    for layer in layers:
        for index, value in enumerate(layer):
            mixed[index] += value
    peak = max((abs(value) for value in mixed), default=0.0)
    if peak > 1.0:
        mixed = [value / peak for value in mixed]
    return mixed


def _sequence(*chunks: list[float]) -> list[float]:
    out: list[float] = []
    for chunk in chunks:
        out.extend(chunk)
    return out


# ── Individual effects ────────────────────────────────────────────────────────


def type_correct() -> list[float]:
    return _tone(0.045, 880.0, 1180.0, "square", 0.5, 0.30, 0.01, 0.35)


def type_wrong() -> list[float]:
    return _mix(
        _tone(0.10, 150.0, 96.0, "saw", 0.5, 0.30, 0.005, 0.5),
        _noise(0.07, 0.10, 0.005, 0.4, 0.6, seed=3),
    )


def destroy() -> list[float]:
    return _mix(
        _tone(0.30, 520.0, 90.0, "saw", 0.5, 0.26, 0.005, 0.7),
        _noise(0.28, 0.22, 0.004, 0.7, 0.45, seed=11),
    )


def combo() -> list[float]:
    return _sequence(
        _tone(0.075, 660.0, 660.0, "square", 0.5, 0.26, 0.01, 0.4),
        _tone(0.075, 880.0, 880.0, "square", 0.5, 0.26, 0.01, 0.4),
        _tone(0.16, 1320.0, 1320.0, "square", 0.35, 0.26, 0.01, 0.5),
    )


def boss() -> list[float]:
    return _mix(
        _tone(0.75, 190.0, 62.0, "saw", 0.5, 0.30, 0.02, 0.9),
        _tone(0.75, 95.0, 48.0, "square", 0.3, 0.20, 0.02, 0.9),
        _noise(0.55, 0.16, 0.02, 0.8, 0.25, seed=29),
    )


def wave_clear() -> list[float]:
    return _sequence(
        _tone(0.11, 523.0, 523.0, "square", 0.5, 0.24, 0.01, 0.5),
        _tone(0.11, 659.0, 659.0, "square", 0.5, 0.24, 0.01, 0.5),
        _tone(0.11, 784.0, 784.0, "square", 0.5, 0.24, 0.01, 0.5),
        _tone(0.30, 1046.0, 1046.0, "square", 0.4, 0.24, 0.01, 0.7),
    )


def game_over() -> list[float]:
    return _sequence(
        _tone(0.20, 440.0, 415.0, "saw", 0.5, 0.26, 0.01, 0.6),
        _tone(0.20, 349.0, 330.0, "saw", 0.5, 0.26, 0.01, 0.6),
        _tone(0.55, 262.0, 175.0, "saw", 0.5, 0.26, 0.01, 0.9),
    )


def menu_select() -> list[float]:
    return _mix(
        _tone(0.055, 1180.0, 1420.0, "square", 0.5, 0.24, 0.005, 0.4),
        _noise(0.03, 0.06, 0.002, 0.3, 0.7, seed=41),
    )


def menu_move() -> list[float]:
    return _tone(0.065, 780.0, 820.0, "square", 0.5, 0.18, 0.005, 0.35)


EFFECTS = {
    "type_correct.wav": type_correct,
    "type_wrong.wav": type_wrong,
    "destroy.wav": destroy,
    "combo.wav": combo,
    "boss.wav": boss,
    "wave_clear.wav": wave_clear,
    "game_over.wav": game_over,
    "menu_select.wav": menu_select,
    "menu_move.wav": menu_move,
}


def write_wav(path: str, samples: list[float]) -> None:
    frames = bytearray()
    for value in samples:
        clipped = max(-1.0, min(1.0, value))
        frames += struct.pack("<h", int(clipped * 32767))
    with wave.open(path, "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate CODETYPE sound effects")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing files instead of skipping them",
    )
    parser.add_argument("--out", default=SOUNDS_DIR, help="output directory")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    written = 0
    skipped = 0
    for filename, builder in EFFECTS.items():
        path = os.path.join(args.out, filename)
        if os.path.exists(path) and not args.force:
            print(f"  skip   {filename} (exists, use --force to replace)")
            skipped += 1
            continue
        samples = builder()
        write_wav(path, samples)
        print(f"  write  {filename}  {len(samples) / RATE:.2f}s")
        written += 1

    print(f"\n{written} written, {skipped} skipped -> {args.out}")
    print("Add music.ogg for background music (optional).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
