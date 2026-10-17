"""Excel/CLI entry point; uses the original runner's CLI and output schema."""
from runtime import load_shared

runner = load_shared("excel_runner")

if __name__ == "__main__":
    raise SystemExit(runner.main())
