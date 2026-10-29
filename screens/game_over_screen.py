"""Game-over summary screen for CODETYPE."""

from __future__ import annotations

import sqlite3

import pygame

from game.constants import (
    DIFFICULTY_EASY,
    HAIRLINE_DIM,
    MODE_ARCADE,
    MODE_COMPETITION,
    MODE_WARMUP,
    NEON_CYAN,
    NEON_GREEN,
    NEON_ORANGE,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.display import toggle_fullscreen
from game.ui import UI, Stage, pulse


# Order matters: the four numbers that define a run come first, the tallies
# after, so the eye lands on the score before the bookkeeping.
_PRIMARY = (
    ("SCORE", "score", "{:,.0f}"),
    ("AVG WPM", "wpm", "{:.1f}"),
    ("ACCURACY", "accuracy", "{:.1f}%"),
    ("MAX COMBO", "max_combo", "x{}"),
)
_SECONDARY = (
    ("BEST WPM", "best_wpm", "{:.1f}"),
    ("WAVES", "waves", "{}"),
    ("ENEMIES", "enemies", "{}"),
    ("BOSSES", "bosses", "{}"),
)

# Outcome of the attempt to write this run to the leaderboard.
_SAVE_SKIPPED   = "skipped"   # warmup: never recorded, by design
_SAVE_SAVED     = "saved"
_SAVE_REJECTED  = "rejected"  # score did not make the top 10
_SAVE_FAILED    = "failed"    # database unavailable / error


class GameOverScreen:
    def __init__(
        self,
        screen: pygame.Surface,
        settings,
        assets,
        audio,
        leaderboard,
        stats: dict[str, object],
        competition=None,
    ) -> None:
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._stats = stats
        self._competition = competition
        self._official = None
        self._official_error = ""
        self._tick = 0.0
        self._rebuild(screen)
        # Cache these so _draw_panel doesn't recompute every frame.
        self._victory = bool(stats.get("victory", False))
        self._save_status = self._save_score()
        if competition is not None:
            self._official = self._save_official()
        self._rank = self._fetch_rank()

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=160, horizon_fraction=0.55, scroll=22.0)

    def _save_score(self) -> str:
        if self._stats.get("mode") == MODE_WARMUP:
            # Warmup is a practice run and is never recorded anywhere.
            return _SAVE_SKIPPED
        if self._leaderboard is None:
            return _SAVE_FAILED
        try:
            accepted = self._leaderboard.save_score(
                player_name=str(self._stats.get("player_name", "PLAYER")),
                score=int(self._stats.get("score", 0)),
                wpm=float(self._stats.get("wpm", 0.0)),
                accuracy=float(self._stats.get("accuracy", 0.0)),
                max_combo=int(self._stats.get("max_combo", 0)),
                waves=int(self._stats.get("waves", 0)),
                enemies=int(self._stats.get("enemies", 0)),
                mode=str(self._stats.get("mode", "campaign")),
            )
            # False means the run did not qualify for the top 10; older
            # backends return None, which counts as saved.
            return _SAVE_REJECTED if accepted is False else _SAVE_SAVED
        except (OSError, sqlite3.Error, TypeError, ValueError):
            return _SAVE_FAILED

    def _save_official(self):
        """Record this run against its tournament slot, exactly once.

        The repository locks the slot and the attempt key, so re-opening the
        summary cannot double-count a representative's score.
        """
        if self._leaderboard is None or self._competition is None:
            return None
        repository = getattr(self._leaderboard, "competition", None)
        if repository is None:
            self._official_error = "COMPETITION STORAGE UNAVAILABLE"
            return None
        try:
            return repository.record_attempt(
                team_id=int(self._competition.team_id),
                slot=int(self._competition.slot),
                attempt_key=str(self._competition.attempt_key),
                player_name=str(self._stats.get("player_name", "PLAYER")),
                score=int(self._stats.get("score", 0)),
                wpm=float(self._stats.get("wpm", 0.0)),
                accuracy=float(self._stats.get("accuracy", 0.0)),
                max_combo=int(self._stats.get("max_combo", 0)),
                waves=int(self._stats.get("waves", 0)),
                enemies=int(self._stats.get("enemies", 0)),
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self._official_error = str(exc) or "OFFICIAL SCORE NOT SAVED"
            return None

    def _fetch_rank(self) -> int | None:
        """Return the leaderboard rank of this run's score, or None if unavailable."""
        if self._stats.get("mode") == MODE_WARMUP:
            return None
        if self._leaderboard is None:
            return None
        try:
            score = int(self._stats.get("score", 0))
            mode  = str(self._stats.get("mode", "campaign"))
            # get_rank(score, mode) should return 1-based rank or None.
            # Fall back gracefully if the method doesn't exist on older builds.
            if hasattr(self._leaderboard, "get_rank"):
                return self._leaderboard.get_rank(score, mode)
        except Exception:
            pass
        return None

    def set_surface(self, screen: pygame.Surface) -> None:
        """Adopt a new surface after a display-mode change."""
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        """F11: borderless fullscreen at the monitor's own resolution."""
        self.set_surface(toggle_fullscreen(self._settings))

    def run(self, clock: pygame.time.Clock):
        from screens.game_screen import GameScreen
        from screens.main_menu import MainMenuScreen
        from screens.name_input_screen import NameInputScreen

        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self._toggle_fullscreen()
                        continue
                    if event.key in (pygame.K_ESCAPE, pygame.K_m):
                        return MainMenuScreen(
                            self._screen,
                            self._settings,
                            self._assets,
                            self._audio,
                            self._leaderboard,
                        )
                    if event.key == pygame.K_r:
                        mode = str(self._stats.get("mode", "campaign"))
                        difficulty = str(
                            self._stats.get("start_difficulty", DIFFICULTY_EASY)
                        )
                        return GameScreen(
                            self._screen,
                            self._settings,
                            self._assets,
                            self._audio,
                            self._leaderboard,
                            mode,
                            str(self._stats.get("player_name", "PLAYER")),
                            difficulty,
                        )
            self._draw()
            pygame.display.flip()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            # The window was resized under us; rebuild for the new size.
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)
        self._draw_panel()
        self._draw_footer_hint()

    def _draw_panel(self) -> None:
        ui = self._ui
        # Use the cached flag set in __init__ so colour is consistent.
        accent = NEON_GREEN if self._victory else NEON_RED

        width = min(ui.width - ui.px(80), ui.px(680))
        top = max(ui.px(40), int(ui.height * 0.09))
        panel = pygame.Rect((ui.width - width) // 2, top, width, ui.height - top - ui.px(80))

        ui.panel(
            self._screen, panel,
            fill=PANEL_BG, alpha=232, border=HAIRLINE_DIM,
            accent=accent, glow=0.35 + 0.25 * pulse(self._tick, 1.8),
        )

        title = (
            "WARM-UP COMPLETE"
            if self._stats.get("mode") == MODE_WARMUP
            else "TIME UP"
            if self._stats.get("mode") == MODE_ARCADE
            else ("ALL WAVES CLEARED" if self._victory else "GAME OVER")
        )
        ui.text(
            self._screen, title, 40, accent, panel.centerx, panel.y + ui.px(26),
            bold=True, anchor="midtop", glow=accent,
        )
        subtitle = (
            f"{self._stats.get('player_name', 'PLAYER')}"
            f"   //   {str(self._stats.get('mode', '')).upper()}"
        )
        ui.text(
            self._screen, subtitle, 14, TEXT_DIM, panel.centerx, panel.y + ui.px(76),
            anchor="midtop",
        )

        # Rank badge: shown when we know the player's leaderboard position.
        badge_bottom = panel.y + ui.px(100)
        if self._rank is not None:
            rank_label = f"RANK  #{self._rank}  ·  SCORE SAVED"
            rank_col   = NEON_YELLOW if self._rank <= 3 else NEON_GREEN
            badge_rect = ui.text(
                self._screen, rank_label, 11, rank_col,
                panel.centerx, panel.y + ui.px(98),
                bold=True, anchor="midtop", glow=rank_col,
            )
            badge_bottom = badge_rect.bottom + ui.px(4)

        ui.divider(
            self._screen, panel.x + ui.px(28), panel.right - ui.px(28),
            badge_bottom + ui.px(4), HAIRLINE_DIM,
        )

        cursor = badge_bottom + ui.px(20)
        cursor = self._draw_tiles(panel, _PRIMARY, cursor, value_size=30, columns=2)
        cursor += ui.px(10)
        ui.section_label(
            self._screen, "RUN TOTALS", panel.x + ui.px(28), cursor + ui.px(10)
        )
        cursor += ui.px(28)
        cursor = self._draw_tiles(panel, _SECONDARY, cursor, value_size=20, columns=4)

        if self._competition is not None:
            self._draw_competition_block(panel, cursor)
        else:
            cursor = self._draw_sparkline(panel, cursor)

        self._draw_save_status(panel)

    def _draw_sparkline(self, panel: pygame.Rect, cursor: int) -> int:
        """WPM history graph, when the run recorded one and there is room."""
        ui = self._ui
        wpm_history = self._stats.get("wpm_history", [])
        if wpm_history and hasattr(ui, "wpm_sparkline"):
            cursor += ui.px(10)
            ui.section_label(
                self._screen, "WPM OVER TIME", panel.x + ui.px(28), cursor + ui.px(6)
            )
            cursor += ui.px(22)
            spark_rect = pygame.Rect(
                panel.x + ui.px(28), cursor,
                panel.width - ui.px(56), ui.px(36),
            )
            ui.wpm_sparkline(self._screen, spark_rect, wpm_history, colour=NEON_CYAN)
            cursor = spark_rect.bottom
        return cursor

    def _draw_competition_block(self, panel: pygame.Rect, top: int) -> int:
        """Team progress, Team to Beat and any match this attempt settled."""
        ui = self._ui
        context = self._competition
        official = self._official
        left = panel.x + ui.px(28)
        right = panel.right - ui.px(28)
        cursor = top + ui.px(12)
        ui.section_label(
            self._screen, "TOURNAMENT RESULT", left, cursor
        )
        cursor += ui.px(20)
        ui.text(
            self._screen,
            f"TEAM  {str(context.team_name)[:22]}   //   REP {context.slot}",
            15, TEXT_BRIGHT, left, cursor, bold=True, anchor="topleft",
        )
        cursor += ui.px(22)

        if official is not None and official.accepted:
            if official.team_finalized and official.team_total is not None:
                progress = (
                    f"TEAM TOTAL  {official.team_total:,}   ·   "
                    "ALL 5 REPRESENTATIVES FINISHED"
                )
                colour = NEON_GREEN
            else:
                progress = (
                    f"TEAM PROGRESS  {official.team_completed}/5   ·   "
                    "TOTAL UNLOCKS AT 5/5"
                )
                colour = NEON_CYAN
            ui.text(
                self._screen, progress, 13, colour, left, cursor,
                bold=True, anchor="topleft",
            )
            cursor += ui.px(19)
            ui.text(
                self._screen, "OFFICIAL SCORE RECORDED", 11, NEON_GREEN,
                left, cursor, bold=True, anchor="topleft",
            )
        elif official is not None:
            ui.text(
                self._screen, "ALREADY COUNTED — NO DOUBLE SCORING", 13,
                NEON_ORANGE, left, cursor, bold=True, anchor="topleft",
            )
        else:
            ui.text(
                self._screen,
                f"OFFICIAL SCORE NOT SAVED  {self._official_error}"[:70],
                12, NEON_RED, left, cursor, bold=True, anchor="topleft",
            )
        cursor += ui.px(20)

        if official is not None:
            leader_name = official.team_to_beat_name or "—"
            leader_score = official.team_to_beat_score
        else:
            leader_name = str(getattr(context, "target_name", "") or "—")
            leader_score = getattr(context, "target_score", None)
        leader_score_text = f"{leader_score:,}" if leader_score is not None else "—"
        ui.text(
            self._screen, f"TEAM TO BEAT  {leader_name[:20]}", 12, NEON_YELLOW,
            left, cursor, bold=True, anchor="topleft",
        )
        ui.text(
            self._screen, leader_score_text, 12, NEON_YELLOW,
            right, cursor, bold=True, anchor="topright",
        )
        cursor += ui.px(17)

        notice = official.notice if official is not None else ""
        if notice:
            ui.text(
                self._screen, notice[:58], 10, NEON_ORANGE,
                left, cursor, bold=True, anchor="topleft",
            )
            cursor += ui.px(15)

        if official is not None and official.resolved_matches:
            match = official.resolved_matches[-1]
            ui.text(
                self._screen,
                f"{match.round_label}: {match.winner_name} WINS"[:58],
                10, NEON_GREEN, left, cursor, bold=True, anchor="topleft",
            )
            cursor += ui.px(15)
        return cursor

    def _draw_tiles(
        self,
        panel: pygame.Rect,
        fields: tuple,
        top: int,
        *,
        value_size: int,
        columns: int,
    ) -> int:
        """A grid of caption-over-value blocks, filled left to right."""
        ui = self._ui
        pad = ui.px(28)
        inner = panel.width - pad * 2
        cell = inner // columns
        row_height = max(24, ui.px(18) + ui.px(value_size) + ui.px(14))
        accent_keys = {"score", "max_combo"}

        for index, (label, key, spec) in enumerate(fields):
            column = index % columns
            row = index // columns
            cell_rect = pygame.Rect(
                panel.x + pad + column * cell,
                top + row * row_height,
                cell,
                row_height,
            )
            try:
                value = spec.format(self._stats.get(key, 0))
            except (TypeError, ValueError):
                value = "0"
            # "waves" is sometimes a plain int and sometimes a formatted
            # string depending on the caller; normalise the combo prefix.
            if key == "max_combo":
                value = f"x{self._stats.get('max_combo', 0)}"
            colour = NEON_YELLOW if key in accent_keys else TEXT_BRIGHT
            self._ui.tile(
                self._screen, cell_rect, label, value,
                value_colour=colour, label_size=12, value_size=value_size,
            )
        rows = (len(fields) + columns - 1) // columns
        return top + rows * row_height

    def _draw_save_status(self, panel: pygame.Rect) -> None:
        ui = self._ui
        text, colour = {
            _SAVE_SAVED:    ("SCORE SAVED LOCALLY", NEON_GREEN),
            _SAVE_SKIPPED:  ("PRACTICE RUN — NOT SCORED", NEON_CYAN),
            _SAVE_REJECTED: ("NOT IN TOP 10 — SCORE NOT SAVED", NEON_ORANGE),
        }.get(self._save_status, ("SCORE SAVE UNAVAILABLE", NEON_RED))
        y = panel.bottom - ui.px(58)
        ui.divider(
            self._screen, panel.x + ui.px(28), panel.right - ui.px(28),
            y - ui.px(20), HAIRLINE_DIM,
        )
        ui.text(
            self._screen, text, 13, colour, panel.centerx, y, bold=True, anchor="midtop"
        )

    def _draw_footer_hint(self) -> None:
        ui = self._ui
        if self._competition is not None:
            replay = "COMPETITION HUB"
        elif str(self._stats.get("mode", "")) == MODE_COMPETITION:
            replay = "NEXT PLAYER"
        else:
            replay = "PLAY AGAIN"
        ui.chips(
            self._screen,
            [("R", replay), ("M / ESC", "MAIN MENU")],
            self._ui.height - ui.px(30),
        )