"""
Leaderboard — SQLite-backed persistent high score table.
"""

import os
import sqlite3
from datetime import datetime
from game.constants import DB_FILE, DATABASE_DIR
from game.tournament import TournamentStore

# The board never holds more than this many scores; anything that falls
# outside the top 10 is dropped instead of stored.
TOP_LIMIT = 10


class Leaderboard:
    def __init__(self) -> None:
        os.makedirs(DATABASE_DIR, exist_ok=True)
        self._conn = sqlite3.connect(DB_FILE)
        self._create_table()
        # The tournament keeps individual official results separately.
        self.tournament = TournamentStore(self._conn)
        self._trim()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT    NOT NULL,
                score       INTEGER NOT NULL,
                wpm         REAL    NOT NULL,
                accuracy    REAL    NOT NULL,
                max_combo   INTEGER NOT NULL,
                waves       INTEGER NOT NULL,
                enemies     INTEGER NOT NULL,
                mode        TEXT    NOT NULL,
                played_at   TEXT    NOT NULL
            )
        """)
        self._conn.commit()

    def save_score(
        self,
        player_name: str,
        score: int,
        wpm: float,
        accuracy: float,
        max_combo: int,
        waves: int,
        enemies: int,
        mode: str,
    ) -> bool:
        """Store the run only if it makes the top 10.

        Returns True when the score is kept, False when it did not qualify
        (or was evicted by an equal score already on the board).
        """
        cur = self._conn.execute(
            """INSERT INTO scores
               (player_name, score, wpm, accuracy, max_combo, waves, enemies, mode, played_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                player_name[:32],
                score,
                round(wpm, 2),
                round(accuracy, 2),
                max_combo,
                waves,
                enemies,
                mode,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        row_id = cur.lastrowid
        self._trim()
        self._conn.commit()
        kept = self._conn.execute(
            "SELECT 1 FROM scores WHERE id = ?", (row_id,)
        ).fetchone()
        return kept is not None

    def _trim(self) -> None:
        """Keep only the TOP_LIMIT highest scores; ties keep the older run."""
        self._conn.execute(
            """DELETE FROM scores
               WHERE id NOT IN (
                   SELECT id FROM scores ORDER BY score DESC, id ASC LIMIT ?
               )""",
            (TOP_LIMIT,),
        )
        self._conn.commit()

    def get_top(
        self,
        limit: int = TOP_LIMIT,
        sort_by: str = "score",
        mode: str | None = None,
    ) -> list[dict]:
        """The highest-scoring rows, optionally restricted to one mode.

        ``mode=None`` returns the board-wide top; passing a mode narrows the
        query so competition can look up the number it has to beat without the
        campaign and endless rows getting in the way.
        """
        allowed = {"score", "wpm", "accuracy"}
        col = sort_by if sort_by in allowed else "score"
        if mode is None:
            cur = self._conn.execute(
                f"SELECT * FROM scores ORDER BY {col} DESC LIMIT ?", (limit,)
            )
        else:
            cur = self._conn.execute(
                f"SELECT * FROM scores WHERE mode = ? ORDER BY {col} DESC LIMIT ?",
                (mode, limit),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def reset(self) -> None:
        self._conn.execute("DELETE FROM scores")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()