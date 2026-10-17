"""Run isolated unit suites without private data or performance backtests."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
suites = [
    (ROOT / "mark_4/engine", ["discover", "-s", ".", "-p", "test_*.py", "-q"]),
    (ROOT / "shared_execution_engine", ["test_data_quality_reporting", "test_price_data_diagnostics", "-q"]),
    (ROOT, ["discover", "-s", "tests", "-p", "test_*.py", "-v"]),
]
for cwd, args in suites:
    print(f"Checking {cwd.relative_to(ROOT) or '.'}", flush=True)
    subprocess.run([sys.executable, "-B", "-m", "unittest", *args], cwd=cwd, env=env, check=True)
print("All release checks passed. No market-data backtest was run.")
