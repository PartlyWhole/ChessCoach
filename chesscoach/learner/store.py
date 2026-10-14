"""Learner store (docs/01 "Learner store", 06 §2): portable relational schema, SQLite here.
Structured fields (Glicko, settings, assessments, hits) are JSON columns."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Optional

from chesscoach.learner.glicko2 import Glicko
from chesscoach.learner.mastery import ConceptMastery, Opportunity
from chesscoach.learner.srs import ReviewCard

SCHEMA = """
CREATE TABLE IF NOT EXISTS learner_profile (
  player_id TEXT PRIMARY KEY,
  game_rating TEXT NOT NULL,      -- Glicko JSON
  drill_rating TEXT NOT NULL,
  band TEXT NOT NULL,
  bot_offset REAL NOT NULL,
  settings TEXT NOT NULL,         -- CoachSettings JSON
  repertoire TEXT NOT NULL        -- {"white": [...], "black": [...]}
);
CREATE TABLE IF NOT EXISTS concept_mastery (
  player_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  state TEXT NOT NULL,
  opportunities INTEGER NOT NULL,
  successes INTEGER NOT NULL,
  hint_depth_sum INTEGER NOT NULL,
  last_seen_at TEXT,
  rating TEXT,
  history TEXT NOT NULL,          -- recent opportunities, for the windowed state rules
  PRIMARY KEY (player_id, concept_id)
);
CREATE TABLE IF NOT EXISTS review_card (
  card_id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  fen TEXT NOT NULL,
  solution TEXT NOT NULL,
  concept_ids TEXT NOT NULL,
  source TEXT NOT NULL,
  srs TEXT NOT NULL,
  due TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS review_card_due ON review_card (player_id, due);
CREATE TABLE IF NOT EXISTS game_log_move (
  game_id TEXT NOT NULL,
  ply INTEGER NOT NULL,
  assessment TEXT NOT NULL,
  hits TEXT NOT NULL,
  coach_event TEXT,
  bot_move TEXT,
  clock_ms INTEGER,
  PRIMARY KEY (game_id, ply)
);
CREATE TABLE IF NOT EXISTS game (
  game_id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  player_color TEXT NOT NULL,
  start_fen TEXT NOT NULL,
  moves TEXT NOT NULL,
  result REAL,
  lesson_focus TEXT,
  concepts_mentioned TEXT,
  finished_at TEXT
);
"""

HISTORY_KEEP = 20


class Store:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    # ---- profile
    def save_profile(self, player_id: str, game_rating: Glicko, drill_rating: Glicko, band: str,
                     bot_offset: float, settings: dict, repertoire: Optional[dict] = None) -> None:
        self.db.execute("REPLACE INTO learner_profile VALUES (?,?,?,?,?,?,?)",
                        (player_id, json.dumps(asdict(game_rating)), json.dumps(asdict(drill_rating)), band,
                         bot_offset, json.dumps(settings), json.dumps(repertoire or {"white": [], "black": []})))
        self.db.commit()

    def load_profile(self, player_id: str) -> Optional[dict]:
        r = self.db.execute("SELECT * FROM learner_profile WHERE player_id=?", (player_id,)).fetchone()
        if r is None:
            return None
        return {"player_id": r[0], "game_rating": Glicko(**json.loads(r[1])), "drill_rating": Glicko(**json.loads(r[2])),
                "band": r[3], "bot_offset": r[4], "settings": json.loads(r[5]), "repertoire": json.loads(r[6])}

    # ---- mastery
    def save_mastery(self, m: ConceptMastery) -> None:
        self.db.execute("REPLACE INTO concept_mastery VALUES (?,?,?,?,?,?,?,?,?)",
                        (m.player_id, m.concept_id, m.state, m.opportunities, m.successes, m.hint_depth_sum,
                         m.last_seen_at, json.dumps(asdict(m.rating)) if m.rating else None,
                         json.dumps([asdict(o) for o in m.history[-HISTORY_KEEP:]])))
        self.db.commit()

    def load_mastery(self, player_id: str) -> dict[str, ConceptMastery]:
        out = {}
        for r in self.db.execute("SELECT * FROM concept_mastery WHERE player_id=?", (player_id,)):
            out[r[1]] = ConceptMastery(r[0], r[1], r[2], r[3], r[4], r[5], r[6] or "",
                                       Glicko(**json.loads(r[7])) if r[7] else None,
                                       [Opportunity(**o) for o in json.loads(r[8])])
        return out

    # ---- cards
    def save_card(self, c: ReviewCard) -> None:
        self.db.execute("REPLACE INTO review_card VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (c.card_id, c.player_id, c.kind, c.fen, json.dumps(c.solution), json.dumps(c.concept_ids),
                         json.dumps(c.source), json.dumps(c.srs), c.srs.get("due"), c.created_at))
        self.db.commit()

    def load_cards(self, player_id: str) -> list[ReviewCard]:
        return [ReviewCard(r[0], r[1], r[2], r[3], json.loads(r[4]), json.loads(r[5]), json.loads(r[6]),
                           json.loads(r[7]), r[9] or "")
                for r in self.db.execute("SELECT * FROM review_card WHERE player_id=? ORDER BY due", (player_id,))]

    # ---- game log
    def log_move(self, game_id: str, ply: int, assessment: dict, hits: list, coach_event: Optional[dict],
                 bot_move: Optional[dict] = None, clock_ms: Optional[int] = None) -> None:
        self.db.execute("REPLACE INTO game_log_move VALUES (?,?,?,?,?,?,?)",
                        (game_id, ply, json.dumps(assessment), json.dumps(hits),
                         json.dumps(coach_event) if coach_event else None,
                         json.dumps(bot_move) if bot_move else None, clock_ms))
        self.db.commit()

    def game_log(self, game_id: str) -> list[dict]:
        rows = self.db.execute("SELECT * FROM game_log_move WHERE game_id=? ORDER BY ply", (game_id,))
        return [{"game_id": r[0], "ply": r[1], "assessment": json.loads(r[2]), "hits": json.loads(r[3]),
                 "coach_event": json.loads(r[4]) if r[4] else None, "bot_move": json.loads(r[5]) if r[5] else None,
                 "clock_ms": r[6]} for r in rows]

    def save_game(self, game_id: str, player_id: str, color: str, start_fen: str, moves: list[str],
                  result: Optional[float], lesson_focus: Optional[str], concepts_mentioned: list[str],
                  finished_at: str = "") -> None:
        self.db.execute("REPLACE INTO game VALUES (?,?,?,?,?,?,?,?,?)",
                        (game_id, player_id, color, start_fen, json.dumps(moves), result, lesson_focus,
                         json.dumps(concepts_mentioned), finished_at))
        self.db.commit()

    def recent_games(self, player_id: str, n: int) -> list[dict]:
        rows = self.db.execute("SELECT game_id, result, concepts_mentioned FROM game WHERE player_id=? "
                               "ORDER BY rowid DESC LIMIT ?", (player_id, n))
        return [{"game_id": r[0], "result": r[1], "concepts_mentioned": json.loads(r[2] or "[]")} for r in rows]
