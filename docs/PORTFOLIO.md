# EXS Trade Journal: project case study

A local-first analytics product that captures MetaTrader trades automatically and turns them into behavioural insight for retail traders.

**Repository:** [ebixs/Trade_Journal_Expert_Forex](https://github.com/ebixs/Trade_Journal_Expert_Forex)

## Résumé entry

**EXS Trade Journal** · Personal product · Python, FastAPI, SQLite, MQL4/5, JavaScript

- Built a local-first trading analytics platform that ingests live MetaTrader data through a read-only expert advisor.
- Designed a pipeline that rebuilds round-trip trades from raw deals, including partial exits and broker-time normalisation.
- Developed risk and performance metrics: R multiple, profit factor, expectancy, maximum drawdown and captured share of favourable excursion.
- Implemented rule-based detection of trading behaviours and quantified the profit or loss linked to each one.
- Combined economic calendars and RSS news into per-market fundamentals with surprise analysis and source health tracking.
- Integrated a configurable LLM coach that uses structured statistics and removes account identity before sending data.
- Delivered Persian right-to-left dashboards with eight themes, self-updating desktop launchers and automated backups.
- Wrote 65 automated tests and reproduced a concurrency failure under load before fixing it with per-thread database connections.

## The problem

Traders repeat costly habits because memory favours good outcomes. Manual journals are abandoned quickly, and hosted tools require handing over private trading history.

## The approach

1. **Capture without friction.** The expert syncs in the background and has no ability to trade.
2. **Model the data correctly.** Raw deals remain the source of truth and every trade is derived from them.
3. **Separate evidence from advice.** Statistics are computed in code. The language model only explains them, and small samples are stated plainly.
4. **Respect privacy.** Everything runs locally, and account identity never reaches the AI service.

## Skills demonstrated

| Area | Evidence |
|---|---|
| Data modelling | Deal-to-trade reconstruction, partial closes, MT4 ticket chaining |
| Analytics | Performance metrics, group comparison, minimum-sample rules |
| Data engineering | Idempotent ingestion, incremental cursors, feed normalisation |
| Backend | FastAPI, SQLite in WAL mode, background workers, token authentication |
| Applied AI | Provider-agnostic LLM integration, prompt boundaries, data minimisation |
| Frontend and data visualisation | Dependency-free SVG charts, Persian RTL interface, measured text contrast |
| Reliability | Automated tests, load reproduction, failure isolation between sources |

## Honest scope

The project was built with AI-assisted development. It runs on macOS with MT5 on a demo account. The MT4 build and the Windows launcher have not been run on real systems yet, and the AI coach has not yet been tested with a live provider.
