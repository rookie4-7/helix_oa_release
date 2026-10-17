MARK 4 ENGINE
Version: Mark4-0.1.0
Status: development configuration. Mark 3 and Mark 2 remain unchanged.
Development period: 2022-2024. These years are not untouched OOS for this rule.

Retain Mark3-0.1.1 setup rules, merged pivots, both 24-month obstacles,
pivot-only repeated-visit exception, news exits and 18:00 London forced close.

ADDED IN MARK 4
Original two-pivot resistance lines for buys and support lines for sells.
Reuse original line construction, body validation, four-anchor retention,
body-break cancellation and annual reset. Default hit half-width is 1.5 pips;
body-break tolerance is 2.0 pips. Evaluate the completed run body extreme.
No regression calculation or slope-direction requirement.

Require a trendline hit AND at least one cluster-score condition:
trade-side oldest local score >70;
trade-side latest local score >65;
opposite-side latest trailing score >50.
Trade side means highs for buys and lows for sells. Highs/lows stay separate.
Use the latest three distinct confirmed merged 5/5 pivots before run start
as score references only. Oldest requires three pivots; latest may still be
available with fewer. Missing scores do not qualify; equality does not qualify.

Scores use the existing Atlas formula: six consecutive M15 candles, highs/lows
for calculation, four equal weights and 96 earlier reference candles.
Body boxes contain the exact pivot price. A local box must also include the
pivot candle and be completed by its confirmation. The trailing box ends
at that pivot candle. Score references are not required to remain active
obstacles. This score gate is separate from the existing active cluster filter.
Repeated-visit exceptions cannot waive this new trendline obstacle.

WORKBOOK
Keep the filename Backtest_Model_Runner.xlsm and existing buttons.
Engine_Profile: MARK_4_CURRENT_ENGINE. Runner Engine cell shows Mark4-0.1.0.
use_trendline_obstacles = Yes enables the original lines.
use_trendline_cluster_score_filter = Yes qualifies hits with the score rule.
No to the score switch means unqualified original trendline obstacles.
No to the trendline switch restores Mark 3 behaviour with the same parameters.
The three strict score cutoffs are editable and labelled Added in Mark 4.
Entry-line and signal archives retain line hits, score components, reference
pivot confirmation times, cluster boxes and blocking conditions for inspection.

No trading filter is justified solely by net R. Historical cutoff selection
remains a research limitation. Do not run outside 2022-2024 without permission.
