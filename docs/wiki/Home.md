# SignalSync

Daily scanner that checks every S&P 500 constituent on daily bars for three bullish chart patterns (Cup & Handle, Inverse Head & Shoulders, Bullish Wolfe Wave) and reports only confirmed, risk-defined setups with an entry, a structural stop and a reference target. Heuristic screener, not trading advice.

| Page | Contents |
|---|---|
| [Architecture and Data Pipeline](01-Architecture-and-Data-Pipeline.md) | universe source, ingestion and throttling, which bar is scanned, output contract, scheduling |
| [Pattern Catalog](02-Pattern-Catalog.md) | exact geometric criteria, formulas for entry / stop / target / score, edge cases |
| [Configuration and Tuning](03-Configuration-and-Tuning.md) | every threshold, what loosening or tightening it does, false-positive filters |
| [Testing and Contributing](04-Testing-and-Contributing.md) | running the suite, fixtures, adding a pattern, code style, workflows |

Source: `docs/wiki/` in the [code repository](https://github.com/yanivil/SignalSync/tree/main/docs/wiki). The `sync-wiki` workflow overwrites these wiki pages whenever that directory changes on `main`, so edit the files in the repository rather than here.
