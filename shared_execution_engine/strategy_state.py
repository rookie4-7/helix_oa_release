from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategyRuntimeState:
    asia_high: float | None = None
    asia_low: float | None = None
    asia_body_peak: float | None = None
    asia_body_trough: float | None = None
    asia_max_body_drop_pct: float = 0.0
    asia_max_body_rise_pct: float = 0.0
    asia_bull_done: bool = False
    asia_bear_done: bool = False
    daily_swing_high: float | None = None
    daily_swing_low: float | None = None
    ds_bull_done: bool = False
    ds_bear_done: bool = False
    asia_bull_confirmed: bool = False
    asia_bear_confirmed: bool = False
    ds_bull_confirmed: bool = False
    ds_bear_confirmed: bool = False
    buy_b_done: bool = False
    sell_b_done: bool = False
    first_buy_locked: bool = False
    first_sell_locked: bool = False
    consolidation_broken: bool = False
    pre_london_resistance_pivot: dict[str, Any] | None = None
    pre_london_support_pivot: dict[str, Any] | None = None
    pre_london_bull_break_consumed: bool = False
    pre_london_bear_break_consumed: bool = False
    previous_in_asia: bool = False
    previous_in_london_setup: bool = False
    run: dict[str, Any] | None = None
    signals: list[dict[str, Any]] = field(default_factory=list)

    def reset_new_london_day(self) -> None:
        self.daily_swing_high = None
        self.daily_swing_low = None
        self.ds_bull_done = False
        self.ds_bear_done = False
        self.first_buy_locked = False
        self.first_sell_locked = False
        self.pre_london_resistance_pivot = None
        self.pre_london_support_pivot = None
        self.pre_london_bull_break_consumed = False
        self.pre_london_bear_break_consumed = False

    def reset_london_setup(self) -> None:
        self.asia_bull_confirmed = False
        self.asia_bear_confirmed = False
        self.ds_bull_confirmed = False
        self.ds_bear_confirmed = False
        self.buy_b_done = False
        self.sell_b_done = False
        self.first_buy_locked = False
        self.first_sell_locked = False

    def start_asia_session(self, row: dict[str, Any]) -> None:
        self.asia_high = row["buy_body_high"]
        self.asia_low = row["sell_body_low"]
        self.asia_body_peak = row["buy_body_high"]
        self.asia_body_trough = row["sell_body_low"]
        self.asia_max_body_drop_pct = 0.0
        self.asia_max_body_rise_pct = 0.0
        self.asia_bull_done = False
        self.asia_bear_done = False

    def extend_asia_session(self, row: dict[str, Any]) -> None:
        self.asia_high = row["buy_body_high"] if self.asia_high is None else max(self.asia_high, row["buy_body_high"])
        self.asia_low = row["sell_body_low"] if self.asia_low is None else min(self.asia_low, row["sell_body_low"])
        if self.asia_body_peak is not None and self.asia_body_peak > 0:
            self.asia_max_body_drop_pct = max(
                self.asia_max_body_drop_pct,
                (self.asia_body_peak - row["sell_body_low"]) / self.asia_body_peak,
            )
        if self.asia_body_trough is not None and self.asia_body_trough > 0:
            self.asia_max_body_rise_pct = max(
                self.asia_max_body_rise_pct,
                (row["buy_body_high"] - self.asia_body_trough) / self.asia_body_trough,
            )
        self.asia_body_peak = (
            row["buy_body_high"]
            if self.asia_body_peak is None
            else max(self.asia_body_peak, row["buy_body_high"])
        )
        self.asia_body_trough = (
            row["sell_body_low"]
            if self.asia_body_trough is None
            else min(self.asia_body_trough, row["sell_body_low"])
        )

    def update_daily_swing_high(self, pivot_high: float) -> None:
        self.daily_swing_high = pivot_high if self.daily_swing_high is None else max(self.daily_swing_high, pivot_high)
        self.ds_bull_done = False

    def update_daily_swing_low(self, pivot_low: float) -> None:
        self.daily_swing_low = pivot_low if self.daily_swing_low is None else min(self.daily_swing_low, pivot_low)
        self.ds_bear_done = False

    def mark_asia_breaks(self, break_flags: Any) -> None:
        if break_flags.bull_break:
            self.asia_bull_done = True
        if break_flags.bear_break:
            self.asia_bear_done = True

    def consume_pre_london_asia_break(self, side: str) -> None:
        if side == "Buy":
            self.asia_bull_done = True
            self.first_buy_locked = True
            self.pre_london_bull_break_consumed = True
        if side == "Sell":
            self.asia_bear_done = True
            self.first_sell_locked = True
            self.pre_london_bear_break_consumed = True

    def mark_daily_swing_breaks(self, break_flags: Any) -> None:
        if break_flags.bull_break:
            self.ds_bull_done = True
        if break_flags.bear_break:
            self.ds_bear_done = True

    def consume_pre_london_daily_swing_reaches(self, row: dict[str, Any]) -> None:
        if self.daily_swing_high is not None and row["buy_body_high"] > self.daily_swing_high:
            self.ds_bull_done = True
        if self.daily_swing_low is not None and row["sell_body_low"] < self.daily_swing_low:
            self.ds_bear_done = True

    def reset_consolidation_if_not_ready(self, ready: bool) -> None:
        if not ready:
            self.consolidation_broken = False

    def mark_valid_setup_confirmations(self, side: str, run_obj: dict[str, Any]) -> None:
        if run_obj["asia_valid"]:
            self.asia_bull_confirmed = side == "Buy" or self.asia_bull_confirmed
            self.asia_bear_confirmed = side == "Sell" or self.asia_bear_confirmed
        if run_obj["ds_valid"]:
            self.ds_bull_confirmed = side == "Buy" or self.ds_bull_confirmed
            self.ds_bear_confirmed = side == "Sell" or self.ds_bear_confirmed

    def mark_buy_sell_b(self, buy_b: bool, sell_b: bool) -> None:
        if buy_b:
            self.buy_b_done = True
        if sell_b:
            self.sell_b_done = True

    def set_first_break_locks(self, first_buy_locked: bool, first_sell_locked: bool) -> None:
        self.first_buy_locked = first_buy_locked
        self.first_sell_locked = first_sell_locked

    def mark_previous_sessions(self, in_asia: bool, in_london_setup: bool) -> None:
        self.previous_in_asia = in_asia
        self.previous_in_london_setup = in_london_setup

    def clear_run(self) -> None:
        self.run = None

    def upsert_run(
        self,
        idx: int,
        row: dict[str, Any],
        bull: bool,
        asia_signal: bool,
        ds_signal: bool,
        consol_signal: bool,
        internal_signal: bool,
        current_setup: bool,
        setup_body_valid: bool,
        side_body_size: float,
        pip_size: float,
    ) -> None:
        side_high = row["buy_body_high"] if bull else row["sell_body_high"]
        side_low = row["buy_body_low"] if bull else row["sell_body_low"]
        if self.run is None:
            self.run = {
                "direction": row["direction"],
                "start_i": idx,
                "end_i": idx,
                "count": 1,
                "high": side_high,
                "low": side_low,
                "wick_high": row["mid_high"],
                "wick_low": row["mid_low"],
                "close": row["mid_close"],
                "asia": asia_signal,
                "ds": ds_signal,
                "consol": consol_signal,
                "internal": internal_signal,
                "asia_valid": asia_signal and setup_body_valid,
                "ds_valid": ds_signal and setup_body_valid,
                "consol_valid": consol_signal and setup_body_valid,
                "internal_valid": internal_signal and setup_body_valid,
                "valid_imbalance": current_setup and setup_body_valid,
                "has_setup": current_setup,
                "largest_body_pips": side_body_size / pip_size if current_setup else 0,
                "first_setup_i": idx if current_setup else None,
                "first_valid_i": idx if current_setup and setup_body_valid else None,
                "entry_frozen": False,
                "frozen_entry_price": None,
            }
            return

        self.run["end_i"] = idx
        self.run["count"] += 1
        self.run["high"] = max(self.run["high"], side_high)
        self.run["low"] = min(self.run["low"], side_low)
        self.run["wick_high"] = max(self.run["wick_high"], row["mid_high"])
        self.run["wick_low"] = min(self.run["wick_low"], row["mid_low"])
        self.run["close"] = row["mid_close"]
        self.run["asia"] = self.run["asia"] or asia_signal
        self.run["ds"] = self.run["ds"] or ds_signal
        self.run["consol"] = self.run["consol"] or consol_signal
        self.run["internal"] = self.run["internal"] or internal_signal
        self.run["asia_valid"] = self.run["asia_valid"] or (asia_signal and setup_body_valid)
        self.run["ds_valid"] = self.run["ds_valid"] or (ds_signal and setup_body_valid)
        self.run["consol_valid"] = self.run["consol_valid"] or (consol_signal and setup_body_valid)
        self.run["internal_valid"] = self.run["internal_valid"] or (internal_signal and setup_body_valid)
        self.run["valid_imbalance"] = self.run["valid_imbalance"] or (current_setup and setup_body_valid)
        self.run["has_setup"] = self.run["has_setup"] or current_setup
        if current_setup:
            self.run["largest_body_pips"] = max(self.run["largest_body_pips"], side_body_size / pip_size)
            self.run["first_setup_i"] = self.run["first_setup_i"] if self.run["first_setup_i"] is not None else idx
            if setup_body_valid and self.run["first_valid_i"] is None:
                self.run["first_valid_i"] = idx

    def freeze_run_entry(self, entry: float) -> None:
        if self.run is None:
            return
        self.run["entry_frozen"] = True
        self.run["frozen_entry_price"] = entry
