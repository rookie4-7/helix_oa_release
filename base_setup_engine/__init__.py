"""Shared GBP/USD candidate, setup, and obstacle rules.

The existing implementation supports both package imports and historical
top-level imports. The shared runtime path is added here only to preserve that
compatibility while the old research scripts remain in use.
"""

from pathlib import Path
import sys


SHARED_EXECUTION_ROOT = Path(__file__).resolve().parents[1] / "shared_execution_engine"
if str(SHARED_EXECUTION_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_EXECUTION_ROOT))

from .obstacle_logic import ObstacleCheck
from .setup_logic import BreakFlags
from .setup_logic import ConsolidationBreakFlags
from .setup_logic import ConsolidationSnapshot
from .setup_logic import SetupSignals

__all__ = [
    "BreakFlags",
    "ConsolidationBreakFlags",
    "ConsolidationSnapshot",
    "ObstacleCheck",
    "SetupSignals",
]
