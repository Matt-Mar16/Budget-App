# Budget Tracker — Complete Project Spec (v2)

Use this file to ask for the project to be built. It's self-contained — no earlier conversation needed.

## Context
Moving abroad for 8 months. Income arrives in **GBP**, gets exchanged into **CAD** for day-to-day spending. Need to track both currencies as separate budgets, log the exchanges themselves as transactions, log spend on the go (phone), and analyze it properly on a laptop.

This is deliberately a standalone, disposable system for the trip — it does not integrate with any other budgeting tool. Excel is a **transient inbox**, not the permanent ledger: entries get pushed to a local data store and the sheet resets to empty (headers only) after each push, so phone entry always starts from a clean, fast table instead of scrolling an ever-growing history.

---

## Architecture

```
[Phone] --Excel mobile--> [OneDrive Transactions.xlsx]   (transient inbox — cleared after each sync)
                                    |
                          sync_transactions.py  (laptop, run whenever you want fresh numbers)
                            1. read current Transactions rows
                            2. write a timestamped backup of exactly what was read
                            3. append those rows to the persistent log
                            4. clear the Transactions table back to headers, save
                                    |
                          [data/transactions_log.csv]   (persistent, append-only, full history)
                                    |
                             analyze.py   (laptop, anytime — never touches Excel)
                     (aggregate per currency, flag, chart)
```

- **Excel (OneDrive)** = data entry only, and only for whatever hasn't been pushed yet. Accounts and Categories sheets are permanent reference data and are never touched by the sync; only the Transactions table's data rows get cleared.
- **`sync_transactions.py`** = the one script allowed to write to the Excel file. Moves rows out of the phone's inbox and into permanent local storage.
- **`analyze.py`** = all the analysis, reading only the local persistent store. Reads full trip history, computes actual vs. budget per currency and category, flags overspend, charts it. Safe to re-run anytime with no side effects.
- Suggested layout: put both scripts and `data/` in their own subfolder (e.g. `trip-budget/`) rather than mixed in with any other Python project in the same directory, so the two stay easy to tell apart.

---

## Excel File Structure

### `Accounts` sheet
| Account | Currency | Starting balance | Starting date |
|---|---|---|---|
| UK Bank | GBP | 1200.00 | 2026-09-01 |
| CAD Chequing | CAD | 0.00 | 2026-09-01 |
| CAD Credit Card | CAD | 0.00 | 2026-09-01 |

- One row per real account or card, in whatever currency it holds.
- `Starting balance` is the actual balance on `Starting date` — the anchor point Python counts forward from, using the full history in `transactions_log.csv` (not the live Excel file, which won't hold full history after the first sync).

### `Categories` sheet
*(`—` in any table in this spec means: leave the cell blank in Excel — it's markdown shorthand, not a character to type.)*

| Category | Currency | Monthly budget | Label |
|---|---|---|---|
| Groceries | CAD | 400 | Groceries (CAD) |
| Rent | CAD | 900 | Rent (CAD) |
| Subscriptions | GBP | 30 | Subscriptions (GBP) |
| Income | GBP | — | Income (GBP) |
| ... | ... | ... | ... |
| Currency Exchange | — | — | Currency Exchange |

- Same category name can appear once per currency (e.g. "Groceries" only in CAD, "Subscriptions" only in GBP) — each (Category, Currency) pair is tracked independently.
- **`Label`** is a helper column: `=Category & " (" & Currency & ")"` for every normal row. The **`Currency Exchange`** row is the one exception — its Currency cell is blank, so the formula would otherwise produce `"Currency Exchange ()"` (empty parens, since concatenating a blank cell still leaves the surrounding parentheses); type its Label cell as plain text (`Currency Exchange`, no formula) instead.
- This Label — not the plain category name — is what the Transactions dropdown actually shows and stores (see below for why).
- Add an **`Income`** row per currency you receive money in, budget left blank (same convention as Currency Exchange — it's an inflow, not something to budget against).
- One extra fixed row: **`Currency Exchange | — | — | Currency Exchange`** (budget left blank — it's a transfer, not spend, and excluded from all budget totals).

### `Transactions` sheet (Excel Table, `Ctrl+T`)
| Date | Account | Category | Description | Amount | Currency | Exchange Rate |
|---|---|---|---|---|---|---|
| 2026-09-02 | UK Bank | Income (GBP) | Salary | 1500.00 | GBP | |
| 2026-09-03 | CAD Chequing | Groceries (CAD) | Superstore | -62.40 | CAD | |
| 2026-09-05 | UK Bank | Currency Exchange | GBP exchanged | -500.00 | GBP | 1.72 |
| 2026-09-05 | CAD Chequing | Currency Exchange | Converted from GBP | 860.00 | CAD | 1.72 |

- **This table is a transient inbox.** After each run of `sync_transactions.py` it's cleared back to just its header row — it never holds more than the entries since your last sync.
- **Account dropdown** sourced from `Accounts` — every transaction (including each leg of a currency exchange) belongs to exactly one account.
- **Category dropdown** sourced from `Categories.Label` (e.g. "Groceries (CAD)") — this is the value actually stored in the cell, not the plain category name, because Excel data validation can't show one thing in a dropdown while storing another. When Python loads a row, it splits the label back into `category` and `currency` (e.g. on the last `" ("`).
- **Currency** auto-fills via one `XLOOKUP(Category, Categories.Label, Categories.Currency)` formula — the one formula this workbook uses; everything else is Python's job. Exception: on **Currency Exchange** rows, the lookup returns blank (the category row has no fixed currency), so type Currency manually (GBP or CAD) — a single exchange event spans two currencies, so it can't be looked up from one category row. Give the Currency column its own dropdown restricted to `{GBP, CAD}` as a typo guard on these manually-entered rows.
- **Sign convention**: negative `Amount` = money out (an expense, or GBP leaving on an exchange); positive = money in (income, or CAD arriving on an exchange). Applies uniformly across expense, income, and exchange rows — Python relies on this to tell them apart.
- **Exchange Rate** only populated on `Currency Exchange` rows — the actual rate you got, not a market rate.
- A currency exchange is always logged as **two rows, same date**: GBP outflow from one account + CAD inflow to another. No explicit link between the two rows is needed — see the exchange-rate calculation below, which aggregates each leg independently instead of pairing rows.

---

## Local Data Store

`data/transactions_log.csv` — append-only, one row per transaction ever pushed, same columns as the Transactions sheet plus a `synced_at` timestamp. This is the actual source of truth for everything Python computes; the Excel file only ever holds the not-yet-synced tail.

`data/backups/` — `sync_transactions.py` writes a timestamped copy of whatever it's about to push (e.g. `pushed_2026-09-12_1430.csv`) before clearing the sheet, so a bad sync is recoverable by hand.

---

## Money-Flow Sankey Diagram

A Sankey diagram of where the money actually went, cumulative over the whole trip. It reuses numbers the plan already computes elsewhere — no new aggregation logic, just reshaping existing totals into nodes and links.

**Nodes**: `Income (GBP)` → per-category GBP spend nodes, `Currency Exchange`, `Unspent GBP` → `CAD Funds` → per-category CAD spend nodes, `Unspent CAD`.

**Links** (link width = amount):
- `Income (GBP)` → each GBP category with spend (that category's total GBP spend)
- `Income (GBP)` → `Currency Exchange` (total GBP exchanged)
- `Income (GBP)` → `Unspent GBP` (the leftover — same figure as the "unexchanged GBP" balance already planned)
- `Currency Exchange` → `CAD Funds` (total CAD received)
- `CAD Funds` → each CAD category with spend (that category's total CAD spend)
- `CAD Funds` → `Unspent CAD` (the CAD account's running balance)

Every node's inflows must sum to its outflows (`Income (GBP)` in = GBP spend + exchanged + unspent; `CAD Funds` in = CAD spend + unspent) — that balancing is what makes a Sankey diagram read correctly, so build it as the last step after the other totals exist and are trusted, not before.

**Library**: `plotly` (`plotly.graph_objects.Sankey`) is the practical choice — matplotlib's built-in `Sankey` class is built for single-path energy/material-flow diagrams and gets awkward fast with more than a couple of branching nodes. This is the one new dependency beyond pandas/matplotlib; note it in Skills/setup instructions if that matters for the build environment.

---

## Feature List

### v1
- Log a transaction (date, category, description, amount) — phone or laptop
- Category + budget list, split by currency, with an Income category per currency
- Dropdown validation on Account and Category (Category auto-fills Currency)
- Currency exchange logged as a linked transaction pair, with the actual rate applied
- `sync_transactions.py`: push Transactions rows into the persistent log (backed up first), then reset the sheet to headers
- `analyze.py`: load the persistent log into a DataFrame
- Actual vs. budget per category, **calculated separately for GBP and CAD**
- Remaining budget per category, per currency
- Flag categories over budget (independently per currency)
- Effective average GBP→CAD exchange rate over the trip — computed as `total CAD received tagged Currency Exchange ÷ abs(total GBP sent tagged Currency Exchange)`, no row-pairing required
- Running balance per account — starting balance + cumulative transactions on that account up to today, from the persistent log
- "Unexchanged GBP" is just the UK Bank account's running balance — reuse the per-account balance function rather than a separate calculation (holds as long as all GBP income and spend flow through that one account, true in the example Accounts sheet above; if a second GBP account is ever added, this shortcut breaks and needs its own sum again)
- Flag if an account's running balance goes negative (or below a set threshold, e.g. a credit card limit)
- Bar chart: actual vs. budget per category (one for CAD, one for GBP)
- Sankey diagram: cumulative money flow, GBP income → direct GBP spend / exchange / unspent GBP, then CAD funds → CAD spend categories / unspent CAD (see dedicated section above)

### Stretch
- Manual "actual balance" check-ins per account, with Python flagging a mismatch against the calculated balance (catches a missed or mistyped transaction)
- Streamlit dashboard instead of a plain script — clickable local app
- Overspend run-rate projection (spend-so-far ÷ days elapsed vs. budget, warns before you actually go over)
- Compare your exchange rate against the historical market rate on that date, via a free FX API (`requests` + e.g. exchangerate.host) — shows whether you're getting a fair deal
- Multi-month trend view (line chart per category over time)
- Bank CSV import via pandas (skip manual entry)
- Recurring-payment detection (inferred from history — different from just scheduling a known recurring bill)

---

## Build Order
1. `Accounts` sheet — list real accounts/cards, currency, and current actual balance as the starting point
2. `Categories` sheet — real categories, currency per category, rough budget guesses, the `Label` helper column, the `Currency Exchange` row, and an `Income` row per currency
3. `Transactions` sheet as a Table — Account + Category(Label) dropdowns, Currency auto-fill via XLOOKUP, save to OneDrive
4. Verify the phone ↔ laptop round-trip works before relying on it: add a test row on the phone, confirm it appears on the laptop copy, and vice versa
5. Log 2–3 weeks of real spending, mixing phone and laptop entry, including at least one currency exchange pair and one income entry
6. Build `sync_transactions.py`: read → backup → append to `data/transactions_log.csv` → clear sheet to headers → save
7. Run the first sync; confirm the log has the expected rows and the sheet is back to just headers
8. Build `analyze.py`: load the log, split into GBP and CAD, compute actual vs. budget per category per currency
9. Running balance per account (and reuse it for the "unexchanged GBP" figure)
10. Overspend flagging (per currency) + low/negative balance flagging (per account)
11. Exchange-rate summary (aggregate average rate, per note above)
12. Charts — one bar chart per currency
13. Sankey diagram — build last, once every total it depends on (category spend, exchanged amount, unspent GBP/CAD) is already computed and trusted
14. Stretch features, in whatever order is useful once the above works

---

## Cautions
- **OneDrive sync lag**: confirm both phone and laptop show "up to date" before running `sync_transactions.py` — syncing mid-edit risks either missing a just-entered phone row, or having it reappear after the sheet was cleared.
- **Clear scope**: the reset must only ever touch the Transactions table's data rows. Accounts and Categories are permanent reference data and should never be modified by the sync script.
- **No automatic dedup, on purpose**: matching rows by content (date+account+category+amount+description) to detect "already pushed" transactions sounds safe but isn't — two genuinely identical same-day transactions (two coffees, two identical parking fees) would match each other and the second would be silently dropped. Instead, the backup-then-append-then-clear order keeps the risky window short, and a backup file always exists to check by hand: if a sync is ever interrupted, look at the most recent file in `data/backups/` against the tail of `transactions_log.csv` before re-running, rather than re-running blindly.

---

## Skills This Builds
- Excel: structured Tables, data validation, cross-sheet lookups
- Python/pandas: reading Excel programmatically, `groupby`/`merge` aggregation across two currency pools, append-only log management
- matplotlib (or streamlit) for visualization
- plotly Sankey diagrams — modeling money flow as balanced nodes/links
- FX/currency handling — real-world relevant for a banking role
- Account balance reconciliation logic — the same core idea as bank reconciliation work
- `requests` + a public API, if the market-rate comparison stretch is built
