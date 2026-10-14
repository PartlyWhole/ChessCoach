import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

PINNED_ENGINE = "Stockfish 19"


@pytest.fixture(scope="session")
def pool():
    if shutil.which("stockfish") is None:
        pytest.skip("stockfish not installed")
    from chesscoach.analysis.engine import EnginePool
    # One thread: deterministic search for engine-dependent expectations (08 §1).
    p = EnginePool(size=1, threads=1, hash_mb=64, clear_hash=True)
    if not p.version.startswith(PINNED_ENGINE):
        pytest.skip(f"tests pinned to {PINNED_ENGINE}, found {p.version}")
    yield p
    p.close()


@pytest.fixture(scope="session")
def analyzer(pool):
    from chesscoach.analysis.analyzer import Analyzer
    return Analyzer(pool)
