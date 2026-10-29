"""Competition Mode hub: team setup, progress, Team to Beat and bracket."""

from __future__ import annotations

import uuid

import pygame

from game.audio_manager import SFX_MENU_MOVE, SFX_MENU_SELECT
from game.competition import (
    DEFAULT_TEAM_NAMES,
    REPS_PER_TEAM,
    TEAM_COUNT,
    AttemptContext,
    MatchView,
)
from game.constants import (
    HAIRLINE_DIM,
    NEON_CYAN,
    NEON_GREEN,
    NEON_ORANGE,
    NEON_PINK,
    NEON_RED,
    NEON_YELLOW,
    PANEL_BG,
    SURFACE_RAISED,
    TARGET_FPS,
    TEXT_BRIGHT,
    TEXT_DIM,
)
from game.display import toggle_fullscreen
from game.input_map import printable_character
from game.ui import UI, Stage, pulse


_BRACKET_COLOURS = {
    "winners": NEON_GREEN,
    "losers": NEON_ORANGE,
    "finals": NEON_YELLOW,
}


class CompetitionScreen:
    """Runs the tournament: name the teams, then play one slot at a time."""

    def __init__(self, screen, settings, assets, audio, leaderboard, difficulty=None):
        self._screen = screen
        self._settings = settings
        self._assets = assets
        self._audio = audio
        self._leaderboard = leaderboard
        self._difficulty = difficulty
        self._repo = getattr(leaderboard, "competition", None)
        self._snapshot = self._repo.snapshot() if self._repo is not None else None
        self._tick = 0.0

        # Setup state is only used while no tournament exists.
        self._setup = self._snapshot is None
        self._names = list(DEFAULT_TEAM_NAMES)
        self._field = 0

        # Hub selection.
        self._team_index = 0
        self._slot = 1
        self._confirm_new = False
        self._notice = ""
        self._notice_timer = 0.0

        if self._snapshot is not None:
            self._select_first_open_team()

        self._rebuild(screen)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _rebuild(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        self._ui = UI(self._assets, width, height)
        self._stage = Stage(self._ui, star_count=140, horizon_fraction=0.5, scroll=20.0)

    def set_surface(self, screen: pygame.Surface) -> None:
        self._screen = screen
        self._rebuild(screen)

    def _toggle_fullscreen(self) -> None:
        self.set_surface(toggle_fullscreen(self._settings))

    def _reload(self) -> None:
        if self._repo is not None:
            self._snapshot = self._repo.snapshot()
        if self._snapshot is None:
            self._setup = True
            return
        self._setup = False
        self._clamp_selection()

    # ── Selection helpers ─────────────────────────────────────────────────────

    def _select_first_open_team(self) -> None:
        if self._snapshot is None:
            return
        for index, team in enumerate(self._snapshot.teams):
            if not team.finalized:
                self._team_index = index
                self._slot = self._first_open_slot(team)
                return
        self._team_index = 0
        self._slot = 1

    @staticmethod
    def _first_open_slot(team) -> int:
        for rep in team.reps:
            if not rep.completed:
                return rep.slot
        return 1

    def _clamp_selection(self) -> None:
        if self._snapshot is None or not self._snapshot.teams:
            return
        self._team_index = max(0, min(self._team_index, len(self._snapshot.teams) - 1))
        team = self._snapshot.teams[self._team_index]
        self._slot = max(1, min(self._slot, REPS_PER_TEAM))
        if team.reps and all(rep.completed for rep in team.reps):
            self._slot = 1

    def _current_team(self):
        if self._snapshot is None or not self._snapshot.teams:
            return None
        return self._snapshot.teams[self._team_index]

    def _move_team(self, delta: int) -> None:
        if self._snapshot is None:
            return
        self._team_index = (self._team_index + delta) % len(self._snapshot.teams)
        team = self._current_team()
        if team is not None:
            self._slot = self._first_open_slot(team)
        self._audio.play(SFX_MENU_MOVE)

    def _move_slot(self, delta: int) -> None:
        team = self._current_team()
        if team is None:
            return
        for _ in range(REPS_PER_TEAM):
            self._slot = (self._slot - 1 + delta) % REPS_PER_TEAM + 1
            rep = next((item for item in team.reps if item.slot == self._slot), None)
            if rep is not None and not rep.completed:
                break
        self._audio.play(SFX_MENU_MOVE)

    def _set_notice(self, message: str) -> None:
        self._notice = message
        self._notice_timer = 2.4

    # ── Event loop ────────────────────────────────────────────────────────────

    def run(self, clock: pygame.time.Clock):
        while True:
            dt = clock.tick(TARGET_FPS) / 1000.0
            self._tick += dt
            self._notice_timer = max(0.0, self._notice_timer - dt)
            self._stage.update(dt)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue
                result = self._handle_key(event)
                if result is not None:
                    return result
            self._draw()
            pygame.display.flip()

    def _handle_key(self, event):
        if self._confirm_new:
            return self._handle_confirm_key(event.key)
        if self._setup:
            return self._handle_setup_key(event)
        return self._handle_hub_key(event)

    # ── Setup keys ────────────────────────────────────────────────────────────

    def _handle_setup_key(self, event):
        key = event.key
        if key == pygame.K_ESCAPE:
            return self._to_menu()
        if key in (pygame.K_UP, pygame.K_w):
            self._field = (self._field - 1) % TEAM_COUNT
            self._audio.play(SFX_MENU_MOVE)
            return None
        if key in (pygame.K_DOWN, pygame.K_s, pygame.K_TAB):
            self._field = (self._field + 1) % TEAM_COUNT
            self._audio.play(SFX_MENU_MOVE)
            return None
        if key in (pygame.K_RETURN, getattr(pygame, "K_KP_ENTER", -1)):
            self._audio.play(SFX_MENU_SELECT)
            if self._field < TEAM_COUNT - 1:
                self._field += 1
                return None
            return self._start_tournament()
        if key == pygame.K_BACKSPACE:
            self._names[self._field] = self._names[self._field][:-1]
            return None
        character = printable_character(event)
        if character is not None and len(self._names[self._field]) < 18:
            self._names[self._field] += character
        return None

    def _start_tournament(self):
        if self._repo is None:
            self._set_notice("COMPETITION STORAGE UNAVAILABLE")
            return None
        try:
            self._repo.start_tournament(self._names)
        except Exception:  # sqlite3.Error and friends: never crash the UI
            self._set_notice("COULD NOT START TOURNAMENT")
            return None
        self._setup = False
        self._confirm_new = False
        self._reload()
        self._select_first_open_team()
        return None

    # ── Hub keys ──────────────────────────────────────────────────────────────

    def _handle_hub_key(self, event):
        key = event.key
        if key == pygame.K_ESCAPE:
            return self._to_menu()
        if key in (pygame.K_UP, pygame.K_w):
            self._move_team(-1)
            return None
        if key in (pygame.K_DOWN, pygame.K_s):
            self._move_team(1)
            return None
        if key in (pygame.K_LEFT, pygame.K_a):
            self._move_slot(-1)
            return None
        if key in (pygame.K_RIGHT, pygame.K_d):
            self._move_slot(1)
            return None
        if key == pygame.K_n:
            self._audio.play(SFX_MENU_SELECT)
            self._confirm_new = True
            return None
        if key == pygame.K_l:
            from screens.leaderboard_screen import LeaderboardScreen

            self._audio.play(SFX_MENU_SELECT)
            return LeaderboardScreen(
                self._screen, self._settings, self._assets,
                self._audio, self._leaderboard,
            )
        if key == pygame.K_r:
            self._reload()
            self._set_notice("TOURNAMENT REFRESHED")
            return None
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            return self._play_selected()
        return None

    def _handle_confirm_key(self, key):
        if key == pygame.K_y:
            self._audio.play(SFX_MENU_SELECT)
            self._confirm_new = False
            if self._repo is not None:
                self._repo.reset_tournament()
            self._names = list(DEFAULT_TEAM_NAMES)
            self._field = 0
            self._setup = True
            self._snapshot = None
            return None
        if key in (pygame.K_n, pygame.K_ESCAPE):
            self._confirm_new = False
            self._audio.play(SFX_MENU_MOVE)
        return None

    def _play_selected(self):
        team = self._current_team()
        if team is None:
            return None
        rep = next((item for item in team.reps if item.slot == self._slot), None)
        if rep is None or rep.completed:
            self._set_notice("THAT REPRESENTATIVE IS ALREADY FINISHED")
            return None
        target_name = (
            self._snapshot.team_to_beat_name if self._snapshot is not None else ""
        )
        target_score = (
            self._snapshot.team_to_beat_score if self._snapshot is not None else None
        )
        context = AttemptContext(
            team_id=team.id,
            team_name=team.name,
            slot=rep.slot,
            attempt_key=uuid.uuid4().hex,
            target_name=target_name,
            target_score=target_score,
        )
        from screens.name_input_screen import NameInputScreen

        self._audio.play(SFX_MENU_SELECT)
        return NameInputScreen(
            self._screen, self._settings, self._assets, self._audio,
            self._leaderboard, "competition", difficulty=self._difficulty,
            competition=context,
        )

    def _to_menu(self):
        from screens.main_menu import MainMenuScreen

        return MainMenuScreen(
            self._screen, self._settings, self._assets,
            self._audio, self._leaderboard,
        )

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        if self._stage.stale(self._screen):
            self._rebuild(self._screen)
        ui = self._ui
        ui.backdrop_fill(self._screen)
        self._stage.draw(self._screen, self._tick)

        if self._setup:
            self._draw_setup()
        else:
            if self._snapshot is None:
                self._reload()
            self._draw_hub()

        if self._confirm_new:
            self._draw_confirm_new()

    def _draw_title(self, subtitle: str = "") -> int:
        ui = self._ui
        cx = ui.width // 2
        rect = ui.text(
            self._screen, "COMPETITION", 38, TEXT_BRIGHT, cx, ui.px(18),
            bold=True, anchor="midtop", glow=NEON_YELLOW,
        )
        y = rect.bottom + ui.px(4)
        ui.divider(
            self._screen, cx - ui.px(170), cx + ui.px(170), y,
            HAIRLINE_DIM, 220,
        )
        if subtitle:
            ui.text(
                self._screen, subtitle, 12, TEXT_DIM, cx, y + ui.px(7),
                anchor="midtop",
            )
        return y + (ui.px(24) if subtitle else ui.px(12))

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _draw_setup(self) -> None:
        ui = self._ui
        top = self._draw_title("NAME THE FIVE TEAMS  ·  DEFAULTS ARE FINE")
        width = min(ui.width - ui.px(80), ui.px(680))
        panel = pygame.Rect(
            (ui.width - width) // 2, top + ui.px(8), width,
            ui.height - top - ui.px(78),
        )
        ui.panel(
            self._screen, panel, fill=PANEL_BG, alpha=238,
            border=HAIRLINE_DIM, accent=NEON_YELLOW,
            glow=0.3 + 0.15 * pulse(self._tick, 1.6),
        )
        ui.section_label(
            self._screen, "TEAM ROSTER", panel.x + ui.px(22), panel.y + ui.px(14)
        )
        ui.text(
            self._screen, "Each team fields five representatives.", 12, TEXT_DIM,
            panel.right - ui.px(22), panel.y + ui.px(14), anchor="topright",
        )

        rows_top = panel.y + ui.px(44)
        available = panel.height - ui.px(44) - ui.px(48)
        row_h = max(ui.px(42), available // TEAM_COUNT)
        field_w = panel.width - ui.px(44)
        for index in range(TEAM_COUNT):
            row = pygame.Rect(
                panel.x + ui.px(22), rows_top + index * row_h,
                field_w, row_h - ui.px(8),
            )
            active = index == self._field
            fill = SURFACE_RAISED if active else PANEL_BG
            ui.panel(
                self._screen, row, fill=fill, alpha=236,
                border=NEON_YELLOW if active else HAIRLINE_DIM,
                glow=0.28 if active else 0.0,
            )
            ui.text(
                self._screen, f"TEAM {index + 1}", 11,
                NEON_YELLOW if active else TEXT_DIM,
                row.x + ui.px(12), row.centery, bold=True, anchor="midleft",
            )
            value = self._names[index] or DEFAULT_TEAM_NAMES[index]
            ui.text(
                self._screen, value, 20,
                TEXT_BRIGHT if self._names[index] else TEXT_DIM,
                row.x + ui.px(104), row.centery, bold=True, anchor="midleft",
            )
            if active:
                caret = "|" if (pygame.time.get_ticks() // 420) % 2 == 0 else " "
                ui.text(
                    self._screen, caret, 20, NEON_YELLOW,
                    row.right - ui.px(12), row.centery,
                    bold=True, anchor="midright",
                )

        ui.chips(
            self._screen,
            [
                ("↑ ↓", "TEAM"), ("TYPE", "EDIT"), ("ENTER", "NEXT / START"),
                ("ESC", "MENU"),
            ],
            panel.bottom - ui.px(24),
        )

    # ── Hub ───────────────────────────────────────────────────────────────────

    def _draw_hub(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        top = self._draw_title("5 TEAMS  ·  5 REPRESENTATIVES EACH  ·  DOUBLE ELIMINATION")
        margin = max(self._ui.px(24), self._ui.width // 24)
        banner_h = self._ui.px(68)
        banner = pygame.Rect(
            margin, top, self._ui.width - margin * 2, banner_h
        )
        self._draw_banner(banner)

        content_top = banner.bottom + self._ui.px(10)
        footer_h = self._ui.px(36)
        content_h = self._ui.height - content_top - footer_h
        gap = self._ui.px(12)
        left_w = int((self._ui.width - margin * 2 - gap) * 0.62)
        right_w = self._ui.width - margin * 2 - gap - left_w
        bracket = pygame.Rect(margin, content_top, left_w, content_h)
        teams = pygame.Rect(bracket.right + gap, content_top, right_w, content_h)
        self._draw_bracket(bracket)
        self._draw_teams(teams)

        if self._notice and self._notice_timer > 0:
            self._ui.text(
                self._screen, self._notice, 12, NEON_ORANGE,
                self._ui.width // 2, self._ui.height - footer_h + self._ui.px(2),
                bold=True, anchor="midtop",
            )
        self._draw_footer()

    def _draw_banner(self, rect: pygame.Rect) -> None:
        ui = self._ui
        snapshot = self._snapshot
        ui.panel(
            self._screen, rect, fill=PANEL_BG, alpha=242,
            border=NEON_YELLOW, glow=0.35 + 0.2 * pulse(self._tick, 2.0),
        )
        ui.section_label(
            self._screen, "TEAM TO BEAT", rect.x + ui.px(18), rect.y + ui.px(10),
            colour=NEON_YELLOW,
        )
        if snapshot is None or snapshot.team_to_beat_name == "":
            name = "AWAITING THE FIRST FINISHED TEAM"
            score = "—"
            colour = TEXT_DIM
        else:
            name = snapshot.team_to_beat_name
            score = (
                f"{snapshot.team_to_beat_score:,}"
                if snapshot.team_to_beat_score is not None
                else "—"
            )
            colour = TEXT_BRIGHT
        ui.text(
            self._screen, name[:28], 24, colour, rect.x + ui.px(18),
            rect.y + ui.px(28), bold=True, anchor="topleft",
        )
        score_rect = ui.text(
            self._screen, score, 30, NEON_YELLOW, rect.right - ui.px(18),
            rect.y + ui.px(22), bold=True, anchor="topright", glow=NEON_YELLOW,
        )
        notice = snapshot.notice if snapshot is not None else ""
        if snapshot is not None and snapshot.champion_name:
            notice = f"CHAMPION  {snapshot.champion_name}"
        if notice:
            notice_colour = (
                NEON_GREEN
                if snapshot is not None and snapshot.champion_name
                else NEON_ORANGE
            )
            ui.text(
                self._screen, notice[:56], 12, notice_colour,
                rect.right - ui.px(18), score_rect.bottom + ui.px(2),
                bold=True, anchor="topright",
            )
        if snapshot is not None:
            done = sum(team.completed for team in snapshot.teams)
            total = TEAM_COUNT * REPS_PER_TEAM
            ui.text(
                self._screen, f"ATTEMPTS  {done}/{total}", 11, TEXT_DIM,
                rect.x + ui.px(18), rect.bottom - ui.px(14),
                anchor="midleft",
            )

    def _draw_bracket(self, panel: pygame.Rect) -> None:
        ui = self._ui
        snapshot = self._snapshot
        if snapshot is None:
            return
        ui.panel(
            self._screen, panel, fill=PANEL_BG, alpha=232, border=HAIRLINE_DIM,
            glow=0.2,
        )
        ui.section_label(
            self._screen, "TOURNAMENT BRACKET", panel.x + ui.px(16),
            panel.y + ui.px(12),
        )
        ui.text(
            self._screen, "TWO LOSSES ELIMINATE  ·  MATCHES USE OFFICIAL TEAM TOTALS",
            10, TEXT_DIM, panel.right - ui.px(16), panel.y + ui.px(13),
            anchor="topright",
        )
        top = panel.y + ui.px(38)
        bottom = panel.bottom - ui.px(12)
        inner_x = panel.x + ui.px(14)
        inner_w = panel.width - ui.px(28)
        column_gap = ui.px(10)
        col_w = (inner_w - column_gap * 2) // 3
        columns = (
            ("WINNERS", "winners", inner_x),
            ("LOSERS", "losers", inner_x + col_w + column_gap),
            ("FINALS", "finals", inner_x + (col_w + column_gap) * 2),
        )
        for label, bracket, x in columns:
            colour = _BRACKET_COLOURS[bracket]
            ui.section_label(
                self._screen, label, x + ui.px(2), top, colour=colour
            )
            cards = [
                match for match in snapshot.matches if match.bracket == bracket
            ]
            card_top = top + ui.px(18)
            available = bottom - card_top
            card_h = ui.px(46)
            if cards:
                spacing = max(
                    ui.px(5),
                    min(ui.px(12), (available - card_h * len(cards)) // max(1, len(cards))),
                )
            else:
                spacing = ui.px(6)
            for index, match in enumerate(cards):
                rect = pygame.Rect(
                    x, card_top + index * (card_h + spacing), col_w, card_h
                )
                if rect.bottom > bottom:
                    break
                self._draw_match_card(rect, match, colour)

    def _draw_match_card(
        self, rect: pygame.Rect, match: MatchView, colour
    ) -> None:
        ui = self._ui
        if match.status == "not_needed":
            ui.panel(
                self._screen, rect, fill=PANEL_BG, alpha=170,
                border=HAIRLINE_DIM, glow=0.0,
            )
            ui.text(
                self._screen, f"{match.round_label}  ·  NOT NEEDED", 9,
                TEXT_DIM, rect.centerx, rect.centery, bold=True, anchor="center",
            )
            return
        done = match.status == "done"
        ui.panel(
            self._screen, rect, fill=SURFACE_RAISED, alpha=224,
            border=colour if done else HAIRLINE_DIM,
            glow=0.22 if done else 0.05,
        )
        ui.text(
            self._screen, f"{match.match_key}  {match.round_label}", 8,
            TEXT_DIM, rect.x + ui.px(5), rect.y + ui.px(3),
            bold=True, anchor="topleft",
        )
        rows = (
            (match.team_a_name, match.score_a, match.winner_id == match.team_a_id),
            (match.team_b_name, match.score_b, match.winner_id == match.team_b_id),
        )
        for index, (name, score, won) in enumerate(rows):
            y = rect.y + ui.px(16) + index * ui.px(14)
            label = name[:13] if name else "TBD"
            text_colour = TEXT_BRIGHT if (not done or won) else TEXT_DIM
            if name:
                ui.text(
                    self._screen, label, 10, text_colour,
                    rect.x + ui.px(5), y, bold=done and won, anchor="topleft",
                )
            else:
                ui.text(
                    self._screen, label, 10, TEXT_DIM,
                    rect.x + ui.px(5), y, anchor="topleft",
                )
            if done and score is not None:
                ui.text(
                    self._screen, f"{score:,}", 10,
                    NEON_YELLOW if won else TEXT_DIM,
                    rect.right - ui.px(5), y, bold=won, anchor="topright",
                )

    def _draw_teams(self, panel: pygame.Rect) -> None:
        ui = self._ui
        snapshot = self._snapshot
        if snapshot is None:
            return
        ui.panel(
            self._screen, panel, fill=PANEL_BG, alpha=232,
            border=HAIRLINE_DIM, glow=0.2,
        )
        ui.section_label(
            self._screen, "TEAM PROGRESS", panel.x + ui.px(14), panel.y + ui.px(12)
        )
        ui.text(
            self._screen, "← →  REPRESENTATIVE", 9, TEXT_DIM,
            panel.right - ui.px(14), panel.y + ui.px(13), anchor="topright",
        )
        top = panel.y + ui.px(36)
        bottom = panel.bottom - ui.px(34)
        row_gap = ui.px(4)
        row_h = max(ui.px(48), (bottom - top - row_gap * (TEAM_COUNT - 1)) // TEAM_COUNT)
        for index, team in enumerate(snapshot.teams):
            row = pygame.Rect(
                panel.x + ui.px(10), top + index * (row_h + row_gap),
                panel.width - ui.px(20), row_h,
            )
            selected = index == self._team_index
            accent = (
                NEON_GREEN if team.id == snapshot.champion_id
                else NEON_RED if team.eliminated
                else NEON_YELLOW if selected
                else HAIRLINE_DIM
            )
            if selected:
                ui.select_row(
                    self._screen, row, selected=True, colour=NEON_YELLOW,
                )
            ui.panel(
                self._screen, row, fill=PANEL_BG, alpha=150 if selected else 110,
                border=accent, glow=0.22 if selected else 0.0,
            )
            ui.text(
                self._screen, f"{team.seed}. {team.name[:18]}", 15,
                TEXT_BRIGHT if not team.eliminated else TEXT_DIM,
                row.x + ui.px(9), row.y + ui.px(6),
                bold=True, anchor="topleft",
            )
            status = (
                "CHAMPION" if team.id == snapshot.champion_id
                else "ELIMINATED" if team.eliminated
                else f"LOSSES {team.losses}"
            )
            ui.text(
                self._screen, status, 9, accent,
                row.right - ui.px(8), row.y + ui.px(7),
                bold=True, anchor="topright",
            )
            total = f"{team.total:,}" if team.finalized and team.total is not None else "TOTAL PENDING"
            ui.text(
                self._screen, total, 11,
                NEON_YELLOW if team.finalized else TEXT_DIM,
                row.x + ui.px(9), row.y + ui.px(24),
                bold=team.finalized, anchor="topleft",
            )
            ui.text(
                self._screen, f"{team.completed}/{REPS_PER_TEAM}", 11,
                NEON_GREEN if team.finalized else TEXT_BRIGHT,
                row.right - ui.px(8), row.y + ui.px(24),
                bold=True, anchor="topright",
            )
            self._draw_rep_chips(row, team, selected)
        ui.chips(
            self._screen,
            [("ENTER", "PLAY SLOT"), ("N", "NEW")],
            panel.bottom - ui.px(16),
        )

    def _draw_rep_chips(self, row: pygame.Rect, team, selected: bool) -> None:
        ui = self._ui
        chip_w = ui.px(14)
        chip_h = ui.px(9)
        gap = ui.px(4)
        total = chip_w * REPS_PER_TEAM + gap * (REPS_PER_TEAM - 1)
        x = row.x + ui.px(9)
        y = row.bottom - ui.px(15)
        for rep in team.reps:
            rect = pygame.Rect(x, y, chip_w, chip_h)
            filled = rep.completed
            colour = NEON_GREEN if filled else HAIRLINE_DIM
            pygame.draw.rect(self._screen, colour, rect, border_radius=ui.px(2))
            if selected and rep.slot == self._slot and not filled:
                pygame.draw.rect(
                    self._screen, NEON_YELLOW, rect.inflate(2, 2),
                    max(1, ui.px(1)), border_radius=ui.px(2),
                )
            x += chip_w + gap
        ui.text(
            self._screen, f"REP {self._slot}", 9,
            NEON_YELLOW if selected else TEXT_DIM,
            row.right - ui.px(8), row.bottom - ui.px(14),
            bold=selected, anchor="midright",
        )

    def _draw_footer(self) -> None:
        ui = self._ui
        ui.chips(
            self._screen,
            [
                ("↑ ↓", "TEAM"), ("← →", "SLOT"), ("ENTER", "PLAY"),
                ("L", "LEADERBOARD"), ("N", "NEW"), ("ESC", "MENU"),
            ],
            ui.height - ui.px(24),
        )

    def _draw_confirm_new(self) -> None:
        ui = self._ui
        ui.veil(self._screen, 208)
        box = ui.centre_panel(520, 220)
        ui.panel(
            self._screen, box, fill=PANEL_BG, alpha=250, border=NEON_RED,
            border_width=max(1, ui.px(2)),
            glow=0.5 + 0.5 * pulse(self._tick, 4.0),
        )
        ui.heading(
            self._screen, "START A NEW COMPETITION?", box.centerx,
            box.y + ui.px(30), size=24, colour=NEON_RED, glow=NEON_RED,
        )
        ui.text(
            self._screen, "Every team, score and bracket result will be cleared.",
            14, TEXT_BRIGHT, box.centerx, box.bottom - ui.px(74), anchor="midtop",
        )
        ui.chips(
            self._screen, [("Y", "CLEAR & RESTART"), ("N / ESC", "CANCEL")],
            box.bottom - ui.px(30),
        )
