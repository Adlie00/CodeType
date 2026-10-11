"""Visual effects for CODETYPE: particles, explosions, shake, and popups.

Every system here is gated by the ``typing_effects`` and ``screen_shake``
settings, so both can be turned off from the settings screen.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import pygame

from game.constants import (
    NEON_CYAN,
    NEON_GREEN,
    NEON_YELLOW,
)


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    colour: tuple[int, int, int]
    size: float
    gravity: float = 30.0
    drag: float = 0.0

    @property
    def alive(self) -> bool:
        return self.life > 0.0

    def update(self, dt: float) -> None:
        self.life -= dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += self.gravity * dt
        if self.drag:
            decay = max(0.0, 1.0 - self.drag * dt)
            self.vx *= decay
            self.vy *= decay

    def draw(self, surface: pygame.Surface) -> None:
        ratio = max(0.0, min(1.0, self.life / self.max_life)) if self.max_life else 0.0
        radius = max(1, int(self.size * ratio))
        colour = tuple(int(channel * ratio) for channel in self.colour)
        pygame.draw.circle(surface, colour, (int(self.x), int(self.y)), radius)


@dataclass
class Popup:
    text: str
    x: float
    y: float
    life: float
    max_life: float
    colour: tuple[int, int, int]
    rise: float = 24.0

    @property
    def alive(self) -> bool:
        return self.life > 0.0

    def update(self, dt: float) -> None:
        self.life -= dt
        self.y -= self.rise * dt

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        ratio = max(0.0, min(1.0, self.life / self.max_life)) if self.max_life else 0.0
        colour = tuple(int(channel * ratio) for channel in self.colour)
        text = font.render(self.text, True, colour)
        surface.blit(text, text.get_rect(center=(int(self.x), int(self.y))))


class ScreenShake:
    """Intensity-scaled shake that decays to rest.

    The scene is drawn onto an oversized surface so the offset never exposes
    an uncovered edge.
    """

    def __init__(self, margin: int = 12, scale: float = 1.0) -> None:
        self._timer = 0.0
        self._duration = 0.0
        self._strength = 0.0
        # The margin is a distance, so it scales with the display; the shake
        # amplitudes handed to ``add`` are design-space and scaled on the way in.
        self._margin = max(1, int(round(margin * scale)))
        self._scale = max(0.0, scale)
        self._offset = (0, 0)

    @property
    def active(self) -> bool:
        return self._timer > 0.0

    @property
    def offset(self) -> tuple[int, int]:
        return self._offset

    @property
    def margin(self) -> int:
        return self._margin

    def add(self, strength: float, duration: float = 0.16) -> None:
        strength = max(0.0, strength) * self._scale
        duration = max(0.0, duration)
        if self._timer > 0.0 and self._duration > 0.0:
            # Re-triggering mid-shake keeps the stronger of the two amplitudes.
            remaining = self._timer / self._duration
            strength = max(strength, self._strength * remaining)
            duration = max(duration, self._duration * remaining)
        self._strength = strength
        self._duration = duration
        self._timer = duration

    def update(self, dt: float) -> None:
        if self._timer <= 0.0:
            self._offset = (0, 0)
            return
        self._timer = max(0.0, self._timer - max(0.0, dt))
        decay = self._timer / self._duration if self._duration > 0.0 else 0.0
        magnitude = self._strength * decay
        self._offset = (
            int(random.uniform(-magnitude, magnitude)),
            int(random.uniform(-magnitude, magnitude)),
        )

    def reset(self) -> None:
        self._timer = 0.0
        self._duration = 0.0
        self._strength = 0.0
        self._offset = (0, 0)


class ParticleSystem:
    def __init__(
        self,
        enabled: bool = True,
        limit: int = 900,
        scale: float = 1.0,
    ) -> None:
        self.enabled = enabled
        self._particles: list[Particle] = []
        self._limit = limit
        # Radii and velocities are in display pixels, so they scale with the
        # UI: the same explosion covers the same fraction of the screen on a
        # laptop and on a 4K panel.
        self._scale = max(0.0, scale)

    def __len__(self) -> int:
        return len(self._particles)

    def clear(self) -> None:
        self._particles.clear()

    def spawn(self, particle: Particle) -> None:
        if not self.enabled:
            return
        if len(self._particles) >= self._limit:
            self._particles.pop(0)
        self._particles.append(particle)

    def explosion(
        self,
        x: float,
        y: float,
        colours: tuple[tuple[int, int, int], ...] = (
            NEON_CYAN,
            NEON_GREEN,
            NEON_YELLOW,
        ),
        count: int = 18,
        speed: tuple[float, float] = (35.0, 120.0),
        size: tuple[float, float] = (1.5, 4.0),
    ) -> None:
        s = self._scale
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            magnitude = random.uniform(*speed) * s
            life = random.uniform(0.25, 0.65)
            self.spawn(
                Particle(
                    x=x,
                    y=y,
                    vx=math.cos(angle) * magnitude,
                    vy=math.sin(angle) * magnitude,
                    life=life,
                    max_life=life,
                    colour=random.choice(colours),
                    size=random.uniform(*size) * s,
                )
            )

    def shockwave(
        self,
        x: float,
        y: float,
        colour: tuple[int, int, int],
        count: int = 30,
    ) -> None:
        """An expanding ring, used for boss and combo milestones."""
        s = self._scale
        for index in range(count):
            angle = math.tau * index / count
            life = random.uniform(0.4, 0.8)
            self.spawn(
                Particle(
                    x=x,
                    y=y,
                    vx=math.cos(angle) * 180.0 * s,
                    vy=math.sin(angle) * 180.0 * s,
                    life=life,
                    max_life=life,
                    colour=colour,
                    size=random.uniform(2.0, 5.0) * s,
                    gravity=0.0,
                    drag=2.4,
                )
            )

    def trail(self, x: float, y: float, colour: tuple[int, int, int]) -> None:
        s = self._scale
        life = random.uniform(0.2, 0.45)
        self.spawn(
            Particle(
                x=x + random.uniform(-14.0, 14.0) * s,
                y=y,
                vx=random.uniform(-18.0, 18.0) * s,
                vy=random.uniform(30.0, 70.0) * s,
                life=life,
                max_life=life,
                colour=colour,
                size=random.uniform(1.0, 2.6) * s,
            )
        )

    def update(self, dt: float) -> None:
        if not self._particles:
            return
        for particle in self._particles:
            particle.update(dt)
        self._particles = [p for p in self._particles if p.alive]

    def draw(self, surface: pygame.Surface) -> None:
        for particle in self._particles:
            particle.draw(surface)


@dataclass
class PopupSystem:
    enabled: bool = True
    _popups: list[Popup] = field(default_factory=list)
    _scale: float = 1.0

    def __len__(self) -> int:
        return len(self._popups)

    def clear(self) -> None:
        self._popups.clear()

    def add(
        self,
        text: str,
        x: float,
        y: float,
        colour: tuple[int, int, int],
        life: float = 0.9,
        rise: float = 24.0,
    ) -> None:
        if not self.enabled:
            return
        self._popups.append(
            Popup(text, x, y, life, life, colour, rise * max(0.0, self._scale))
        )

    def update(self, dt: float) -> None:
        if not self._popups:
            return
        for popup in self._popups:
            popup.update(dt)
        self._popups = [p for p in self._popups if p.alive]

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        for popup in self._popups:
            popup.draw(surface, font)


class EffectsManager:
    """Bundles the effect systems so the game holds one object.

    ``scale`` is the display's UI scale. Every distance the effects travel or
    occupy is authored in design space and multiplied here, so a 4K run throws
    the same debris across the same fraction of the screen as a 720p one.
    """

    def __init__(
        self,
        typing_effects: bool = True,
        screen_shake: bool = True,
        scale: float = 1.0,
    ) -> None:
        self._scale = max(0.0, scale)
        self.particles = ParticleSystem(
            enabled=typing_effects, scale=self._scale
        )
        self.popups = PopupSystem(enabled=typing_effects, _scale=self._scale)
        self.shake = ScreenShake(scale=self._scale)
        self._shake_enabled = screen_shake

    @property
    def effects_enabled(self) -> bool:
        return self.particles.enabled

    def configure(
        self,
        typing_effects: bool | None = None,
        screen_shake: bool | None = None,
    ) -> None:
        if typing_effects is not None:
            self.particles.enabled = typing_effects
            self.popups.enabled = typing_effects
            if not typing_effects:
                self.particles.clear()
                self.popups.clear()
        if screen_shake is not None:
            self._shake_enabled = screen_shake
            if not screen_shake:
                self.shake.reset()

    def add_shake(self, strength: float, duration: float = 0.16) -> None:
        if self._shake_enabled:
            self.shake.add(strength, duration)

    def rescale(self, scale: float) -> None:
        """Re-target every effect at a new display scale, in flight or not.

        Live particles are re-sized and re-timed rather than cleared: a window
        resize should not silently delete the debris already on screen.
        """
        scale = max(0.0, scale)
        if abs(scale - self._scale) < 1e-6:
            return
        ratio = scale / self._scale if self._scale > 0 else 1.0
        self._scale = scale
        for particle in self.particles._particles:
            particle.size *= ratio
            particle.x *= ratio
            particle.y *= ratio
            particle.vx *= ratio
            particle.vy *= ratio
        self.particles._scale = scale
        self.popups._scale = scale
        self.shake = ScreenShake(scale=scale)

    def update(self, dt: float) -> None:
        self.particles.update(dt)
        self.popups.update(dt)
        self.shake.update(dt)

    def draw_world(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Particles and popups, drawn inside the play field."""
        self.particles.draw(surface)
        self.popups.draw(surface, font)

    def clear(self) -> None:
        self.particles.clear()
        self.popups.clear()
        self.shake.reset()
