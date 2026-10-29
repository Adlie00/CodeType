"""Competition Mode: teams, official scores, Team to Beat and the bracket."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import pygame

from game.competition import (
    CompetitionRepository,
    REPS_PER_TEAM,
    TEAM_COUNT,
)
from game.leaderboard import Leaderboard


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self.addCleanup(self._conn.close)
        self.repo = CompetitionRepository(self._conn)

    def _finalize(self, team, total: int, attempt_prefix: str = "") -> None:
        for slot in range(1, REPS_PER_TEAM + 1):
            result = self.repo.record_attempt(
                team_id=team.id,
                slot=slot,
                attempt_key=f"{attempt_prefix}{team.id}-{slot}",
                player_name=f"P{team.id}{slot}",
                score=total // REPS_PER_TEAM,
                wpm=70.0 + slot,
                accuracy=97.0,
                max_combo=10,
                waves=3,
                enemies=9,
            )
            self.assertTrue(result.accepted, result.reason)

    def _start(self, names=None):
        return self.repo.start_tournament(names or ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO"])

    def test_team_total_waits_for_all_five_representatives(self) -> None:
        snapshot = self._start()
        team = snapshot.teams[0]
        for slot in range(1, REPS_PER_TEAM):
            result = self.repo.record_attempt(
                team_id=team.id, slot=slot, attempt_key=f"k{slot}",
                player_name=f"P{slot}", score=100, wpm=80.0, accuracy=99.0,
                max_combo=10, waves=2, enemies=5,
            )
            self.assertFalse(result.team_finalized)
            self.assertIsNone(result.team_total)
            self.assertEqual(result.team_completed, slot)

        final = self.repo.record_attempt(
            team_id=team.id, slot=5, attempt_key="k5", player_name="P5",
            score=250, wpm=80.0, accuracy=99.0, max_combo=10, waves=2, enemies=5,
        )
        self.assertTrue(final.accepted)
        self.assertTrue(final.team_finalized)
        self.assertEqual(final.team_completed, REPS_PER_TEAM)
        self.assertEqual(final.team_total, 100 * 4 + 250)

    def test_duplicate_attempt_never_counts_twice(self) -> None:
        snapshot = self._start()
        team = snapshot.teams[0]
        first = self.repo.record_attempt(
            team_id=team.id, slot=1, attempt_key="same", player_name="ACE",
            score=500, wpm=80.0, accuracy=98.0, max_combo=4, waves=2, enemies=3,
        )
        self.assertTrue(first.accepted)
        again = self.repo.record_attempt(
            team_id=team.id, slot=1, attempt_key="same", player_name="ACE",
            score=9999, wpm=80.0, accuracy=98.0, max_combo=4, waves=2, enemies=3,
        )
        self.assertFalse(again.accepted)
        self.assertTrue(again.duplicate)
        self.assertEqual(again.reason, "REPRESENTATIVE ALREADY COMPLETED")
        # A different key cannot replace a locked official slot either.
        other = self.repo.record_attempt(
            team_id=team.id, slot=1, attempt_key="different", player_name="ACE",
            score=9999, wpm=80.0, accuracy=98.0, max_combo=4, waves=2, enemies=3,
        )
        self.assertFalse(other.accepted)
        stored = self.repo.snapshot().team_by_id(team.id).reps[0]
        self.assertEqual(stored.score, 500)

    def test_team_to_beat_new_remaining_and_tie_notices(self) -> None:
        snapshot = self._start(["A", "B", "C", "D", "E"])
        self._finalize(snapshot.teams[0], 100, "a")
        self.assertIn("SETS THE TEAM TO BEAT", self.repo.snapshot().notice)

        self._finalize(snapshot.teams[1], 200, "b")
        self.assertEqual(self.repo.snapshot().notice, "NEW TEAM TO BEAT")
        self.assertEqual(self.repo.snapshot().team_to_beat_name, "B")

        self._finalize(snapshot.teams[2], 150, "c")
        current = self.repo.snapshot()
        self.assertEqual(current.team_to_beat_name, "B")
        self.assertIn("REMAINS TEAM TO BEAT", current.notice)

        self._finalize(snapshot.teams[3], 200, "d")
        current = self.repo.snapshot()
        self.assertEqual(current.team_to_beat_name, "B")
        self.assertEqual(current.team_to_beat_score, 200)
        self.assertIn("TIE", current.notice)

    def test_team_totals_rank_leaderboard_rows(self) -> None:
        snapshot = self._start(["A", "B", "C", "D", "E"])
        self._finalize(snapshot.teams[3], 900, "d")
        self._finalize(snapshot.teams[0], 500, "a")
        team_rows, rep_rows = self.repo.leaderboard_rows()
        self.assertEqual(len(team_rows), TEAM_COUNT)
        self.assertEqual(len(rep_rows), REPS_PER_TEAM * 2)
        self.assertEqual(team_rows[0]["team_name"], "D")
        self.assertTrue(team_rows[0]["finalized"])
        self.assertFalse(team_rows[2]["finalized"])
        self.assertIsNone(team_rows[2]["score"])
        self.assertEqual(rep_rows[0]["score"], 900 // REPS_PER_TEAM)

    def test_match_winner_uses_only_the_two_match_teams(self) -> None:
        snapshot = self._start(["A", "B", "C", "D", "E"])
        teams = self.repo._load_teams()
        low = dict(next(team for team in teams if team["name"] == "E"))
        high = dict(next(team for team in teams if team["name"] == "A"))
        low["total"], high["total"] = 100, 500
        other = dict(next(team for team in teams if team["name"] == "B"))
        other["total"] = 99999

        winner, loser = self.repo._decide_winner(low, high, teams + [other])
        self.assertEqual(winner, high["id"])
        self.assertEqual(loser, low["id"])

        # Equal totals fall back to accuracy, then WPM, then seed.
        tie_a = dict(low)
        tie_b = dict(high)
        tie_a["total"] = tie_b["total"] = 500
        for team, accuracy, wpm in ((tie_a, 99.0, 80.0), (tie_b, 98.0, 90.0)):
            self._conn.execute(
                "DELETE FROM competition_representatives WHERE team_id = ?",
                (team["id"],),
            )
            for slot in range(1, REPS_PER_TEAM + 1):
                self._conn.execute(
                    """INSERT INTO competition_representatives
                       (team_id, slot, name, score, wpm, accuracy, max_combo,
                        waves, enemies, attempt_key, completed_at)
                       VALUES (?, ?, '', 10, ?, ?, 1, 1, 1, NULL, NULL)""",
                    (team["id"], slot, wpm, accuracy),
                )
        winner, loser = self.repo._decide_winner(tie_a, tie_b, teams)
        self.assertEqual(winner, tie_a["id"])

    def test_five_team_bracket_crowns_champion_and_eliminates_on_two_losses(self) -> None:
        snapshot = self._start(["A", "B", "C", "D", "E"])
        totals = {1: 5000, 2: 4000, 3: 3000, 4: 2000, 5: 1000}
        for team in snapshot.teams:
            self._finalize(team, totals[team.seed], f"t{team.seed}-")

        final = self.repo.snapshot()
        self.assertEqual(final.champion_name, "A")
        self.assertTrue(final.complete)
        self.assertEqual(
            {team.name: team.losses for team in final.teams},
            {"A": 0, "B": 2, "C": 2, "D": 2, "E": 2},
        )
        self.assertEqual(
            {team.name for team in final.teams if team.eliminated},
            {"B", "C", "D", "E"},
        )
        matches = {match.match_key: match for match in final.matches}
        self.assertEqual(matches["M4"].winner_name, "A")
        self.assertEqual(matches["M7"].winner_name, "B")
        self.assertEqual(matches["M8"].winner_name, "A")
        self.assertEqual(matches["M9"].status, "not_needed")
        for match in final.matches:
            if match.status == "done":
                self.assertIn(match.winner_id, (match.team_a_id, match.team_b_id))
                self.assertGreaterEqual(max(match.score_a, match.score_b), 0)

    def test_matches_stay_ready_until_both_teams_finalize(self) -> None:
        snapshot = self._start()
        self._finalize(snapshot.teams[3], 4000, "d-")  # seed 4
        matches = {m.match_key: m for m in self.repo.snapshot().matches}
        self.assertEqual(matches["M1"].status, "ready")
        self.assertEqual(matches["M1"].team_a_name, "DELTA")
        self.assertEqual(matches["M1"].team_b_name, "ECHO")
        self._finalize(snapshot.teams[4], 1000, "e-")
        matches = {m.match_key: m for m in self.repo.snapshot().matches}
        self.assertEqual(matches["M1"].status, "done")
        self.assertEqual(matches["M1"].winner_name, "DELTA")
        self.assertTrue(
            any(team.name == "ECHO" and team.losses == 1
                for team in self.repo.snapshot().teams)
        )


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._db = os.path.join(self._tmp.name, "competition.db")
        for target, value in (
            ("game.leaderboard.DB_FILE", self._db),
            ("game.leaderboard.DATABASE_DIR", self._tmp.name),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_tournament_survives_reopening_the_existing_database(self) -> None:
        board = Leaderboard()
        snapshot = board.competition.start_tournament(
            ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO"]
        )
        for slot in range(1, REPS_PER_TEAM + 1):
            board.competition.record_attempt(
                team_id=snapshot.teams[0].id, slot=slot, attempt_key=f"p-{slot}",
                player_name="ACE", score=1000, wpm=80.0, accuracy=99.0,
                max_combo=10, waves=3, enemies=10,
            )
        board.close()

        reopened = Leaderboard()
        self.addCleanup(reopened.close)
        stored = reopened.competition.snapshot()
        self.assertIsNotNone(stored)
        self.assertEqual(stored.teams[0].name, "ALPHA")
        self.assertTrue(stored.teams[0].finalized)
        self.assertEqual(stored.teams[0].total, 5000)
        self.assertEqual(stored.team_to_beat_name, "ALPHA")

    def test_reset_clears_the_tournament_as_well_as_scores(self) -> None:
        board = Leaderboard()
        self.addCleanup(board.close)
        board.competition.start_tournament()
        board.save_score("ACE", 100, 80.0, 99.0, 10, 2, 3, "campaign")
        board.reset()
        self.assertIsNone(board.competition.snapshot())
        self.assertEqual(board.get_top(), [])


class ScreenTests(unittest.TestCase):
    class FakeAssets:
        def font(self, size, bold=False):
            return pygame.font.Font(None, max(8, size))

    class FakeAudio:
        def play(self, slot):
            pass

        def update_volumes(self):
            pass

    class FakeSettings:
        fullscreen = False
        typing_effects = True
        screen_shake = False

        def save(self):
            pass

    STATS = {
        "player_name": "ACE", "mode": "competition", "score": 1234,
        "wpm": 80.0, "accuracy": 98.0, "max_combo": 12, "waves": 3,
        "enemies": 8, "victory": False,
    }

    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        for target, value in (
            ("game.leaderboard.DB_FILE", os.path.join(self._tmp.name, "screens.db")),
            ("game.leaderboard.DATABASE_DIR", self._tmp.name),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.board = Leaderboard()
        self.addCleanup(self.board.close)
        self.screen = pygame.display.set_mode((1280, 720))
        self.assets = self.FakeAssets()
        self.audio = self.FakeAudio()
        self.settings = self.FakeSettings()

    def test_competition_setup_and_hub_draw(self) -> None:
        from screens.competition_screen import CompetitionScreen

        setup = CompetitionScreen(
            self.screen, self.settings, self.assets, self.audio, self.board
        )
        self.assertTrue(setup._setup)
        setup._draw()

        result = setup._start_tournament()
        self.assertIsNone(result)
        self.assertFalse(setup._setup)
        setup._draw()
        self.assertIsNotNone(setup._snapshot)
        self.assertEqual(len(setup._snapshot.teams), TEAM_COUNT)

        setup._move_team(1)
        setup._move_slot(1)
        setup._draw()

    def test_play_selected_returns_a_name_screen_with_context(self) -> None:
        from screens.competition_screen import CompetitionScreen
        from screens.name_input_screen import NameInputScreen

        self.board.competition.start_tournament(["A", "B", "C", "D", "E"])
        view = CompetitionScreen(
            self.screen, self.settings, self.assets, self.audio, self.board
        )
        target = view._play_selected()
        self.assertIsInstance(target, NameInputScreen)
        self.assertIsNotNone(target._competition)
        self.assertEqual(target._competition.team_id, view._snapshot.teams[0].id)
        self.assertEqual(target._competition.slot, 1)

    def test_game_over_records_the_official_score_once(self) -> None:
        from game.competition import AttemptContext
        from screens.game_over_screen import GameOverScreen

        snapshot = self.board.competition.start_tournament()
        team = snapshot.teams[0]
        context = AttemptContext(team.id, team.name, 1, "official-key")
        view = GameOverScreen(
            self.screen, self.settings, self.assets, self.audio, self.board,
            dict(self.STATS), competition=context,
        )
        self.assertIsNotNone(view._official)
        self.assertTrue(view._official.accepted)
        view._draw()

        again = GameOverScreen(
            self.screen, self.settings, self.assets, self.audio, self.board,
            dict(self.STATS), competition=context,
        )
        self.assertTrue(again._official.duplicate)
        stored = self.board.competition.snapshot().team_by_id(team.id)
        self.assertEqual(stored.completed, 1)
        self.assertEqual(stored.reps[0].score, self.STATS["score"])

    def test_leaderboard_competition_view_lists_teams_and_reps(self) -> None:
        from screens.leaderboard_screen import LeaderboardScreen

        snapshot = self.board.competition.start_tournament()
        for slot in range(1, REPS_PER_TEAM + 1):
            self.board.competition.record_attempt(
                team_id=snapshot.teams[0].id, slot=slot,
                attempt_key=f"l-{slot}", player_name=f"P{slot}",
                score=1000, wpm=80.0, accuracy=98.0, max_combo=10,
                waves=3, enemies=9,
            )
        view = LeaderboardScreen(
            self.screen, self.settings, self.assets, self.audio, self.board
        )
        view._select_filter(4)
        kinds = [row.get("kind") for row in view._rows]
        self.assertEqual(kinds.count("team"), TEAM_COUNT)
        self.assertEqual(kinds.count("representative"), REPS_PER_TEAM)
        view._draw()
        view._scroll_rows(3)
        view._draw()

    def test_competition_screen_draws_at_each_size(self) -> None:
        from screens.competition_screen import CompetitionScreen

        self.board.competition.start_tournament()
        for size in ((1280, 720), (1920, 1080), (960, 540)):
            screen = pygame.display.set_mode(size)
            view = CompetitionScreen(
                screen, self.settings, self.assets, self.audio, self.board
            )
            view._draw()
            self.assertEqual((view._ui.width, view._ui.height), size)
            pygame.display.flip()


if __name__ == "__main__":
    unittest.main()
