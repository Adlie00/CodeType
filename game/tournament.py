"""Tournament storage for one attempt per participant.

Each participant is identified by ``(team_number, player_number)``.
This keeps individual scores locally, with a CSV export for organizer records.
No team totals, brackets, or network coordination.
"""

from __future__ import annotations

import csv
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime

from game.constants import (
    TOURNAMENT_PLAYERS_PER_TEAM,
    TOURNAMENT_RESULTS_FILE,
    TOURNAMENT_TEAM_COUNT,
)

_SLOT_AVAILABLE = "available"
_SLOT_STARTED = "started"
_SLOT_COMPLETED = "completed"

_TEAM_LABEL = "Team {number}"
_PLAYER_LABEL = "Player {number}"


def team_label(number: int) -> str:
    return _TEAM_LABEL.format(number=int(number))


def player_label(number: int) -> str:
    return _PLAYER_LABEL.format(number=int(number))


@dataclass(frozen=True)
class TournamentEntry:
    """Carried from name entry through the game; matches the existing HUD shape."""

    player_name: str
    team_number: int
    player_number: int
    attempt_key: str
    target_name: str = ""
    target_score: int | None = None

    @property
    def team_name(self) -> str:
        return team_label(self.team_number)

    @property
    def slot(self) -> int:
        return self.player_number


@dataclass(frozen=True)
class TournamentResult:
    id: int
    attempt_key: str
    player_name: str
    team_number: int
    player_number: int
    score: int | None
    wpm: float
    accuracy: float
    max_combo: int
    waves: int
    enemies: int
    started_at: str
    completed_at: str

    @property
    def completed(self) -> bool:
        return self.score is not None

    @property
    def team_name(self) -> str:
        return team_label(self.team_number)

    @property
    def player_slot_label(self) -> str:
        return player_label(self.player_number)


@dataclass(frozen=True)
class SlotStatus:
    state: str
    result: TournamentResult | None = None

    @property
    def available(self) -> bool:
        return self.state == _SLOT_AVAILABLE


class TournamentStore:
    """Individual participant results with CSV export."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._create_table()

    # ── Schema ───────────────────────────────────────────────────────────────

    def _create_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tournament_results (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_key    TEXT    NOT NULL UNIQUE,
                player_name    TEXT    NOT NULL,
                team_number    INTEGER NOT NULL CHECK (team_number BETWEEN 1 AND 5),
                player_number  INTEGER NOT NULL CHECK (player_number BETWEEN 1 AND 5),
                score          INTEGER,
                wpm            REAL,
                accuracy       REAL,
                max_combo      INTEGER,
                waves          INTEGER,
                enemies        INTEGER,
                started_at     TEXT    NOT NULL,
                completed_at   TEXT,
                UNIQUE(team_number, player_number)
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS tournament_results_completed
            ON tournament_results(completed_at)
            """
        )
        self._conn.commit()

    # ── Registration / attempt control ───────────────────────────────────────

    def slot_status(self, team_number: int, player_number: int) -> SlotStatus:
        try:
            team = int(team_number)
            player = int(player_number)
        except (TypeError, ValueError):
            return SlotStatus(_SLOT_AVAILABLE)
        row = self._conn.execute(
            """
            SELECT id, attempt_key, player_name, team_number, player_number,
                   score, wpm, accuracy, max_combo, waves, enemies,
                   started_at, completed_at
            FROM tournament_results
            WHERE team_number = ? AND player_number = ?
            """,
            (team, player),
        ).fetchone()
        if row is None:
            return SlotStatus(_SLOT_AVAILABLE)
        result = self._row_to_result(row)
        return SlotStatus(
            _SLOT_COMPLETED if result.completed else _SLOT_STARTED,
            result,
        )

    def begin_attempt(
        self,
        player_name: str,
        team_number: int | None,
        player_number: int | None,
    ) -> dict:
        """Reserve a participant slot before gameplay starts.

        Once a slot is reserved, an interrupted run still consumes the official
        attempt.  The unique ``(team_number, player_number)`` index is the final
        guard against duplicate attempts.
        """
        name = str(player_name or "").strip()[:32]
        if not name:
            return {"accepted": False, "reason": "ENTER PLAYER NAME"}
        try:
            team = int(team_number)  # type: ignore[arg-type]
            player = int(player_number)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return {"accepted": False, "reason": "SELECT TEAM AND PLAYER NUMBER"}
        if not 1 <= team <= TOURNAMENT_TEAM_COUNT:
            return {"accepted": False, "reason": "SELECT TEAM 1-5"}
        if not 1 <= player <= TOURNAMENT_PLAYERS_PER_TEAM:
            return {"accepted": False, "reason": "SELECT PLAYER NUMBER 1-5"}

        status = self.slot_status(team, player)
        if status.state == _SLOT_COMPLETED:
            return {
                "accepted": False,
                "reason": f"{team_label(team).upper()} {player_label(player).upper()} ALREADY COMPLETED ON THIS PC",
            }
        if status.state == _SLOT_STARTED:
            return {
                "accepted": False,
                "reason": f"{team_label(team).upper()} {player_label(player).upper()} ATTEMPT ALREADY STARTED",
            }

        key = uuid.uuid4().hex
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO tournament_results
                        (attempt_key, player_name, team_number, player_number,
                         score, wpm, accuracy, max_combo, waves, enemies,
                         started_at, completed_at)
                    VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL)
                    """,
                    (key, name, team, player, now),
                )
        except sqlite3.IntegrityError:
            # A second writer won the race; report the slot as consumed.
            status = self.slot_status(team, player)
            reason = (
                "ATTEMPT ALREADY STARTED"
                if status.state == _SLOT_STARTED
                else "ALREADY COMPLETED ON THIS PC"
            )
            return {"accepted": False, "reason": reason}

        return {
            "accepted": True,
            "reason": "",
            "entry": TournamentEntry(
                player_name=name,
                team_number=team,
                player_number=player,
                attempt_key=key,
            ),
        }

    def complete_attempt(
        self,
        attempt_key: str,
        *,
        score: int,
        wpm: float,
        accuracy: float,
        max_combo: int,
        waves: int,
        enemies: int,
    ) -> TournamentResult | None:
        """Write the final numbers once; reopening the summary is idempotent."""
        key = str(attempt_key or "")
        if not key:
            return None
        existing = self.result_for_attempt(key)
        if existing is None:
            return None
        if existing.completed:
            return existing

        try:
            safe_score = max(0, int(score))
            safe_wpm = max(0.0, float(wpm))
            safe_accuracy = max(0.0, min(100.0, float(accuracy)))
            safe_combo = max(0, int(max_combo))
            safe_waves = max(0, int(waves))
            safe_enemies = max(0, int(enemies))
        except (TypeError, ValueError):
            return None

        with self._conn:
            cur = self._conn.execute(
                """
                UPDATE tournament_results
                SET score = ?, wpm = ?, accuracy = ?, max_combo = ?,
                    waves = ?, enemies = ?, completed_at = ?
                WHERE attempt_key = ? AND score IS NULL
                """,
                (
                    safe_score,
                    round(safe_wpm, 2),
                    round(safe_accuracy, 2),
                    safe_combo,
                    safe_waves,
                    safe_enemies,
                    datetime.now().isoformat(timespec="seconds"),
                    key,
                ),
            )
        if cur.rowcount != 1:
            # It was completed by another call between the read and the write.
            return self.result_for_attempt(key)
        return self.result_for_attempt(key)

    def result_for_attempt(self, attempt_key: str) -> TournamentResult | None:
        row = self._conn.execute(
            """
            SELECT id, attempt_key, player_name, team_number, player_number,
                   score, wpm, accuracy, max_combo, waves, enemies,
                   started_at, completed_at
            FROM tournament_results
            WHERE attempt_key = ?
            """,
            (str(attempt_key or ""),),
        ).fetchone()
        return None if row is None else self._row_to_result(row)

    def reset_slot(self, team_number: int, player_number: int) -> bool:
        """Organizer override for one participant slot."""
        try:
            team = int(team_number)
            player = int(player_number)
        except (TypeError, ValueError):
            return False
        with self._conn:
            cur = self._conn.execute(
                """
                DELETE FROM tournament_results
                WHERE team_number = ? AND player_number = ?
                """,
                (team, player),
            )
        return cur.rowcount > 0

    # ── CSV export ───────────────────────────────────────────────────────────

    def export_result(self, attempt_key: str, path: str | None = None) -> dict:
        """Append one completed result to CSV; idempotent."""
        result = self.result_for_attempt(attempt_key)
        if result is None or not result.completed:
            return {"ok": False, "message": "RESULT NOT AVAILABLE"}
        target = path or TOURNAMENT_RESULTS_FILE
        try:
            directory = os.path.dirname(os.path.abspath(target))
            if directory:
                os.makedirs(directory, exist_ok=True)
            existing = self._existing_attempt_keys(target)
            if result.attempt_key in existing:
                return {"ok": True, "message": "ALREADY IN CSV"}
            needs_header = not os.path.exists(target) or os.path.getsize(target) == 0
            with open(target, "a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if needs_header:
                    writer.writerow(
                        (
                            "Attempt ID",
                            "Date/Time",
                            "Player Name",
                            "Team Name",
                            "Player Number",
                            "WPM",
                            "Accuracy",
                            "Final Score",
                            "Waves",
                            "Enemies",
                            "Max Combo",
                        )
                    )
                writer.writerow(
                    (
                        result.attempt_key,
                        result.completed_at,
                        result.player_name,
                        result.team_name,
                        result.player_number,
                        f"{result.wpm:.1f}",
                        f"{result.accuracy:.1f}",
                        result.score,
                        result.waves,
                        result.enemies,
                        result.max_combo,
                    )
                )
        except (OSError, csv.Error, ValueError) as exc:
            return {"ok": False, "message": f"CSV EXPORT FAILED: {exc}"}
        return {"ok": True, "message": "RESULT APPENDED TO CSV"}

    @staticmethod
    def _existing_attempt_keys(path: str) -> set[str]:
        keys: set[str] = set()
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return keys
        try:
            with open(path, "r", newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                next(reader, None)
                for row in reader:
                    if row:
                        keys.add(str(row[0]))
        except (OSError, csv.Error, UnicodeError):
            return set()
        return keys

    # ── Row helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_result(row) -> TournamentResult:
        return TournamentResult(
            id=int(row[0]),
            attempt_key=str(row[1]),
            player_name=str(row[2]),
            team_number=int(row[3]),
            player_number=int(row[4]),
            score=None if row[5] is None else int(row[5]),
            wpm=float(row[6] or 0.0),
            accuracy=float(row[7] or 0.0),
            max_combo=int(row[8] or 0),
            waves=int(row[9] or 0),
            enemies=int(row[10] or 0),
            started_at=str(row[11] or ""),
            completed_at=str(row[12] or ""),
        )