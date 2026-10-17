# Helix: Systematic GBP/USD Trading Research and Strategy Engine

Helix is a systematic GBP/USD trading project covering rule-based strategy
development, market-structure analysis, simulated trade execution, and risk and
performance evaluation. It combines a versioned Python strategy engine with an
Excel for Mac interface for configuring, running, and reviewing experiments.
Historical backtesting is one component of this wider research workflow.

The strategy focuses on London-session breakout and retracement setups, using
M15 candles for setup analysis and M1 mid/bid/ask data for execution simulation.
The wider project also includes manual-trade comparison, shadow tests, and
statistical evaluation of proposed rules. This public repository contains the
release engine and its supporting tools; private research documents, datasets,
manual trade logs, and historical experiment archives are not included.

This is a research and simulation system. **Live broker execution is not
implemented**, and the project makes no claim of proven alpha. The included
workbook selects **Mark 4 v0.1.0**. Trading rules and Strategy_Params are
preserved from the research version. The 2022-2024 period has been used for
development and is not an untouched holdout.

## Project Components

| Component | Responsibility |
| --- | --- |
| Strategy engine | Detect London-session breakout and retracement setups using Asia ranges and body-based pivots. |
| Market structure and context | Evaluate pivot, price-cluster, and trendline obstacles, with configurable contextual exceptions. |
| Execution simulation | Model entries, stops, targets, spread-aware fills, and news/session forced exits using historical price data. |
| Risk and performance analysis | Report trade returns in R, win rate, profit factor, Sharpe ratios, drawdown, and equity curves. |
| Data validation | Check input data, including missing bars, spreads, and timezone consistency, and expose diagnostic reports. |
| Experiment controls and audit | Configure versioned parameters through Excel, preserve run archives, and record trade and signal decisions for review. |

The release also includes regression tests and a synthetic-data demonstration
so the software workflow can be checked without distributing private prices.

## Quick Start on macOS

Requirements: an independent Python 3.11+ installation, Terminal, and Microsoft
Excel for Mac for the workbook buttons. The command-line runner does not need
Excel. Codex is not required. The verified local Python version is recorded in
[release validation](docs/RELEASE_VALIDATION.md).

From this folder:

```sh
bash excel_runner/setup_python_macos.sh /path/to/python3
bash excel_runner/install_bridge_macos.sh
.venv/bin/python3 tools/run_checks.py
```

Use the path to your installed Python, or omit it to use `python3` on PATH.
The setup creates a project-local `.venv` and installs pinned runtime packages.
The bridge installer installs only the supplied AppleScript handler in Excel's
per-user script folder, preserving a backup if an older handler differs.

Open `Backtest_Model_Runner.xlsm` in Excel. Enable macros only after reviewing
and trusting this project; do not disable global macro security. The buttons
locate this repository from the workbook's folder, so keep the workbook inside
the release folder. Folder names may contain spaces, but the VBA launcher
currently rejects apostrophes. After relocating the project, recreate `.venv`
at the new location instead of copying an existing virtual environment.
On first use, Excel may ask for file access to the launcher, Python executable
or output workbook. Check that each prompt names this trusted release copy.

## Try Without Private Data

```sh
.venv/bin/python3 tools/make_demo.py
.venv/bin/python3 shared_execution_engine/excel_runner.py --workbook Backtest_Model_Runner.xlsm --mode write --price-data-root demo_data --news-data-root demo_data --output-root demo_output
```

This generates deterministic **synthetic** M1/M15 prices and a clearly labelled
synthetic news event for January 2022. It is a pipeline demonstration, not a
performance backtest or a full-year dataset. It leaves the workbook parameters
unchanged. Calendar-completeness warnings are expected because the data is
deliberately incomplete. Repeating the demo data generator refuses to overwrite
existing files.

The Excel button expects real input files under the project root. The demo
command deliberately uses a separate directory so it cannot masquerade as your
real prices. For real data layouts and timezone assumptions, see
[Data and Reports](docs/DATA_AND_REPORTS.md).

## Run Your Data

The shipped workbook selects `WF_2022` / `OOS`. Inspect Config and
Strategy_Params before every run. Only the selected window is executed; a dry
run still computes the selected strategy and is not just a syntax check.

```sh
.venv/bin/python3 shared_execution_engine/excel_runner.py --workbook Backtest_Model_Runner.xlsm --mode write --price-data-root /path/to/prices --news-data-root /path/to/calendar
```

`--mode write` creates a new output workbook. The input workbook is not replaced
by Python. Output workbooks are under `excel_runner_runs`; each output has its
own archive directory. Existing output files/archive directories are refused,
not overwritten. The Excel button also records a log under `excel_runner_logs`.
An output workbook can be rerun while it remains inside this repository.

No prices, manual trade logs, personal trade explanations, credentials,
historical result archives, or local Python environment are distributed here.
Supply data you have permission to use. Keep data and generated results out of
Git; the included `.gitignore` covers the standard locations.

## Layout

| Folder | Responsibility |
| --- | --- |
| `mark_4/engine` | Active strategy, parameters, contextual rules and tests |
| `mark_3/engine`, `mark_2/engine` | Earlier versioned implementation dependencies and compatibility |
| `shared_execution_engine` | Prices, sessions, news, execution, metrics and reporting |
| `base_setup_engine` | Legacy setup/import compatibility |
| `excel_runner` | Auditable VBA source, AppleScript bridge and macOS setup |
| `tools`, `tests` | Synthetic demo, checks and release portability tests |

The workbook's `Engine_Profile` chooses the version. Do not select an older
profile while retaining incompatible newer parameters. Historical parameter
workbooks and research notebooks remain in the separate research repository.
Historical `manifest.json` files are provenance, not current release checksums.
`release_manifest.json` records this release copy separately.

## Scope and Limitations

- M1 candles cannot reproduce the exact intraminute tick path or peak spread.
- Data-quality warnings are diagnostic and do not add trading filters.
- Timezone checks detect inconsistency but cannot prove a source's timezone.
- The release has regression and portability tests, not live-order integration.
- Research-period returns and matching statistics do not establish statistical
  significance or future profitability.

See [release validation](docs/RELEASE_VALIDATION.md) for exactly what was tested
and what remains unverified. Nothing in the setup or test scripts downloads
market data or automatically runs a multi-year performance backtest.

## License

This release is licensed under the [MIT License](LICENSE). Third-party
dependencies retain their own licenses. Private research files and market data
are not included in this release.
