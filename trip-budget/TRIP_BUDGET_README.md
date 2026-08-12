# Trip Budget Tracker

GBP/CAD trip budget tracker: log spend on your phone in Excel (via OneDrive),
sync it into a permanent local log, and analyze it with Python. See
`../budget-tracker-plan.md` for the full spec this was built from.

## One-time setup

For phone entry to reach this laptop copy, this folder (or at least
`Data.xlsx`) needs to live inside a OneDrive-synced tree — it currently does
not, so phone edits won't reach this copy until that's set up.

1. `Data.xlsx` has already been generated here. Open it and:
   - Edit the `Accounts` sheet with your real accounts/cards and starting balances.
   - Edit the `Categories` sheet with your real categories and budgets.
   - Delete row 2 of the `Transactions` sheet (the "Example — delete this row"
     placeholder) before you start logging real transactions.
2. Dependencies are installed in `.venv/` already (pandas, openpyxl, matplotlib,
   plotly, pytest). Activate it or call scripts via `.venv/Scripts/python.exe`.

## Day to day

Log transactions on your phone or laptop directly in the `Transactions` table
in `Data.xlsx`. When you want fresh numbers, on the laptop, run the dashboard:

```bash
.venv/Scripts/python.exe dashboard.py
```

This does everything in one step: reads whatever's currently in `Data.xlsx`'s
`Transactions` table, backs it up to `data/backups/`, appends it to
`data/transactions_log.csv`, clears the sheet back to just its header row (so
it's ready for new entries), then prints budget-vs-actual and account
balances and writes bar charts + a money-flow Sankey diagram to
`data/charts/`.

`sync_transactions.py` (just the load-and-clear step) and `analyze.py` (just
the report, without touching the Excel file) are still available separately
if you want to run either step on its own.

All three scripts accept `--excel`, `--log`, `--charts-dir` / `--backups-dir`
if you ever move files around; defaults assume everything stays in this folder.

## Tests

```bash
.venv/Scripts/python.exe -m pytest
```
