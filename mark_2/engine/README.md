# Mark 2 current engine edition

Version: `Mark2-0.2.0`, frozen no-expiry research configuration on 2026-10-08.
This is the active Excel-runner implementation, not the
earlier Mark 2 scoring or BC hard-rule research. It is based on current engine
0.8.0, with rules from `Current engine vs BC engine Rule.docx` and the user's
subsequent clarifications.

## Rules

- London setups 08:00 to before 12:00; pending lines expire at noon, GMT/BST aware.
- Asia, current-day daily swing and IBOS; existing Buy B/Sell B combinations.
- Body pivots use symmetric 2, 3 and 5 candle confirmation. Equal prices qualify.
  A candle/side is registered once, at its earliest confirmation. Later larger
  scales do not rearm it. Daily swing retains the current engine's highest
  current-day high and lowest current-day low, not every smaller local pivot.
- Historical confirmed pivots are tracked for 1,024 M15 candles. Their breaks
  NEVER create, validate, or rescue a setup. They are context only, associated
  with a current-day pivot break in the SAME directional imbalance run, before
  or simultaneously. The current-day prerequisite is directional and resets
  with the run. A prior-day break before that prerequisite is not retroactively
  promoted. Historical breaks are consumed after the first confirmed close
  beyond the level and cannot be rearmed by another confirmation scale.
- Structural and setup break distances default to 0.1 pip.
- IBOS additionally requires a break of a previously confirmed current-London-day
  body pivot in the same directional imbalance run, during the London setup
  window. Buy breaks a pivot high; sell breaks a pivot low. Any configured pivot
  scale qualifies, not just the day's highest/lowest pivot. Already consumed,
  prior-day, unconfirmed and wick-only breaks do not qualify. The pivot close
  break uses the existing structural-break buffer. Existing IBOS shelf, Asia
  movement and setup-break conditions remain unchanged. The two conditions may
  occur in either order within the run; the entry is never live before both are
  known. Reversals, new days and entry-touch run freezes reset the prerequisite.
- Retain the original consecutive-direction BODY run and 61.8% retracement,
  not BC's alternative swing or 08:00-reset entry measurements.
- Retain original run validation: at most 5 candles and a qualifying setup
  candle body of at least 4 pips. Original valid live lines before a later run
  extension, and the entry-touch freeze, are preserved.
- Multiple daily fills and same-direction fills are allowed. Setup consumption
  and Buy B/Sell B state rules remain, including the Buy B Asia-range condition.
- Consolidation calculation, setups and obstacles are removed. Legacy workbook
  fields remain for schema compatibility and are inactive; enabling removed
  switches is rejected explicitly rather than silently ignored.
- Pivot obstacles are on for 5/5 only. An active resistance/support BODY box
  blocks a buy/sell when the run's furthest directional BODY price finishes
  inside it. The box uses original side-specific sorted first/third open-close
  prices from the pivot pair. A later body high above resistance, or body low
  below support, cancels it permanently. A wick alone does not cancel it.
- Atlas price clusters are on: six consecutive M15 candles, 96 earlier reference
  candles excluding the candidate, four equal 25% weights, score strictly >50.
  Wick highs/lows determine overlap and compactness; close movement determines
  slowness and back-and-forth. The obstacle box is minimum/maximum BODY price
  across the six candles, not their wick range. Only clusters completed before
  the run starts can block. The run's furthest directional BODY price must land
  inside an active box. Any hit blocks, without ranking by later performance.
  A later close above the body box cancels resistance; a later close below it
  cancels support. Cancellation is permanent per direction, without polarity flip.
- Both obstacle expiry values are 0 months: no calendar expiry, with structural
  cancellation still active. Available historical M15 context starts in 2020
  by default. History coverage is recorded; no prior-year trades are generated.
  The separate 1,024-bar historical SETUP pivot book remains unchanged.
- Conditional 2/2-only rejection is on. Only actual authorising Asia, DS and
  IBOS pivot sources count. Preserve an independent Asia route or an actual
  setup pivot already confirmed at 3/3 or 5/5. An incidental 5/5 crossing cannot
  rescue a 2/2-only setup, and later confirmation never rescues an earlier line.
- Trendlines, order blocks, old adverse-context filters and strength override
  remain off. IBOS remains the original separately named shelf setup.
- Existing news invalidation and 15-minute pre-news forced close remain on.
  The 18:00 London forced close remains on. Existing flexible risk and bid/ask
  execution are reused, without reimplementation or threshold optimisation.

## Runner

Open `Backtest_Model_Runner.xlsm` at the repository root and use the existing
Dry Run Backtest / Run Backtest buttons. The Config Engine_Profile marker routes
the workbook to this engine; a name alone does not select strategy code.
Runner!B2 identifies the frozen no-expiry Mark 2 version. Run metadata records
`Mark2-0.2.0`; all three research switches default to Yes in Strategy_Params.
Strategy_Params shows editable values in yellow and unavailable switches in grey.
Obsolete consolidation, single-scale pivot and context settings are
retained for compatibility. Numeric inputs have numeric validation rather than
Yes/No lists. The three header rows stay frozen. Risk and retracement are shown
as percentages without changing the stored ratios. The shared writer's output
is post-processed to retain this layout, input validation and native buttons;
parameter values calculated or written by the run are never overwritten.
The initial selection is WF_2022 / OOS, i.e. calendar 2022 only. Selecting an IS
window can cover earlier years; no 2015-2025 sweep was run during this build.

Previous engine and runner snapshots are preserved before updating. The shared Excel launcher has only a profile
dispatch addition; execution, data loaders, metrics and output schemas are reused.
`strategy_logic.py` is the engine-derived Mark 2 strategy. `setup_logic.py` retains
Asia/DS/IBOS and B definitions. `pivot_logic.py` supplies causal confirmations and
context. `context_filters.py` scores clusters, tracks obstacle cancellation and
gates candidate live lines. `config.py` holds validation and parameter loading. `backtest_engine.py`
and `excel_runner.py` connect these to the shared engine services.

## Frozen candidate semantics

Candidate generation, setup consumption and hypothetical entry-touch freezes
remain identical to v0.1.1. The three filters gate that candidate-line stream
before execution, without creating replacement setups. Removed updates never
extend old orders. Every decision uses only information known at that line's
close. Original risk, fills, news handling and 18:00 close are unchanged.
Signal JSON contains actual setup anchors and every filtered line with obstacle
prices and timestamps. Fully blocked signals are Invalid, preventing execution
fallback. Switches may be disabled for a control run, but doing so changes the
frozen research configuration and must be recorded in the parameter snapshot.

Verification on 2022: all 301 original execution records reproduced with filters
off; all 509 single-obstacle decisions and 23,577 qualifying cluster scores/boxes
matched the saved research. With all three no-expiry rules: 63 fills, +1.1568R,
25 manual matches, 38 extras and 10 misses. This is not the earlier 24-month
shadow result of 65 fills and +5.2065R. Neither result establishes alpha.
No 2015-2025 trade sweep was run. This is a frozen research version, not a claim
of validated profitability or deployment readiness.
