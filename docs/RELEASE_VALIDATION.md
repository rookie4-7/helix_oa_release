# Release Validation

Prepared 2026-10-17. This is a packaging release of Mark 4 v0.1.0, not a new
strategy version and not a statistical alpha test.

## Verified

| Check | Result |
| --- | --- |
| Fresh local Python environment | Python 3.13.9, independent of Codex |
| Runtime dependency check | openpyxl 3.1.5, et_xmlfile 2.0.0, lxml 6.1.1; pip check passed |
| Mark 4 unit suite | 123 passed |
| Shared reporting and data-quality suite | 40 passed |
| Release portability and workbook checks | 7 passed |
| Relocated copy in a path containing spaces | All 170 checks passed again |
| Synthetic CLI demonstration | Passed, wrote workbook and archive |
| Native Excel launch | Run_Backtest_Write macro completed from the relocated copy; EXIT_CODE=0; output opened |
| Button bindings | Existing Dry_Run_Backtest and Run_Backtest_Write bindings retained |
| Native workbook open | No repair warning on the release template or generated synthetic result |
| AppleScript installer | Installed successfully; repeat invocation recognized the same handler |
| Original research files | All 1,309 inventoried non-cache files unchanged |

The native launch was invoked from Excel's Macros dialog using the exact macro
bound to the existing Run Backtest button. The button binding and drawing parts
were also checked. Excel requested file access to the relocated launcher,
Python executable/folder and generated workbook; these are normal macOS Excel
sandbox prompts. No global macro-security setting was changed.

The synthetic demo has 4,320 M1 candles, 288 M15 candles and one synthetic news
event. It produced one invalid signal and zero completed trades with unchanged
parameters. It tests loading, reporting and launch plumbing, not profitability.

## Real-Data Regression

Only **2022** was replayed. Existing private M1 prices, M15 context and news were
read externally; those files are not in this release. Earlier M15 sheets were
read for the unchanged obstacle-history calculation, not traded as test years.

| Metric | Original baseline | Release copy |
| --- | ---: | ---: |
| Completed trades | 66 | 66 |
| Wins | 22 | 22 |
| Losses | 44 | 44 |
| Win rate | 33.3333% | 33.3333% |
| Net R | +7.978663729950792 | +7.978663729950792 |
| Unfilled candidates | 72 | 72 |

The 138 total trade records include 72 no-fills. They are not 138 completed
trades. All eight strategy JSON outputs matched the existing verification
archive exactly after JSON parsing: summary, yearly summary, parameters, news,
trades, signals, equity curve and signal audit.

Strategy parameter hash:

```text
59255695847dbc2fd2993166fab8857471828f4d61d4dc0931df5f0f32752d00
```

## Release-Only Changes

- Portable VBA/Python launch paths and explicit errors for an incomplete copy.
- Optional CLI roots for externally stored prices, news and output archives.
- Separate archives per generated output, with overwrite protection.
- Expected import filenames restored using byte-identical copies of the two
  legacy modules whose research filenames include ` 2`.
- Workbook personal launch history and author metadata sanitized. Strategy_Params
  and Config worksheet XML remain byte-identical to the original.
- Historical manifest paths made relative; historical hashes preserved.
- Setup/bridge instructions, data specification, tests and a synthetic demo.

Trading, setup, obstacle, execution, risk and news-rule source files are
byte-identical to their source copies. Runtime location helpers changed only
path fallback behavior. `release_manifest.json` records release file hashes.

## Limits

Tested on this Mac, not a second physical machine. Windows Excel buttons are not
supported. Python 3.11/3.12 and other operating systems were not validated here.
Earlier Mark 2/3 historical workbook configurations were not replayed. Their
legacy code remains available, but the supported shipped template is Mark 4.
No 2015-2025 sweep was performed. The 2022 replay is a regression check on a
development period, not fresh out-of-sample evidence. The raw-data regression
cannot be reproduced from public files alone without equivalent licensed inputs.

The local validation above did not create a remote repository or upload files.
This release uses the [MIT License](../LICENSE). GitHub publication is a separate
step from validation. Do not publish the private verification archives, original
research documents, price files or manual trade logs with this copy.
