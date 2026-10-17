MARK 3 ENGINE
Version: Mark3-0.1.1

Based on the frozen Mark2-0.2.0 setup generator and shared execution services.
Mark 2's files remain unchanged. Consolidation remains removed.

DEFAULT CONFIGURATION
5/5 pivot obstacles and price clusters enabled, both with 24-calendar-month expiry.
Expiry starts at confirmation close. An obstacle is inactive at its expiry
boundary. Touches do not restart its age. Structural cancellation can end it earlier.
0 months disables calendar expiry. Both lifespan fields remain workbook-editable.
Clusters retain six candles, 96 earlier reference bars, equal weights,
wick-based score strictly above 50 and candle-body obstacle boxes.
Original current-day pivot, Asia, IBOS, 2/2-only rejection and execution rules remain.

PIVOT REGISTRATION (10 OCTOBER 2026)
Consecutive M15 candles sharing the same turning price are one pivot when
the first candle's close equals the next candle's open at that body high/low.
Keep the first candle's timestamp and day. Highs and lows remain separate.
Flat candles connected at that exact turn remain part of the same pivot.
Separate returns to a price, gaps, and merely nearby prices are not merged.
Each scale keeps the confirmation close of its actual qualifying window.
Later larger-scale confirmation never re-arms a consumed pivot or changes
earlier setup anchors. Obstacles and repeated visits use the same identity.

REPEATED-VISIT PIVOT EXCEPTION
Track body-price visits around a confirmed pivot seed, without using outcomes.
Buy uses body highs; Sell uses body lows. Highs and lows are separate structures.
Default membership band: seed +/-4 pips.
A close 5 pips beyond that band completes a departed visit.
Repeated contact before departure remains one visit, regardless of pivot labels.
Require at least three departed visits with causally confirmed pivot evidence.
The actual current-day setup pivot must be a member of a completed visit before
its break candle opens. An incidental or historical pivot is not sufficient.
The repeated structure must still be intact immediately before this break.
The first clean close through its observed floor/ceiling must happen in this
same imbalance run, by the original entry line's availability time.
The first break consumes the structure. No polarity flip or reactivation.
There is no new SD gate or separate calendar expiry on repeated-visit structures.
The exception waives pivot obstacles only, on the qualifying entry line.
It never waives clusters, 2/2-only rejection, news cancellation or entry timing.
Switching the exception off restores ordinary combined-obstacle decisions.

WORKBOOK
Backtest_Model_Runner.xlsm keeps its filename and existing buttons.
Config Engine_Profile: MARK_3_CURRENT_ENGINE; engine version: Mark3-0.1.1.
Runner B2 displays the active version. Archives use archive/mark_3_current_engine.
Strategy_Params C96: pivot expiry; C97: cluster expiry; C102: exception Yes/No.
C103: minimum visits; C104: membership half-width in pips; C105: departure pips.
New parameters are labelled Added in Mark 3. Existing Mark 2 provenance remains.
Changing expiry is independent of enabling the exception.
Output workbooks preserve buttons, parameter formatting and these controls.

DIAGNOSTICS
Each original entry-line audit records original and remaining obstacle hits,
ignored pivot obstacles, qualification witnesses, previously blocked status,
and whether an exception actually waived a hit.
The signal archive retains confirmation, visit, setup-pivot and break timestamps.
The existing Signal_Audit blocked/reason fields describe the resulting gate.
Existing audit keys prefixed mark2 describe inherited setup rules, not engine version.

RESEARCH LIMITATIONS
Before the first-candle registration repair, the selected 2022-2023 shadow
configuration had 138 trades, +5.05R, F1 51.6%. These are pre-repair results.
F1 improved significantly versus no obstacles in that study; profit and Pearson
did not. The exception alone restored two trades and is exploratory.
This is not independently validated alpha. Further refinement belongs to Mark 4.
