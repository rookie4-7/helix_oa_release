# Base Setup Engine

This package contains the strategy rules shared by Mark 1 and Mark 2 before
their version-specific context and selection logic is applied.

- `setup_logic.py`: Asia, daily-swing, consolidation, internal-structure, Buy B
  and Sell B setup conditions.
- `obstacle_logic.py`: pivot, consolidation and trendline obstacle mechanics.
- `strategy_logic.py`: baseline candidate generation and period orchestration.

No Mark 1 or Mark 2 score belongs here. Price loading, trade simulation and
metrics remain in `shared_execution_engine/`.
