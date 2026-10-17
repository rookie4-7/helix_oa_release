"""Compatibility import for the moved base strategy rules."""

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from base_setup_engine.strategy_logic import *  # noqa: F401,F403,E402
