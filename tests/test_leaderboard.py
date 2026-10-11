"""Top-10 acceptance rules for the persistent leaderboard."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from game.leaderboard import TOP_LIMIT, Leaderboard


class LeaderboardTopTenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._db_path = os.path.join(self._tmp.name, "leaderboard.db")
        for target, value in (
            ("game.leaderboard.DB_FILE", self._db_path),
            ("game.leaderboard.DATABASE_DIR", self._tmp.name),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.board = Leaderboard()
        self.addCleanup(self.board.close)

    def _save(self, score: int) -> bool:
        return self.board.save_score(
            player_name="ACE",
            score=score,
            wpm=70.0,
            accuracy=98.0,
            max_combo=9,
            waves=3,
            enemies=30,
            mode="campaign",
        )

    def _count(self) -> int:
        return self.board._conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]

    def test_board_never_holds_more_than_top_limit(self) -> None:
        for index in range(TOP_LIMIT * 3):
            self._save(100 + index)
        self.assertEqual(self._count(), TOP_LIMIT)

    def test_score_below_the_cut_is_rejected(self) -> None:
        for index in range(TOP_LIMIT * 3):
            self.assertTrue(self._save(100 + index))
        lowest = min(
            row["score"] for row in self.board.get_top(TOP_LIMIT)
        )
        self.assertFalse(self._save(lowest - 1))
        self.assertEqual(self._count(), TOP_LIMIT)

    def test_score_that_makes_the_cut_is_accepted(self) -> None:
        for index in range(TOP_LIMIT * 3):
            self._save(100 + index)
        before = [row["score"] for row in self.board.get_top(TOP_LIMIT)]
        best, lowest = max(before), min(before)
        self.assertTrue(self._save(best + 1))
        self.assertEqual(self._count(), TOP_LIMIT)
        after = [row["score"] for row in self.board.get_top(TOP_LIMIT)]
        self.assertIn(best + 1, after)
        self.assertNotIn(lowest, after)

    def test_tie_at_the_cut_keeps_the_older_run(self) -> None:
        for _ in range(TOP_LIMIT):
            self._save(500)
        self.assertEqual(self._count(), TOP_LIMIT)
        self.assertFalse(self._save(500))
        self.assertEqual(self._count(), TOP_LIMIT)
        self.assertTrue(self._save(501))

    def test_startup_trims_a_legacy_overfull_database(self) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS scores (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   player_name TEXT NOT NULL, score INTEGER NOT NULL,
                   wpm REAL NOT NULL, accuracy REAL NOT NULL,
                   max_combo INTEGER NOT NULL, waves INTEGER NOT NULL,
                   enemies INTEGER NOT NULL, mode TEXT NOT NULL,
                   played_at TEXT NOT NULL)"""
        )
        for score in range(1, 26):
            conn.execute(
                """INSERT INTO scores
                   (player_name, score, wpm, accuracy, max_combo, waves,
                    enemies, mode, played_at)
                   VALUES ('OLD', ?, 50.0, 90.0, 1, 1, 1, 'campaign', 'x')""",
                (score,),
            )
        conn.commit()
        conn.close()

        board = Leaderboard()
        self.addCleanup(board.close)
        rows = board.get_top(TOP_LIMIT)
        self.assertEqual(len(rows), TOP_LIMIT)
        self.assertEqual(min(row["score"] for row in rows), 16)


if __name__ == "__main__":
    unittest.main()
