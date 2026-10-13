from __future__ import annotations

import math
import random
from collections import OrderedDict

import pygame

from game.constants import (
    BOSS_STATION_FRACTION,
    BOSS_SWAY,
    BOSS_WIDTH_BONUS,
    DESIGN_HEIGHT,
    DESIGN_WIDTH,
    ENEMY_COLUMN_X,
    ENEMY_COLUMNS,
    ENEMY_FOOTER_HEIGHT,
    ENEMY_HEADER_HEIGHT,
    ENEMY_LINE_HEIGHT,
    ENEMY_MAX_HEIGHT,
    ENEMY_MIN_GAP,
    ENEMY_SWAY_FAST,
    ENEMY_SWAY_SPECIAL,
    ENEMY_WIDTH,
    FIELD_BOTTOM_MARGIN,
    HAIRLINE,
    HAIRLINE_DIM,
    HUD_HEIGHT,
    MAX_SCALE,
    MIN_SCALE,
    NEON_CYAN,
    PANEL_BG,
    SPAWN_CLEARANCE_MARGIN,
    SURFACE_RAISED,
    TEXT_BRIGHT,
    TEXT_DIM,
    WARNING_BAND_HEIGHT,
)


# ── Scaling ──────────────────────────────────────────────────────────────────


def scale_for(width: int, height: int) -> float:
    """Uniform scale factor from the design resolution to a display.

    ``min`` of the two axes rather than height alone: on a short, wide window
    (1024x600) the limiting axis is the width, and scaling by height would
    overflow the sides. Clamped so panels never collapse or balloon.
    """
    if width <= 0 or height <= 0:
        return 1.0
    raw = min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)
    return max(MIN_SCALE, min(MAX_SCALE, raw))


# ── Gameplay layout ──────────────────────────────────────────────────────────


class Layout:
    """Gameplay geometry resolved for one display size.

    Built from a surface size — the scale is then ``scale_for`` of that size —
    or given an explicit scale when the caller wants a fixed look. A degenerate
    size falls back to the design surface rather than to a zero-height field, so
    the authored design numbers survive and the headless engine tests can rely
    on them.
    """

    __slots__ = (
        "width",
        "height",
        "scale",
        "hud_height",
        "field_bottom_margin",
        "enemy_width",
        "enemy_max_height",
        "enemy_line_height",
        "enemy_header_height",
        "enemy_footer_height",
        "enemy_min_gap",
        "enemy_column_x",
        "enemy_sway_special",
        "enemy_sway_fast",
        "boss_sway",
        "boss_width_bonus",
        "warning_band_height",
        "spawn_clearance_y",
    )

    def __init__(self, width: int, height: int, scale: float | None = None) -> None:
        if width <= 0 or height <= 0:
            width, height = DESIGN_WIDTH, DESIGN_HEIGHT
        self.width = int(width)
        self.height = int(height)
        self.scale = scale_for(self.width, self.height) if scale is None else float(scale)
        s = self.scale

        self.hud_height = int(round(HUD_HEIGHT * s))
        self.field_bottom_margin = int(round(FIELD_BOTTOM_MARGIN * s))
        self.enemy_width = int(round(ENEMY_WIDTH * s))
        self.enemy_max_height = int(round(ENEMY_MAX_HEIGHT * s))
        self.enemy_line_height = max(8, int(round(ENEMY_LINE_HEIGHT * s)))
        self.enemy_header_height = max(10, int(round(ENEMY_HEADER_HEIGHT * s)))
        self.enemy_footer_height = max(6, int(round(ENEMY_FOOTER_HEIGHT * s)))
        self.enemy_min_gap = int(round(ENEMY_MIN_GAP * s))
        self.enemy_column_x = int(round(ENEMY_COLUMN_X * s))
        self.enemy_sway_special = ENEMY_SWAY_SPECIAL * s
        self.enemy_sway_fast = ENEMY_SWAY_FAST * s
        self.boss_sway = BOSS_SWAY * s
        self.boss_width_bonus = int(round(BOSS_WIDTH_BONUS * s))
        self.warning_band_height = int(round(WARNING_BAND_HEIGHT * s))
        self.spawn_clearance_y = self.hud_height + int(round(SPAWN_CLEARANCE_MARGIN * s))

    @classmethod
    def for_surface(cls, surface: pygame.Surface) -> "Layout":
        width, height = surface.get_size()
        return cls(width, height)

    # ── Derived positions ────────────────────────────────────────────────────

    @property
    def danger_line(self) -> float:
        return float(self.height - self.field_bottom_margin)

    @property
    def travel(self) -> float:
        """Display pixels an enemy falls before crossing the danger line."""
        return max(40.0, self.danger_line - self.spawn_clearance_y)

    def boss_station(self) -> float:
        top = self.hud_height + int(round(24 * self.scale))
        return top + BOSS_STATION_FRACTION * (self.danger_line - top)

    def column_band(self, card_width: int) -> tuple[float, float]:
        """Leftmost and rightmost x a card of ``card_width`` may sit at.

        The left bound is the authored column; the right bound is measured in
        from the edge so a card swinging sideways at full amplitude still lands
        inside the surface. When the window is too narrow for two lanes the band
        collapses onto the authored column rather than pushing a card off-screen.
        """
        left = float(self.enemy_column_x)
        right = float(self.width) - card_width - self.enemy_sway_special
        return (left, right) if right > left else (left, left)

    @staticmethod
    def lane_stations(count: int = ENEMY_COLUMNS) -> tuple[float, ...]:
        """The spawn lanes as 0..1 positions, left to right.

        A lane is a *fraction* of the band rather than a pixel, so a card keeps
        its relative place across a resize however wide the window is.
        """
        if count <= 1:
            return (0.0,)
        return tuple(index / (count - 1) for index in range(count))

    def column_x(self, card_width: int, station: float) -> float:
        """Left edge for a card whose lane is ``station`` (0..1) across the band."""
        left, right = self.column_band(card_width)
        return left + (right - left) * min(1.0, max(0.0, station))

    def speed(self, base: float) -> float:
        """Scale a pixels-per-second constant into display space.

        Speeds must scale alongside the distance an enemy actually travels, or a
        bigger window would look spacious while the enemy stays just as fast in
        absolute terms, quietly making the game easier. A 16:9 surface scales
        ``travel`` and ``scale`` together, but a 4:3 window has spare height
        that the surface hands to the field, so ``travel`` is the authority here
        rather than the raw scale.
        """
        return base * self.travel / _DESIGN_TRAVEL

    def px(self, value: float) -> int:
        """A design-space length in display pixels, rounded."""
        return int(round(value * self.scale))


# The design-space fall length: from the spawn clearance to the danger line at
# 1:1. Referenced only by ``Layout.speed`` to normalise travel.
_DESIGN_TRAVEL = (
    720.0 - FIELD_BOTTOM_MARGIN - (78.0 + 150.0)
)


# The unscaled design-space layout. Enemies built without an explicit display
# (the headless engine tests, mostly) fall back to this so their geometry is
# identical to the authored constants.
DESIGN_LAYOUT = Layout(DESIGN_WIDTH, DESIGN_HEIGHT, 1.0)


# ── UI ───────────────────────────────────────────────────────────────────────


class UI:
    """Scaled fonts, pixel rounding, and the shared drawing vocabulary.

    Wraps whatever ``AssetManager``-like object is handed in and only relies on
    its ``font(size, bold)`` method, so the lightweight test doubles work too.
    """

    def __init__(self, assets: object, width: int, height: int) -> None:
        self._assets = assets
        self.width = int(width)
        self.height = int(height)
        self.scale = scale_for(self.width, self.height)
        self._fonts: dict[tuple[int, bool], pygame.font.Font] = {}
        self._text: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._glow: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._overlays: dict[tuple[str, int, int], pygame.Surface] = {}

    # ── Sizing ───────────────────────────────────────────────────────────────

    def px(self, value: float) -> int:
        """Scale a design-space length to display pixels, rounded."""
        return int(round(value * self.scale))

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (max(6, int(round(size * self.scale))), bold)
        font = self._fonts.get(key)
        if font is None:
            font = self._assets.font(key[0], bold)  # type: ignore[attr-defined]
            self._fonts[key] = font
        return font

    def measure(self, message: str, size: int, bold: bool = False) -> tuple[int, int]:
        return self.font(size, bold).size(message)

    def centre(self) -> tuple[int, int]:
        return self.width // 2, self.height // 2

    def centre_panel(self, width: float, height: float) -> pygame.Rect:
        """A centred panel rect sized in *design space*, never overflowing.

        Clamped to the surface so a modal on a very small window shrinks rather
        than losing its edges off-screen.
        """
        w = min(self.width, max(80, self.px(width)))
        h = min(self.height, max(60, self.px(height)))
        return pygame.Rect((self.width - w) // 2, (self.height - h) // 2, w, h)

    # ── Screen scaffolding ───────────────────────────────────────────────────

    def frame(
        self,
        surface: pygame.Surface,
        *,
        scanlines: bool = True,
        vignette: bool = True,
    ) -> None:
        """Paint the shared background a screen sits on.

        Gradient wash plus the two cached full-screen overlays. The animated
        layers — stars, grid — are a :class:`Backdrop` and are drawn by the
        screen on top of this, before any chrome.
        """
        self.backdrop_fill(surface)
        if vignette:
            surface.blit(self.overlay("vignette"), (0, 0))
        if scanlines:
            surface.blit(self.overlay("scanlines"), (0, 0))

    def veil(self, surface: pygame.Surface, alpha: int = 190) -> None:
        """Dim the whole screen so a modal or pause state reads as modal."""
        dim = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        dim.fill((2, 2, 10, max(0, min(255, alpha))))
        surface.blit(dim, (0, 0))

    def heading(
        self,
        surface: pygame.Surface,
        message: str,
        centre_x: int,
        top: int,
        *,
        size: int = 46,
        colour: tuple[int, int, int] = TEXT_BRIGHT,
        glow: tuple[int, int, int] | None = NEON_CYAN,
        subtitle: str | None = None,
        rule: bool = True,
    ) -> pygame.Rect:
        """A screen title: glowing text, an underline rule and a caption.

        Returns the rect of the title text so callers can stack content under
        it without re-measuring.
        """
        rect = self.text(
            surface,
            message,
            size,
            colour,
            centre_x,
            top,
            bold=True,
            anchor="midtop",
            glow=glow,
        )
        if rule:
            half = rect.width // 2 + self.px(20)
            y = rect.bottom + self.px(8)
            self.divider(surface, centre_x - half, centre_x + half, y, HAIRLINE, 190)
            bright = self.px(28)
            self.divider(
                surface, centre_x - bright, centre_x + bright, y, glow or NEON_CYAN, 235
            )
        if subtitle:
            self.text(
                surface,
                subtitle,
                14,
                TEXT_DIM,
                centre_x,
                rect.bottom + self.px(16),
                anchor="midtop",
            )
        return rect

    def select_row(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        selected: bool,
        colour: tuple[int, int, int] = NEON_CYAN,
        intensity: float = 1.0,
    ) -> None:
        """The shared treatment for the highlighted row of a list.

        A translucent wash plus a bright left rail, both in the row's accent
        colour. ``intensity`` fades it in so a selection can ease rather than
        snap.
        """
        if not selected:
            return
        alpha = int(max(0.0, min(1.0, intensity)) * 46)
        if alpha <= 0:
            return
        wash = pygame.Surface(rect.size, pygame.SRCALPHA)
        wash.fill((*colour, alpha))
        surface.blit(wash, rect.topleft)
        rail = max(2, self.px(3))
        pygame.draw.rect(
            surface,
            colour,
            pygame.Rect(rect.x, rect.y, rail, rect.height),
            border_radius=rail // 2,
        )

    def tile(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        value: str,
        *,
        value_colour: tuple[int, int, int] = TEXT_BRIGHT,
        label_size: int = 12,
        value_size: int = 22,
        align: str = "left",
    ) -> pygame.Rect:
        """A small caption-over-value block, the atom of every stat display.

        ``align`` is ``"left"``, ``"center"`` or ``"right"`` and decides how the
        pair is placed inside ``rect`` without changing the block's own width.
        """
        if align == "center":
            label_x: int = rect.centerx
            label_anchor = "midtop"
            value_x = rect.centerx
            value_anchor = "midtop"
        elif align == "right":
            label_x = rect.right
            label_anchor = "topright"
            value_x = rect.right
            value_anchor = "topright"
        else:
            label_x = rect.left
            label_anchor = "topleft"
            value_x = rect.left
            value_anchor = "topleft"

        label_height = self.px(label_size) + self.px(3)
        self.text(
            surface, label.upper(), label_size, TEXT_DIM, label_x, rect.top,
            bold=True, anchor=label_anchor,
        )
        return self.text(
            surface, value, value_size, value_colour, value_x,
            rect.top + label_height, bold=True, anchor=value_anchor,
        )

    def progress_bar(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        fraction: float,
        *,
        fill: tuple[int, int, int] = NEON_CYAN,
        track: tuple[int, int, int] = HAIRLINE_DIM,
        radius: int = 2,
    ) -> None:
        """A filled progress track — wave progress, boss health, sparklines.

        ``fraction`` is clamped to [0, 1]. The track is drawn first so the
        fill always sits on top without a blitting order issue.
        """
        pygame.draw.rect(surface, track, rect, border_radius=radius)
        filled = rect.copy()
        filled.width = max(0, int(rect.width * max(0.0, min(1.0, fraction))))
        if filled.width > 0:
            pygame.draw.rect(surface, fill, filled, border_radius=radius)

    def wpm_sparkline(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        history: list[float],
        *,
        colour: tuple[int, int, int] = NEON_CYAN,
    ) -> None:
        """Mini polyline chart of WPM samples inside *rect*.

        Drawn on a transparent sub-surface so it never bleeds outside *rect*
        regardless of the point positions. At least two samples are needed;
        fewer than two is silently a no-op.
        """
        if len(history) < 2:
            return
        peak = max(history) or 1.0
        w, h = rect.width, rect.height
        sub = pygame.Surface((w, h), pygame.SRCALPHA)
        # Filled area below the line (dim fill).
        fill_pts = []
        line_pts = []
        for index, sample in enumerate(history):
            x = int(index / (len(history) - 1) * (w - 1))
            y = int((1.0 - sample / peak) * (h - 1))
            line_pts.append((x, y))
            fill_pts.append((x, y))
        fill_pts += [(line_pts[-1][0], h), (0, h)]
        dim = (*colour, 20)
        pygame.draw.polygon(sub, dim, fill_pts)
        pygame.draw.lines(sub, (*colour, 180), False, line_pts, 2)
        surface.blit(sub, rect.topleft)

    # ── Text ─────────────────────────────────────────────────────────────────

    def text(
        self,
        surface: pygame.Surface,
        message: str,
        size: int,
        colour: tuple[int, int, int],
        x: int,
        y: int,
        *,
        bold: bool = False,
        anchor: str = "topleft",
        glow: tuple[int, int, int] | None = None,
    ) -> pygame.Rect:
        """Draw cached text with optional bloom, and return its rect.

        ``anchor`` is the usual pygame set: ``topleft``, ``topright``,
        ``midtop``, ``midleft``, ``center``, ``midright``, ``bottomleft`` and
        friends. Coordinates are absolute display pixels.
        """
        sharp = self._render(message, size, bold, colour)
        rect = sharp.get_rect(**{anchor: (int(x), int(y))})
        if glow is not None:
            # The bloom is rendered at the sharp text's exact size, so it needs
            # no offset; pygame clips whatever overhangs the surface.
            # The bloom is premultiplied, so BLEND_RGBA_ADD adds nothing
            # outside the glyphs and no background box bleeds through.
            surface.blit(
                self._bloom(message, size, bold, glow),
                rect.topleft,
                special_flags=pygame.BLEND_RGBA_ADD,
            )
        surface.blit(sharp, rect)
        return rect

    def blit_run(
        self,
        surface: pygame.Surface,
        message: str,
        size: int,
        colour: tuple[int, int, int],
        x: int,
        y: int,
        *,
        bold: bool = False,
    ) -> int:
        """Blit one same-colour run of text and return the width it advanced.

        The inner-loop form of :meth:`text`, for callers that lay a line out as
        a sequence of coloured pieces — the code cards do this once per syntax
        token. It reuses the same surface cache but skips the rect and anchor
        arithmetic, which nothing here needs. An empty run advances nothing,
        so the caller can pass token slices without guarding them.
        """
        if not message:
            return 0
        sharp = self._render(message, size, bold, colour)
        surface.blit(sharp, (int(x), int(y)))
        return sharp.get_width()

    def wrap(self, message: str, size: int, max_width: int, bold: bool = False) -> list[str]:
        """Greedy word wrap against a pixel width, honouring explicit newlines."""
        font = self.font(size, bold)
        limit = max(1, int(max_width))
        lines: list[str] = []
        for paragraph in message.split("\n"):
            current = ""
            for word in paragraph.split():
                candidate = word if not current else f"{current} {word}"
                if font.size(candidate)[0] <= limit or not current:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
        return lines

    def _render(
        self,
        message: str,
        size: int,
        bold: bool,
        colour: tuple[int, int, int],
    ) -> pygame.Surface:
        key = (message, size, bold, colour)
        cached = self._text.get(key)
        if cached is not None:
            self._text.move_to_end(key)
            return cached
        surface = self.font(size, bold).render(message, True, colour)
        self._text[key] = surface
        while len(self._text) > 256:
            self._text.popitem(last=False)
        return surface

    def _bloom(
        self,
        message: str,
        size: int,
        bold: bool,
        colour: tuple[int, int, int],
    ) -> pygame.Surface:
        """Blurred glow halo for the text, returned as an SRCALPHA surface.

        By keeping per-pixel alpha, transparent regions stay transparent when
        the caller blits with BLEND_RGBA_ADD — so no solid coloured box appears
        behind the text on large titles.
        """
        key = (message, size, bold, colour)
        cached = self._glow.get(key)
        if cached is not None:
            self._glow.move_to_end(key)
            return cached

        # Render with antialias on a transparent background so the alpha
        # channel already matches the text shape exactly.
        font   = self.font(size, bold)
        sharp  = font.render(message, True, colour)
        w, h   = sharp.get_size()

        # Convert to SRCALPHA so smoothscale preserves the alpha channel.
        src = pygame.Surface((w, h), pygame.SRCALPHA)
        src.blit(sharp, (0, 0))

        # Down-scale then up-scale to produce a cheap Gaussian-like blur.
        factor = 5
        small  = pygame.transform.smoothscale(
            src, (max(1, w // factor), max(1, h // factor))
        )
        bloom  = pygame.transform.smoothscale(small, (w, h))

        # Premultiply, so the colour follows the alpha. A blurred glyph keeps
        # its full RGB where the blur has faded the alpha to nothing, and the
        # caller adds this with BLEND_RGBA_ADD, which adds RGB without looking
        # at alpha - left unpremultiplied that paints a solid rectangle of
        # colour behind every glowing title. Returns a new surface.
        bloom = bloom.premul_alpha()

        self._glow[key] = bloom
        while len(self._glow) > 128:
            self._glow.popitem(last=False)
        return bloom

    # ── Chrome ───────────────────────────────────────────────────────────────

    def panel(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        *,
        fill: tuple[int, int, int] = PANEL_BG,
        alpha: int = 236,
        border: tuple[int, int, int] | None = HAIRLINE,
        radius: int | None = None,
        border_width: int = 1,
        accent: tuple[int, int, int] | None = None,
        glow: float = 0.0,
    ) -> pygame.Rect:
        """Rounded translucent panel with optional border, glow and corner accent."""
        radius = self.px(10) if radius is None else radius
        radius = max(0, min(radius, min(rect.width, rect.height) // 2))

        if glow > 0.0 and border is not None:
            halo = rect.inflate(self.px(12), self.px(12))
            halo_surface = pygame.Surface(halo.size, pygame.SRCALPHA)
            halo_surface.fill((*border, int(min(90, 26 * glow))))
            surface.blit(
                halo_surface,
                halo.topleft,
                special_flags=pygame.BLEND_RGBA_ADD,
            )

        body = pygame.Surface(rect.size, pygame.SRCALPHA)
        body.fill((*fill, alpha))
        surface.blit(body, rect.topleft)
        if border is not None and border_width > 0:
            pygame.draw.rect(surface, border, rect, border_width, border_radius=radius)
        if accent is not None:
            self._corner_accent(surface, rect, accent, radius)
        return rect

    def _corner_accent(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        colour: tuple[int, int, int],
        radius: int,
    ) -> None:
        arm = max(6, min(self.px(16), rect.height // 3))
        inset = self.px(3)
        thickness = max(2, self.px(2))
        for corner_x, corner_y, dir_x, dir_y in (
            (rect.left + inset, rect.top + inset, 1, 1),
            (rect.right - inset, rect.top + inset, -1, 1),
            (rect.left + inset, rect.bottom - inset, 1, -1),
            (rect.right - inset, rect.bottom - inset, -1, -1),
        ):
            pygame.draw.line(
                surface,
                colour,
                (corner_x, corner_y + dir_y * radius // 2),
                (corner_x, corner_y + dir_y * arm),
                thickness,
            )
            pygame.draw.line(
                surface,
                colour,
                (corner_x + dir_x * radius // 2, corner_y + dir_y * arm),
                (corner_x + dir_x * arm, corner_y + dir_y * arm),
                thickness,
            )

    def divider(
        self,
        surface: pygame.Surface,
        x1: int,
        x2: int,
        y: int,
        colour: tuple[int, int, int] = HAIRLINE_DIM,
        alpha: int = 255,
    ) -> None:
        line = pygame.Surface((max(1, x2 - x1), 1), pygame.SRCALPHA)
        line.fill((*colour, alpha))
        surface.blit(line, (x1, y))

    def meter(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        ratio: float,
        colour: tuple[int, int, int],
        *,
        track: tuple[int, int, int] = HAIRLINE_DIM,
        radius: int | None = None,
    ) -> None:
        """A filled progress bar with a soft leading highlight."""
        ratio = max(0.0, min(1.0, ratio))
        radius = rect.height // 2 if radius is None else radius
        if radius > rect.height // 2:
            radius = rect.height // 2
        pygame.draw.rect(surface, track, rect, border_radius=radius)
        filled = int(rect.width * ratio)
        if filled > 0:
            fill_rect = pygame.Rect(rect.x, rect.y, max(1, filled), rect.height)
            pygame.draw.rect(surface, colour, fill_rect, border_radius=radius)
            head = pygame.Rect(
                max(rect.x, fill_rect.right - self.px(3)),
                rect.y,
                min(self.px(3), fill_rect.width),
                rect.height,
            )
            pygame.draw.rect(
                surface,
                tuple(min(255, channel + 60) for channel in colour),
                head,
                border_radius=1,
            )

    def chips(
        self,
        surface: pygame.Surface,
        hints: list[tuple[str, str]],
        y: int,
        *,
        colour: tuple[int, int, int] = TEXT_DIM,
        centre_x: int | None = None,
    ) -> int:
        """Render ``[("ESC", "BACK")]`` pairs as key-cap chips on one line.

        ``centre_x`` moves the run off centre so it can sit flush against a
        panel edge instead. Returns the total width drawn.
        """
        size = 13
        gap = self.px(9)
        pad = self.px(7)
        cap_font = self.font(size, True)
        act_font = self.font(size)

        measured: list[tuple[pygame.Surface, pygame.Surface, int]] = []
        total = 0
        for key, action in hints:
            key_surf = cap_font.render(key, True, NEON_CYAN)
            act_surf = act_font.render(action, True, colour)
            block = pad + key_surf.get_width() + pad + act_surf.get_width()
            measured.append((key_surf, act_surf, block))
            total += block + gap
        total = max(0, total - gap)

        if centre_x is None:
            x = (self.width - total) // 2
        elif centre_x < 0:
            x = self.width + centre_x - total
        else:
            x = centre_x - total // 2
        cap_h = cap_font.get_height()
        for key_surf, act_surf, block in measured:
            cap = pygame.Rect(x, y - cap_h // 2, key_surf.get_width() + pad * 2, cap_h + pad)
            cap_surface = pygame.Surface(cap.size, pygame.SRCALPHA)
            cap_surface.fill((*SURFACE_RAISED, 220))
            surface.blit(cap_surface, cap.topleft)
            pygame.draw.rect(surface, HAIRLINE, cap, 1, border_radius=4)
            surface.blit(key_surf, (cap.x + pad, cap.y + pad // 2))
            surface.blit(act_surf, (cap.right + pad, y - act_surf.get_height() // 2))
            x += block + gap
        return total

    def section_label(
        self,
        surface: pygame.Surface,
        message: str,
        x: int,
        y: int,
        *,
        colour: tuple[int, int, int] = TEXT_DIM,
    ) -> pygame.Rect:
        """A small tracked-out label, used to head panels and columns."""
        font = self.font(12, True)
        tracking = max(1, self.px(1))
        width = 0
        glyphs = []
        for character in message.upper():
            glyph = font.render(character, True, colour)
            glyphs.append(glyph)
            width += glyph.get_width() + tracking
        width = max(0, width - tracking)
        cursor = x
        top = y + font.get_height() // 2
        for glyph in glyphs:
            surface.blit(
                glyph,
                (cursor, top - glyph.get_height() // 2),
            )
            cursor += glyph.get_width() + tracking
        rule = max(0, self.width - x - 6)
        self.divider(surface, x, x + min(rule, 60), top, HAIRLINE_DIM)
        return pygame.Rect(x, top - 7, width, 14)

    # ── Full-screen overlays ─────────────────────────────────────────────────

    def overlay(self, kind: str) -> pygame.Surface:
        """Cached full-screen decorative layer (``scanlines`` or ``vignette``)."""
        key = (kind, self.width, self.height)
        cached = self._overlays.get(key)
        if cached is not None:
            return cached
        surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        if kind == "scanlines":
            step = max(2, self.px(3))
            for y in range(0, self.height, step):
                pygame.draw.line(surface, (0, 0, 0, 26), (0, y), (self.width, y))
        elif kind == "vignette":
            steps = 26
            for index in range(steps):
                fraction = index / steps
                alpha = int(3 + 46 * (fraction ** 2.2))
                inset_x = int(self.width * 0.5 * fraction * 0.55)
                inset_y = int(self.height * 0.5 * fraction * 0.55)
                if inset_x <= 0 or inset_y <= 0:
                    continue
                band = pygame.Rect(
                    inset_x, inset_y, self.width - inset_x * 2, self.height - inset_y * 2
                )
                pygame.draw.rect(surface, (0, 0, 10, alpha), band, max(1, self.px(2)))
        self._overlays[key] = surface
        return surface

    def backdrop_fill(self, surface: pygame.Surface) -> None:
        """Vertical gradient wash, the base every screen sits on.

        Each band is a filled rect, not a line. A line from ``(0, y0)`` to
        ``(width, y1)`` is slanted, so consecutive bands end up as parallel
        lines a step apart and everything between them is never painted: at
        1080p that left 96% of the surface showing whatever was drawn before.
        The wash reads as a deliberate gradient over a black window, so the hole
        is invisible on a fresh launch and glaring the moment a menu is drawn
        over a gameplay frame.
        """
        top = (12, 14, 38)
        bottom = (5, 5, 16)
        steps = max(2, self.px(24))
        for index in range(steps):
            fraction = index / (steps - 1)
            y0 = int(self.height * index / steps)
            y1 = max(y0 + 1, int(self.height * (index + 1) / steps))
            colour = tuple(
                int(top[channel] + (bottom[channel] - top[channel]) * fraction)
                for channel in range(3)
            )
            pygame.draw.rect(surface, colour, (0, y0, self.width, y1 - y0))


# ── Animated backdrop ────────────────────────────────────────────────────────


class Star:
    """One parallax star. Deeper layers drift slower and dimmer."""

    __slots__ = ("x", "y", "depth", "size", "brightness", "phase")

    def __init__(self, width: int, height: int, depth: float) -> None:
        self.depth = depth
        self.x = random.uniform(0, max(1, width))
        self.y = random.uniform(0, max(1, height))
        self.size = 1 if depth < 0.6 else 2
        self.brightness = int(60 + depth * 150)
        self.phase = random.uniform(0.0, math.tau)

    def update(self, dt: float, width: int, height: int, speed: float) -> None:
        self.y += speed * self.depth * max(0.0, dt)
        if self.y > height + 2:
            self.y = -2.0
            self.x = random.uniform(0, max(1, width))

    def draw(self, surface: pygame.Surface, tick: float) -> None:
        twinkle = 0.82 + 0.18 * math.sin(self.phase + tick * 1.7)
        level = int(self.brightness * twinkle)
        pygame.draw.circle(
            surface, (level, level, min(255, level + 20)), (int(self.x), int(self.y)), self.size
        )


class Backdrop:
    """Starfield plus receding grid, shared by the menu and the play field.

    The grid and the star spawn bounds depend only on the surface size, so the
    grid is rendered once into a cached surface and the stars are a handful of
    circle calls per frame.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        star_count: int = 150,
        horizon_fraction: float = 0.58,
        grid: bool = True,
        scroll: float = 26.0,
        colours: bool = True,
        horizon_rule: bool = True,
    ) -> None:
        self.scroll = scroll
        self.colours = colours
        self.star_count = star_count
        self.horizon_fraction = horizon_fraction
        self.horizon_rule = horizon_rule
        self._grid_surface: pygame.Surface | None = None
        self._grid_key: tuple | None = None
        self._stars: list[Star] = []
        self.width = 0
        self.height = 0
        self.resize(width, height)

    def resize(self, width: int, height: int) -> None:
        self.width = int(width)
        self.height = int(height)
        count = max(24, int(self.star_count * max(0.35, min(2.0, self.width / DESIGN_WIDTH))))
        self._stars = [
            Star(self.width, self.height, depth)
            for depth in (random.random() * 0.85 + 0.15 for _ in range(count))
        ]

    def update(self, dt: float) -> None:
        for star in self._stars:
            star.update(dt, self.width, self.height, self.scroll)

    def draw(self, surface: pygame.Surface, tick: float = 0.0) -> None:
        for star in self._stars:
            star.draw(surface, tick)
        grid = self._grid()
        if grid is not None:
            surface.blit(grid, (0, 0))

    def _grid(self) -> pygame.Surface | None:
        key = (self.width, self.height, self.horizon_fraction, self.horizon_rule)
        if self._grid_key == key:
            return self._grid_surface
        self._grid_key = key
        if not self.colours:
            self._grid_surface = None
            return None

        surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        horizon = int(self.height * self.horizon_fraction)
        vanish_x = self.width // 2
        cell = max(48, self.width // 16)

        rays = max(6, int(self.width / cell) + 4)
        for index in range(rays):
            fraction = index / (rays - 1)
            x_bottom = int(-self.width * 0.15 + fraction * self.width * 1.3)
            fade = 1.0 - abs(fraction - 0.5) * 1.2
            alpha = int(max(0.0, min(1.0, 0.35 + fade * 0.65)) * 120)
            pygame.draw.line(
                surface, (0, int(46 * alpha / 120), int(96 * alpha / 120)),
                (vanish_x, horizon), (x_bottom, self.height), 1,
            )

        rows = 12
        for row in range(rows):
            fraction = (row / rows) ** 2.1
            y = int(horizon + fraction * (self.height - horizon))
            alpha = int(18 + 70 * fraction)
            pygame.draw.line(surface, (0, int(alpha * 0.32), int(alpha * 0.78)),
                             (0, y), (self.width, y), 1)

        # A bright rule at the horizon anchors the perspective. It is optional
        # because it reads as a lone centred line when the grid sits behind a
        # panel, which some screens would rather do without.
        if self.horizon_rule:
            pygame.draw.line(
                surface, (0, 120, 170), (0, horizon), (self.width, horizon), 1
            )
        self._grid_surface = surface
        return surface


class Stage:
    """One screen's living background: wash, starfield, grid, scanlines.

    Owning a :class:`Backdrop` and re-syncing it to the ``UI`` size means a
    window resize is a single ``Stage.draw`` with no bookkeeping on the screen,
    and the expensive grid layer is only rebuilt when the size actually moves.
    """

    __slots__ = ("_ui", "_backdrop", "_key", "horizon_fraction", "horizon_rule", "scroll")

    def __init__(
        self,
        ui: UI,
        *,
        star_count: int = 150,
        horizon_fraction: float = 0.58,
        grid: bool = True,
        scroll: float = 26.0,
        horizon_rule: bool = True,
    ) -> None:
        self._ui = ui
        self.horizon_fraction = horizon_fraction
        self.horizon_rule = horizon_rule
        self.scroll = scroll
        self._key: tuple[int, int] | None = None
        self._backdrop = Backdrop(
            ui.width,
            ui.height,
            star_count=star_count,
            horizon_fraction=horizon_fraction,
            grid=grid,
            scroll=scroll,
            horizon_rule=horizon_rule,
        )

    def update(self, dt: float) -> None:
        self._sync()
        self._backdrop.update(dt)

    def draw(self, surface: pygame.Surface, tick: float = 0.0) -> None:
        self._sync()
        self._backdrop.draw(surface, tick)
        surface.blit(self._ui.overlay("vignette"), (0, 0))
        surface.blit(self._ui.overlay("scanlines"), (0, 0))

    def stale(self, surface: pygame.Surface) -> bool:
        """True when the surface no longer matches the UI this stage was built for.

        The window can change size under a screen that only built its ``UI`` once,
        so a screen asks this at the top of its draw and rebuilds when it says
        yes. Cheap enough to poll every frame: a tuple comparison.
        """
        return surface.get_size() != (self._ui.width, self._ui.height)

    def rebind(self, ui: UI) -> None:
        """Adopt a new ``UI``, e.g. one the owner rebuilt after a resize.

        Clearing the key forces ``_sync`` to resize the backdrop on the next
        draw, so the starfield and grid match the new surface immediately.
        """
        self._ui = ui
        self._key = None

    def _sync(self) -> None:
        key = (self._ui.width, self._ui.height)
        if key == self._key:
            return
        self._key = key
        self._backdrop.resize(*key)


def fade_in(alpha: float) -> int:
    """Map a 0..1 fade factor to an 8-bit alpha."""
    return max(0, min(255, int(alpha * 255)))


def pulse(tick: float, speed: float = 2.0) -> float:
    """Smooth 0..1 oscillator for driving glows and beats."""
    return 0.5 + 0.5 * math.sin(tick * speed)


def mix(first: tuple[int, int, int], second: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(  # type: ignore[return-value]
        int(first[channel] + (second[channel] - first[channel]) * amount)
        for channel in range(3)
    )