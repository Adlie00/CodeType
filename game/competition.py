"""Team competition and double-elimination bracket storage.

Competition Mode is a 5-team, 5-representative tournament.  Each
representative plays one official attempt; a team's total is the sum of its
five representative scores and is only finalised when all five have finished.
Bracket matches compare the two participating teams' official totals while the
Team to Beat banner is a separate ranking of every finalised team.

The repository shares the existing SQLite connection owned by
``game.leaderboard.Leaderboard``; it does not open a second database or require
a backend.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

TEAM_COUNT = 5
REPS_PER_TEAM = 5
DEFAULT_TEAM_NAMES = tuple(f"TEAM {index}" for index in range(1, TEAM_COUNT + 1))

NOTICE_NEW_LEADER = "NEW TEAM TO BEAT"
NOTICE_LEADER_REMAINS = "REMAINS TEAM TO BEAT"
NOTICE_TIE = "TIE"


@dataclass(frozen=True)
class RepresentativeView:
    id: int
    team_id: int
    slot: int
    name: str
    score: int | None
    wpm: float
    accuracy: float
    max_combo: int
    waves: int
    enemies: int
    completed_at: str

    @property
    def completed(self) -> bool:
        return self.score is not None


@dataclass
class TeamView:
    id: int
    name: str
    seed: int
    total: int | None
    completed: int
    finalized: bool
    losses: int
    eliminated: bool
    reps: list[RepresentativeView] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, REPS_PER_TEAM - self.completed)

    @property
    def average_wpm(self) -> float:
        scored = [rep for rep in self.reps if rep.completed]
        if not scored:
            return 0.0
        return sum(rep.wpm for rep in scored) / len(scored)

    @property
    def average_accuracy(self) -> float:
        scored = [rep for rep in self.reps if rep.completed]
        if not scored:
            return 0.0
        return sum(rep.accuracy for rep in scored) / len(scored)


@dataclass(frozen=True)
class MatchView:
    match_key: str
    bracket: str
    round_label: str
    position: int
    source_a: str
    source_b: str
    team_a_id: int | None
    team_b_id: int | None
    team_a_name: str
    team_b_name: str
    score_a: int | None
    score_b: int | None
    winner_id: int | None
    loser_id: int | None
    status: str
    is_reset: bool

    @property
    def complete(self) -> bool:
        return self.status == "done"

    @property
    def winner_name(self) -> str:
        if self.winner_id is None:
            return ""
        if self.winner_id == self.team_a_id:
            return self.team_a_name
        if self.winner_id == self.team_b_id:
            return self.team_b_name
        return ""

    @property
    def loser_name(self) -> str:
        if self.loser_id is None:
            return ""
        if self.loser_id == self.team_a_id:
            return self.team_a_name
        if self.loser_id == self.team_b_id:
            return self.team_b_name
        return ""


@dataclass(frozen=True)
class CompetitionSnapshot:
    tournament_id: int
    status: str
    created_at: str
    teams: tuple[TeamView, ...]
    matches: tuple[MatchView, ...]
    team_to_beat_id: int | None
    team_to_beat_name: str
    team_to_beat_score: int | None
    notice: str
    notice_team_id: int | None
    champion_id: int | None
    champion_name: str

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    @property
    def all_finalized(self) -> bool:
        return all(team.finalized for team in self.teams)

    def team_by_id(self, team_id: int | None) -> TeamView | None:
        if team_id is None:
            return None
        for team in self.teams:
            if team.id == team_id:
                return team
        return None

    @property
    def next_team(self) -> TeamView | None:
        """First seed that still has an unscored representative."""
        for team in self.teams:
            if not team.finalized:
                return team
        return self.teams[0] if self.teams else None


@dataclass(frozen=True)
class AttemptContext:
    """The tournament slot a live run belongs to.

    Carried from the competition hub through the name-entry and gameplay
    screens to the game-over screen, where the official score is recorded.
    """

    team_id: int
    team_name: str
    slot: int
    attempt_key: str
    target_name: str = ""
    target_score: int | None = None


@dataclass(frozen=True)
class AttemptResult:
    accepted: bool
    duplicate: bool
    reason: str
    team_id: int
    team_name: str
    slot: int
    team_completed: int
    team_total: int | None
    team_finalized: bool
    notice: str
    team_to_beat_id: int | None
    team_to_beat_name: str
    team_to_beat_score: int | None
    resolved_matches: tuple[MatchView, ...] = ()
    champion_id: int | None = None
    champion_name: str = ""


class CompetitionRepository:
    """CRUD and bracket rules for the current competition tournament."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._create_tables()

    # ── Schema ───────────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competition_tournament (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                created_at         TEXT NOT NULL,
                status             TEXT NOT NULL,
                team_to_beat_id    INTEGER,
                notice             TEXT NOT NULL DEFAULT '',
                notice_team_id     INTEGER,
                champion_id        INTEGER,
                updated_at         TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competition_teams (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id  INTEGER NOT NULL,
                name           TEXT NOT NULL,
                seed           INTEGER NOT NULL,
                losses         INTEGER NOT NULL DEFAULT 0,
                eliminated     INTEGER NOT NULL DEFAULT 0,
                total          INTEGER,
                completed      INTEGER NOT NULL DEFAULT 0,
                finalized      INTEGER NOT NULL DEFAULT 0,
                UNIQUE(tournament_id, seed)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competition_representatives (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id        INTEGER NOT NULL,
                slot           INTEGER NOT NULL,
                name           TEXT NOT NULL DEFAULT '',
                score          INTEGER,
                wpm            REAL,
                accuracy       REAL,
                max_combo      INTEGER,
                waves          INTEGER,
                enemies        INTEGER,
                attempt_key    TEXT UNIQUE,
                completed_at   TEXT,
                UNIQUE(team_id, slot)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competition_matches (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id  INTEGER NOT NULL,
                match_key      TEXT NOT NULL,
                bracket        TEXT NOT NULL,
                round_label    TEXT NOT NULL,
                position       INTEGER NOT NULL,
                source_a       TEXT NOT NULL,
                source_b       TEXT NOT NULL,
                team_a_id      INTEGER,
                team_b_id      INTEGER,
                score_a        INTEGER,
                score_b        INTEGER,
                winner_id      INTEGER,
                loser_id       INTEGER,
                status         TEXT NOT NULL DEFAULT 'pending',
                is_reset       INTEGER NOT NULL DEFAULT 0,
                UNIQUE(tournament_id, match_key)
            )
            """
        )
        self._conn.commit()

    # ── Public API ───────────────────────────────────────────────────────────

    def has_tournament(self) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM competition_tournament WHERE id = 1"
        ).fetchone()
        return row is not None

    def start_tournament(self, team_names: list[str] | tuple[str, ...] | None = None) -> CompetitionSnapshot:
        names = self._normalise_names(team_names)
        now = self._now()
        with self._conn:
            self._clear_tables()
            self._conn.execute(
                """
                INSERT INTO competition_tournament
                    (id, created_at, status, team_to_beat_id, notice,
                     notice_team_id, champion_id, updated_at)
                VALUES (1, ?, 'active', NULL, '', NULL, NULL, ?)
                """,
                (now, now),
            )
            team_ids: dict[int, int] = {}
            for seed, name in enumerate(names, start=1):
                cur = self._conn.execute(
                    """
                    INSERT INTO competition_teams
                        (tournament_id, name, seed, losses, eliminated,
                         total, completed, finalized)
                    VALUES (1, ?, ?, 0, 0, NULL, 0, 0)
                    """,
                    (name, seed),
                )
                team_id = int(cur.lastrowid)
                team_ids[seed] = team_id
                for slot in range(1, REPS_PER_TEAM + 1):
                    self._conn.execute(
                        """
                        INSERT INTO competition_representatives
                            (team_id, slot, name, score, wpm, accuracy,
                             max_combo, waves, enemies, attempt_key, completed_at)
                        VALUES (?, ?, '', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                        """,
                        (team_id, slot),
                    )
            self._insert_bracket(team_ids)
        snapshot = self.snapshot()
        if snapshot is None:  # pragma: no cover - defensive
            raise sqlite3.DatabaseError("competition tournament was not created")
        return snapshot

    def snapshot(self) -> CompetitionSnapshot | None:
        tournament = self._conn.execute(
            """
            SELECT id, created_at, status, team_to_beat_id, notice,
                   notice_team_id, champion_id
            FROM competition_tournament WHERE id = 1
            """
        ).fetchone()
        if tournament is None:
            return None
        (
            tournament_id,
            created_at,
            status,
            team_to_beat_id,
            notice,
            notice_team_id,
            champion_id,
        ) = tournament

        team_rows = self._conn.execute(
            """
            SELECT id, name, seed, total, completed, finalized, losses, eliminated
            FROM competition_teams
            WHERE tournament_id = ?
            ORDER BY seed
            """,
            (tournament_id,),
        ).fetchall()
        rep_rows = self._conn.execute(
            """
            SELECT r.id, r.team_id, r.slot, r.name, r.score, r.wpm, r.accuracy,
                   r.max_combo, r.waves, r.enemies, r.completed_at
            FROM competition_representatives r
            JOIN competition_teams t ON t.id = r.team_id
            WHERE t.tournament_id = ?
            ORDER BY t.seed, r.slot
            """,
            (tournament_id,),
        ).fetchall()

        reps_by_team: dict[int, list[RepresentativeView]] = {}
        for row in rep_rows:
            view = RepresentativeView(
                id=int(row[0]),
                team_id=int(row[1]),
                slot=int(row[2]),
                name=str(row[3] or ""),
                score=None if row[4] is None else int(row[4]),
                wpm=float(row[5] or 0.0),
                accuracy=float(row[6] or 0.0),
                max_combo=int(row[7] or 0),
                waves=int(row[8] or 0),
                enemies=int(row[9] or 0),
                completed_at=str(row[10] or ""),
            )
            reps_by_team.setdefault(view.team_id, []).append(view)

        teams: list[TeamView] = []
        team_by_id: dict[int, TeamView] = {}
        team_by_seed: dict[int, dict] = {}
        for row in team_rows:
            team = TeamView(
                id=int(row[0]),
                name=str(row[1]),
                seed=int(row[2]),
                total=None if row[3] is None else int(row[3]),
                completed=int(row[4]),
                finalized=bool(row[5]),
                losses=int(row[6]),
                eliminated=bool(row[7]),
                reps=reps_by_team.get(int(row[0]), []),
            )
            teams.append(team)
            team_by_id[team.id] = team
            # ``_source_team_id`` also serves ``_resolve_matches`` where the
            # lookup is a raw row dict, so keep the same shape here.
            team_by_seed[team.seed] = {"id": team.id}

        match_rows = self._conn.execute(
            """
            SELECT id, match_key, bracket, round_label, position, source_a,
                   source_b, team_a_id, team_b_id, score_a, score_b,
                   winner_id, loser_id, status, is_reset
            FROM competition_matches
            WHERE tournament_id = ?
            ORDER BY id
            """,
            (tournament_id,),
        ).fetchall()
        raw_matches = [self._raw_match(row) for row in match_rows]
        matches_by_key = {match["match_key"]: match for match in raw_matches}
        matches: list[MatchView] = []
        for match in raw_matches:
            team_a_id = match["team_a_id"]
            if team_a_id is None:
                team_a_id = self._source_team_id(
                    match["source_a"], matches_by_key, team_by_seed
                )
            team_b_id = match["team_b_id"]
            if team_b_id is None:
                team_b_id = self._source_team_id(
                    match["source_b"], matches_by_key, team_by_seed
                )
            team_a = team_by_id.get(team_a_id) if team_a_id is not None else None
            team_b = team_by_id.get(team_b_id) if team_b_id is not None else None
            matches.append(
                MatchView(
                    match_key=match["match_key"],
                    bracket=match["bracket"],
                    round_label=match["round_label"],
                    position=match["position"],
                    source_a=match["source_a"],
                    source_b=match["source_b"],
                    team_a_id=team_a_id,
                    team_b_id=team_b_id,
                    team_a_name=team_a.name if team_a else "",
                    team_b_name=team_b.name if team_b else "",
                    score_a=match["score_a"],
                    score_b=match["score_b"],
                    winner_id=match["winner_id"],
                    loser_id=match["loser_id"],
                    status=match["status"],
                    is_reset=bool(match["is_reset"]),
                )
            )

        leader = team_by_id.get(team_to_beat_id) if team_to_beat_id is not None else None
        if leader is None or not leader.finalized:
            leader = self._highest_finalized(teams)
        champion = team_by_id.get(champion_id) if champion_id is not None else None

        return CompetitionSnapshot(
            tournament_id=int(tournament_id),
            status=str(status),
            created_at=str(created_at),
            teams=tuple(teams),
            matches=tuple(matches),
            team_to_beat_id=leader.id if leader else None,
            team_to_beat_name=leader.name if leader else "",
            team_to_beat_score=leader.total if leader else None,
            notice=str(notice or ""),
            notice_team_id=None if notice_team_id is None else int(notice_team_id),
            champion_id=champion.id if champion else None,
            champion_name=champion.name if champion else "",
        )

    def record_attempt(
        self,
        team_id: int,
        slot: int,
        attempt_key: str,
        player_name: str,
        score: int,
        wpm: float,
        accuracy: float,
        max_combo: int,
        waves: int,
        enemies: int,
    ) -> AttemptResult:
        """Store one official representative attempt exactly once.

        The representative row is the source of truth: once it has a score it
        is locked.  The unique ``attempt_key`` also makes retrying the same
        game-over save idempotent.
        """
        with self._conn:
            rep = self._conn.execute(
                """
                SELECT r.id, r.score, t.name, t.completed, t.finalized, t.total
                FROM competition_representatives r
                JOIN competition_teams t ON t.id = r.team_id
                WHERE r.team_id = ? AND r.slot = ?
                """,
                (team_id, slot),
            ).fetchone()
            if rep is None:
                snapshot = self.snapshot()
                return self._result_from_snapshot(
                    snapshot, team_id, slot, accepted=False, duplicate=True,
                    reason="UNKNOWN REPRESENTATIVE SLOT",
                )
            rep_id, existing_score, team_name, completed, finalized, total = rep
            if existing_score is not None:
                snapshot = self.snapshot()
                return self._result_from_snapshot(
                    snapshot, team_id, slot, accepted=False, duplicate=True,
                    reason="REPRESENTATIVE ALREADY COMPLETED",
                )
            used = self._conn.execute(
                "SELECT 1 FROM competition_representatives WHERE attempt_key = ?",
                (attempt_key,),
            ).fetchone()
            if used is not None:
                snapshot = self.snapshot()
                return self._result_from_snapshot(
                    snapshot, team_id, slot, accepted=False, duplicate=True,
                    reason="ATTEMPT ALREADY RECORDED",
                )

            now = self._now()
            cur = self._conn.execute(
                """
                UPDATE competition_representatives
                SET name = ?, score = ?, wpm = ?, accuracy = ?, max_combo = ?,
                    waves = ?, enemies = ?, attempt_key = ?, completed_at = ?
                WHERE id = ? AND score IS NULL
                """,
                (
                    (player_name or "PLAYER")[:32],
                    int(score),
                    round(float(wpm), 2),
                    round(float(accuracy), 2),
                    int(max_combo),
                    int(waves),
                    int(enemies),
                    str(attempt_key),
                    now,
                    int(rep_id),
                ),
            )
            if cur.rowcount != 1:
                snapshot = self.snapshot()
                return self._result_from_snapshot(
                    snapshot, team_id, slot, accepted=False, duplicate=True,
                    reason="ATTEMPT ALREADY RECORDED",
                )

            self._refresh_team(team_id)
            resolved = self._resolve_matches()
            snapshot = self.snapshot()
            if snapshot is None:  # pragma: no cover - defensive
                raise sqlite3.DatabaseError("competition tournament disappeared")
            team = snapshot.team_by_id(team_id)
            return AttemptResult(
                accepted=True,
                duplicate=False,
                reason="",
                team_id=team_id,
                team_name=team.name if team else str(team_name),
                slot=int(slot),
                team_completed=team.completed if team else int(completed),
                team_total=team.total if team else None,
                team_finalized=bool(team.finalized) if team else bool(finalized),
                notice=snapshot.notice,
                team_to_beat_id=snapshot.team_to_beat_id,
                team_to_beat_name=snapshot.team_to_beat_name,
                team_to_beat_score=snapshot.team_to_beat_score,
                resolved_matches=tuple(resolved),
                champion_id=snapshot.champion_id,
                champion_name=snapshot.champion_name,
            )

    def leaderboard_rows(self) -> tuple[list[dict], list[dict]]:
        """Team-total rows and individual representative rows for the board."""
        snapshot = self.snapshot()
        if snapshot is None:
            return [], []
        team_rows: list[dict] = []
        for team in snapshot.teams:
            team_rows.append(
                {
                    "kind": "team",
                    "team_id": team.id,
                    "team_name": team.name,
                    "seed": team.seed,
                    "player_name": team.name,
                    "score": team.total,
                    "wpm": round(team.average_wpm, 1),
                    "accuracy": round(team.average_accuracy, 1),
                    "max_combo": 0,
                    "waves": 0,
                    "enemies": 0,
                    "mode": "competition",
                    "completed": team.completed,
                    "finalized": team.finalized,
                    "losses": team.losses,
                    "eliminated": team.eliminated,
                    "is_champion": team.id == snapshot.champion_id,
                }
            )
        team_rows.sort(
            key=lambda row: (
                0 if row["finalized"] else 1,
                -(row["score"] or 0),
                row["seed"],
            )
        )

        rep_rows: list[dict] = []
        for team in snapshot.teams:
            for rep in team.reps:
                if not rep.completed:
                    continue
                rep_rows.append(
                    {
                        "kind": "representative",
                        "team_id": team.id,
                        "team_name": team.name,
                        "seed": team.seed,
                        "slot": rep.slot,
                        "player_name": rep.name or f"REP {rep.slot}",
                        "score": rep.score,
                        "wpm": rep.wpm,
                        "accuracy": rep.accuracy,
                        "max_combo": rep.max_combo,
                        "waves": rep.waves,
                        "enemies": rep.enemies,
                        "mode": "competition",
                        "completed": True,
                        "finalized": team.finalized,
                    }
                )
        rep_rows.sort(
            key=lambda row: (-(row["score"] or 0), row["seed"], row["slot"])
        )
        return team_rows, rep_rows

    def reset_tournament(self) -> None:
        with self._conn:
            self._clear_tables()

    # ── Internal: tournament creation ───────────────────────────────────────

    def _insert_bracket(self, team_ids: dict[int, int]) -> None:
        # M1 is the only winners-bracket play-in with five teams.  Seeds 1-3
        # receive byes; the losers bracket below is the standard eight-slot
        # shape with empty byes collapsed out.
        graph = (
            ("M1", "winners", "WB PLAY-IN", 0, f"team:{team_ids[4]}", f"team:{team_ids[5]}", 0),
            ("M2", "winners", "WB SEMIFINAL", 0, f"team:{team_ids[1]}", "winner:M1", 0),
            ("M3", "winners", "WB SEMIFINAL", 1, f"team:{team_ids[2]}", f"team:{team_ids[3]}", 0),
            ("M4", "winners", "WB FINAL", 0, "winner:M2", "winner:M3", 0),
            ("M5", "losers", "LB ROUND 1", 0, "loser:M2", "loser:M1", 0),
            ("M6", "losers", "LB SEMIFINAL", 0, "winner:M5", "loser:M3", 0),
            ("M7", "losers", "LB FINAL", 0, "winner:M6", "loser:M4", 0),
            ("M8", "finals", "GRAND FINAL", 0, "winner:M4", "winner:M7", 0),
            ("M9", "finals", "RESET FINAL", 0, "winner:M8", "loser:M8", 1),
        )
        for key, bracket, label, position, source_a, source_b, is_reset in graph:
            self._conn.execute(
                """
                INSERT INTO competition_matches
                    (tournament_id, match_key, bracket, round_label, position,
                     source_a, source_b, team_a_id, team_b_id, score_a,
                     score_b, winner_id, loser_id, status, is_reset)
                VALUES (1, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL,
                        NULL, NULL, 'pending', ?)
                """,
                (key, bracket, label, position, source_a, source_b, is_reset),
            )

    def _clear_tables(self) -> None:
        self._conn.execute("DELETE FROM competition_matches")
        self._conn.execute("DELETE FROM competition_representatives")
        self._conn.execute("DELETE FROM competition_teams")
        self._conn.execute("DELETE FROM competition_tournament")

    @staticmethod
    def _normalise_names(
        names: list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        supplied = list(names or [])
        raw = [
            str(supplied[index]).strip() if index < len(supplied) else ""
            for index in range(TEAM_COUNT)
        ]
        result: list[str] = []
        seen: set[str] = set()
        for index, value in enumerate(raw):
            base = (value or DEFAULT_TEAM_NAMES[index])[:18]
            candidate = base
            suffix = 2
            while candidate.upper() in seen:
                tail = f" {suffix}"
                candidate = f"{base[:18 - len(tail)]}{tail}"
                suffix += 1
            seen.add(candidate.upper())
            result.append(candidate)
        return result

    # ── Internal: finalisation and bracket ──────────────────────────────────

    def _refresh_team(self, team_id: int) -> None:
        rows = self._conn.execute(
            """
            SELECT score FROM competition_representatives
            WHERE team_id = ? ORDER BY slot
            """,
            (team_id,),
        ).fetchall()
        scores = [None if row[0] is None else int(row[0]) for row in rows]
        completed = sum(1 for value in scores if value is not None)
        total = sum(value for value in scores if value is not None) if completed else None
        finalized = completed >= REPS_PER_TEAM and len(scores) >= REPS_PER_TEAM
        self._conn.execute(
            """
            UPDATE competition_teams
            SET completed = ?, total = ?, finalized = ?
            WHERE id = ?
            """,
            (completed, total if finalized else None, 1 if finalized else 0, team_id),
        )
        if finalized:
            self._update_team_to_beat(team_id, int(total or 0))

    def _update_team_to_beat(self, team_id: int, total: int) -> None:
        row = self._conn.execute(
            """
            SELECT t.team_to_beat_id, t.notice, l.name, l.total
            FROM competition_tournament t
            LEFT JOIN competition_teams l ON l.id = t.team_to_beat_id
            WHERE t.id = 1
            """
        ).fetchone()
        if row is None:  # pragma: no cover - start_tournament creates it
            return
        leader_id, _old_notice, leader_name, leader_total = row
        team_name = self._conn.execute(
            "SELECT name FROM competition_teams WHERE id = ?", (team_id,)
        ).fetchone()
        name = str(team_name[0]) if team_name else "TEAM"
        if leader_id is None or leader_total is None:
            new_leader_id = team_id
            notice = f"{name} SETS THE TEAM TO BEAT"
        elif total > int(leader_total):
            new_leader_id = team_id
            notice = NOTICE_NEW_LEADER
        elif total < int(leader_total):
            new_leader_id = int(leader_id)
            notice = f"{leader_name} {NOTICE_LEADER_REMAINS}"
        else:
            # The existing leader keeps the banner; the notice records the tie.
            new_leader_id = int(leader_id)
            notice = f"{NOTICE_TIE} — {name} MATCHES {leader_name}"
        self._conn.execute(
            """
            UPDATE competition_tournament
            SET team_to_beat_id = ?, notice = ?, notice_team_id = ?, updated_at = ?
            WHERE id = 1
            """,
            (new_leader_id, notice, team_id, self._now()),
        )

    def _resolve_matches(self) -> list[MatchView]:
        """Resolve every match whose two teams are known and finalised."""
        tournament = self._conn.execute(
            "SELECT champion_id FROM competition_tournament WHERE id = 1"
        ).fetchone()
        already_champion = tournament[0] if tournament else None
        before = self._match_status_map()
        resolved_keys: list[str] = []
        for _ in range(32):
            raw_matches = self._load_raw_matches()
            if not raw_matches:
                break
            matches_by_key = {match["match_key"]: match for match in raw_matches}
            teams = self._load_teams()
            team_by_seed = {team["seed"]: team for team in teams}
            progressed = False
            for match in raw_matches:
                if match["status"] in ("done", "not_needed"):
                    continue
                if match["is_reset"]:
                    grand = matches_by_key.get("M8")
                    losers_final = matches_by_key.get("M7")
                    if grand is None or grand["status"] != "done":
                        continue
                    if (
                        losers_final is None
                        or grand["winner_id"] != losers_final["winner_id"]
                    ):
                        self._set_match_status(match["id"], "not_needed")
                        match["status"] = "not_needed"
                        progressed = True
                        continue

                team_a_id = self._source_team_id(
                    match["source_a"], matches_by_key, team_by_seed
                )
                team_b_id = self._source_team_id(
                    match["source_b"], matches_by_key, team_by_seed
                )
                status = match["status"]
                if team_a_id is None or team_b_id is None:
                    status = "pending"
                else:
                    team_a = self._team_by_id(teams, team_a_id)
                    team_b = self._team_by_id(teams, team_b_id)
                    if team_a is None or team_b is None:
                        status = "pending"
                    elif not team_a["finalized"] or not team_b["finalized"]:
                        status = "ready"
                    else:
                        winner_id, loser_id = self._decide_winner(team_a, team_b, teams)
                        self._write_match_result(
                            match, team_a_id, team_b_id, winner_id, loser_id
                        )
                        self._apply_loss(loser_id)
                        resolved_keys.append(match["match_key"])
                        match["team_a_id"] = team_a_id
                        match["team_b_id"] = team_b_id
                        match["winner_id"] = winner_id
                        match["loser_id"] = loser_id
                        match["status"] = "done"
                        progressed = True
                        continue
                self._write_match_progress(
                    match["id"], team_a_id, team_b_id, status
                )
                match["team_a_id"] = team_a_id
                match["team_b_id"] = team_b_id
                match["status"] = status
                if status != before.get(match["match_key"], "pending"):
                    progressed = True
            if not progressed:
                break

        self._finish_championship()
        after = self._match_status_map()
        if not resolved_keys:
            return []
        snapshot = self.snapshot()
        if snapshot is None:
            return []
        return [
            match
            for match in snapshot.matches
            if match.status == "done" and before.get(match.match_key) != "done"
        ]

    def _finish_championship(self) -> None:
        raw_matches = self._load_raw_matches()
        matches = {match["match_key"]: match for match in raw_matches}
        grand = matches.get("M8")
        reset = matches.get("M9")
        champion_id: int | None = None
        if grand is not None and grand["status"] == "done":
            if reset is None or reset["status"] == "not_needed":
                champion_id = grand["winner_id"]
            elif reset["status"] == "done":
                champion_id = reset["winner_id"]
        if champion_id is None:
            return
        self._conn.execute(
            """
            UPDATE competition_tournament
            SET status = 'complete', champion_id = ?, updated_at = ?
            WHERE id = 1
            """,
            (champion_id, self._now()),
        )

    def _decide_winner(
        self, team_a: dict, team_b: dict, teams: list[dict]
    ) -> tuple[int, int]:
        score_a = int(team_a["total"] or 0)
        score_b = int(team_b["total"] or 0)
        if score_a > score_b:
            return team_a["id"], team_b["id"]
        if score_b > score_a:
            return team_b["id"], team_a["id"]
        # A tied match is still resolved, but it never consults the global
        # Team to Beat.  Aggregate accuracy, then WPM, then the lower seed.
        key_a = self._tiebreak_key(team_a)
        key_b = self._tiebreak_key(team_b)
        if key_a > key_b:
            return team_a["id"], team_b["id"]
        return team_b["id"], team_a["id"]

    def _tiebreak_key(self, team: dict) -> tuple[float, float, int]:
        rows = self._conn.execute(
            "SELECT accuracy, wpm FROM competition_representatives WHERE team_id = ?",
            (team["id"],),
        ).fetchall()
        accuracy = sum(float(row[0] or 0.0) for row in rows) / max(1, len(rows))
        wpm = sum(float(row[1] or 0.0) for row in rows) / max(1, len(rows))
        return (accuracy, wpm, -int(team["seed"]))

    def _apply_loss(self, team_id: int) -> None:
        row = self._conn.execute(
            "SELECT losses FROM competition_teams WHERE id = ?", (team_id,)
        ).fetchone()
        if row is None:
            return
        losses = int(row[0] or 0) + 1
        self._conn.execute(
            "UPDATE competition_teams SET losses = ?, eliminated = ? WHERE id = ?",
            (losses, 1 if losses >= 2 else 0, team_id),
        )

    def _write_match_result(
        self,
        match: dict,
        team_a_id: int,
        team_b_id: int,
        winner_id: int,
        loser_id: int,
    ) -> None:
        teams = self._load_teams()
        team_a = self._team_by_id(teams, team_a_id)
        team_b = self._team_by_id(teams, team_b_id)
        self._conn.execute(
            """
            UPDATE competition_matches
            SET team_a_id = ?, team_b_id = ?, score_a = ?, score_b = ?,
                winner_id = ?, loser_id = ?, status = 'done'
            WHERE id = ?
            """,
            (
                team_a_id,
                team_b_id,
                int(team_a["total"] or 0) if team_a else None,
                int(team_b["total"] or 0) if team_b else None,
                winner_id,
                loser_id,
                match["id"],
            ),
        )

    def _write_match_progress(
        self,
        match_id: int,
        team_a_id: int | None,
        team_b_id: int | None,
        status: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE competition_matches
            SET team_a_id = ?, team_b_id = ?, status = ?
            WHERE id = ?
            """,
            (team_a_id, team_b_id, status, match_id),
        )

    def _set_match_status(self, match_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE competition_matches SET status = ? WHERE id = ?",
            (status, match_id),
        )

    # ── Internal: row helpers ───────────────────────────────────────────────

    def _load_raw_matches(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT id, match_key, bracket, round_label, position, source_a,
                   source_b, team_a_id, team_b_id, score_a, score_b,
                   winner_id, loser_id, status, is_reset
            FROM competition_matches WHERE tournament_id = 1 ORDER BY id
            """
        ).fetchall()
        return [self._raw_match(row) for row in rows]

    @staticmethod
    def _raw_match(row) -> dict:
        return {
            "id": int(row[0]),
            "match_key": str(row[1]),
            "bracket": str(row[2]),
            "round_label": str(row[3]),
            "position": int(row[4]),
            "source_a": str(row[5]),
            "source_b": str(row[6]),
            "team_a_id": None if row[7] is None else int(row[7]),
            "team_b_id": None if row[8] is None else int(row[8]),
            "score_a": None if row[9] is None else int(row[9]),
            "score_b": None if row[10] is None else int(row[10]),
            "winner_id": None if row[11] is None else int(row[11]),
            "loser_id": None if row[12] is None else int(row[12]),
            "status": str(row[13]),
            "is_reset": bool(row[14]),
        }

    def _load_teams(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT id, name, seed, total, completed, finalized, losses, eliminated
            FROM competition_teams WHERE tournament_id = 1 ORDER BY seed
            """
        ).fetchall()
        return [
            {
                "id": int(row[0]),
                "name": str(row[1]),
                "seed": int(row[2]),
                "total": None if row[3] is None else int(row[3]),
                "completed": int(row[4]),
                "finalized": bool(row[5]),
                "losses": int(row[6]),
                "eliminated": bool(row[7]),
            }
            for row in rows
        ]

    @staticmethod
    def _team_by_id(teams: list[dict], team_id: int | None) -> dict | None:
        if team_id is None:
            return None
        for team in teams:
            if team["id"] == team_id:
                return team
        return None

    def _source_team_id(
        self, source: str, matches_by_key: dict[str, dict], team_by_seed: dict[int, dict]
    ) -> int | None:
        try:
            kind, value = source.split(":", 1)
        except ValueError:
            return None
        if kind == "team":
            try:
                team = team_by_seed.get(int(value))
            except ValueError:
                return None
            return team["id"] if team else None
        match = matches_by_key.get(value)
        if match is None or match["status"] != "done":
            return None
        if kind == "winner":
            return match["winner_id"]
        if kind == "loser":
            return match["loser_id"]
        return None

    def _match_status_map(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT match_key, status FROM competition_matches WHERE tournament_id = 1"
        ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    @staticmethod
    def _highest_finalized(teams: list[TeamView]) -> TeamView | None:
        finalised = [team for team in teams if team.finalized and team.total is not None]
        if not finalised:
            return None
        return max(finalised, key=lambda team: (int(team.total or 0), -team.seed))

    @staticmethod
    def _result_from_snapshot(
        snapshot: CompetitionSnapshot | None,
        team_id: int,
        slot: int,
        *,
        accepted: bool,
        duplicate: bool,
        reason: str,
    ) -> AttemptResult:
        team = snapshot.team_by_id(team_id) if snapshot else None
        return AttemptResult(
            accepted=accepted,
            duplicate=duplicate,
            reason=reason,
            team_id=team_id,
            team_name=team.name if team else "",
            slot=int(slot),
            team_completed=team.completed if team else 0,
            team_total=team.total if team else None,
            team_finalized=team.finalized if team else False,
            notice=snapshot.notice if snapshot else "",
            team_to_beat_id=snapshot.team_to_beat_id if snapshot else None,
            team_to_beat_name=snapshot.team_to_beat_name if snapshot else "",
            team_to_beat_score=snapshot.team_to_beat_score if snapshot else None,
            champion_id=snapshot.champion_id if snapshot else None,
            champion_name=snapshot.champion_name if snapshot else "",
        )

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
