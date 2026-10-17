# Data and Reports

## Required Price Layout

Under the project root (Excel) or `--price-data-root` (CLI):

```text
GBP_USD_M1_MBA/
    GBP_USD_M1_MBA_2022.xlsx       sheet: 2022
GBP_USD_M15_MBA_2015_2025_by_year.xlsx
                                sheet: 2022
```

The M15 filename is a legacy convention, not an instruction to run 2015-2025.
Mark 4 also reads earlier M15 sheets for obstacle context. With the supplied
`obstacle_context_start_year=2020`, a 2022 run needs M15 sheets 2020, 2021 and
2022, but M1 execution data only for 2022. Earlier candles are context, not trades
in the selected test period. With obstacles off, the previous year's M15 data
is still used for context. Use corresponding M1 filenames and sheet names for
other selected years. The synthetic demo supplies header-only history sheets;
use actual historical candles for meaningful research.

Each sheet begins with `time`, then `mid_open`, `mid_high`, `mid_low`,
`mid_close`, and the equivalent `bid_*` and `ask_*` columns. Optional fields are
`volume`, `spread_open`, `spread_high`, `spread_low`, `spread_close`.

Prices are decimal GBP/USD prices. One pip is 0.0001. Timestamps represent
candle opening times and must be UTC. Excel timestamps are timezone-naive;
the loader interprets them as UTC and converts sessions to Europe/London.
Do not write London local time into a UTC-labelled sheet. M1 and M15 must
describe the same market/source and compatible timestamps.

## News Calendar

Put `news_calendar.csv` under the project root or `--news-data-root`. The
loader also recognizes the paths listed in `shared_execution_engine/news_loader.py`.
A simple schema is:

```csv
datetime,timezone,currency,impact,event
2022-01-05 19:00:00,UTC,USD,High,Synthetic demo event (not real news)
```

The row above is illustrative only. Use complete, correctly timestamped real
news for real backtests. Missing news data must not silently be replaced by a
synthetic file. Existing news-filter and forced-close rules are unchanged.

## Status Meaning

- `Pending` / `Not Checked` in an unused template means no validation result
  has been written yet. Review the generated output workbook, not the template.
- `Validated` means the core required-data checks passed.
- `Review` means informational checks found warnings requiring inspection.
- Missing or malformed required data is reported separately and may prevent a
  run under the existing engine validation behavior.

Data_Catalog and Data_Quality_Report record scanned rows, timestamp bounds,
possible missing bars, maximum observed spread, timezone diagnostics and a
link to the detailed JSON report. Those fields are populated in write-mode
outputs. Missing-bar checks use a market-session calendar; holidays and
historical schedule differences can produce warnings. Maximum spread is from
available bid/ask open/close observations, not an unseen tick maximum.

## Result Counts

The trade archive can include unfilled/blocked candidate records. Completed
trades, wins and losses should be reconciled by status before comparing totals.
Do not interpret a total record count as the number of executed positions.

Excel outputs preserve strategy parameters and native runner controls. The
archive contains JSON snapshots for trades, signals, parameters, news, equity,
yearly summaries and data validation. Archives are generated artifacts and
should not be committed accidentally with licensed prices or manual records.
