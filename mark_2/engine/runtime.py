"""Locate the unchanged execution and workbook services used by Mark 2."""
import importlib.util
from pathlib import Path
import sys

ENGINE_DIR = Path(__file__).resolve().parent
REPOSITORY = next(
    (p for p in ENGINE_DIR.parents if (p / "shared_execution_engine/backtest_engine.py").exists()),
    None,
)
if REPOSITORY is None:
    raise RuntimeError("Missing shared_execution_engine. Keep the release folder structure intact.")
SHARED = REPOSITORY / "shared_execution_engine"
for path in (SHARED, ENGINE_DIR):
    if str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))


def load_shared(name):
    module_name = "mark2_shared_" + name
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SHARED / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
