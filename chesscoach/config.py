"""All tunable knobs in one place (docs/01-architecture.md "Configuration knobs")."""
from __future__ import annotations

import os
import shutil

ENGINE_PATH = os.environ.get("CHESSCOACH_STOCKFISH") or shutil.which("stockfish") or "stockfish"
SYZYGY_PATH = os.environ.get("CHESSCOACH_SYZYGY")          # None → no tablebase probing
MAIA_MODEL_DIR = os.environ.get("CHESSCOACH_MAIA_DIR", "models/maia2")

CONFIG: dict[str, object] = {
    "engine.depth_live": 16,
    "engine.depth_review": 22,
    "engine.multipv": 3,
    "engine.threads": 2,
    "engine.hash_mb": 128,
    "engine.pool_size": 2,
    "engine.depth_threat": 12,          # 02 §6.4
    "engine.time_live": 0.35,           # s per live search: depth OR time, whichever first (01 latency)
    "engine.time_threat": 0.15,         # s per live null-move threat search
    "policy.max_comments_per_10_moves": 3,
    "bot.temperature": 1.0,
    "steer.max_win_prob_cost": 0.05,
    "steer.max_win_prob_cost_tactic": 0.15,
    "structure.threshold": 1.0,         # 02 §6.3 similarity threshold
}

# Bump whenever detector logic changes; part of the PositionFeatures cache key (01).
DETECTOR_VERSION = 1


def get(key: str):
    return CONFIG[key]
