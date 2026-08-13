# Budget Tracker

This repo holds **two independent, unrelated projects**. They share no
code, no dependencies, and no run command — each has its own README with
the real detail.

## [THE LEDGER](ledger/src/README.md)
A local-first desktop budgeting app (Tkinter + SQLite, Python stdlib only —
nothing to install, nothing leaves your machine). Multiple isolated
profiles, multi-currency accounts, budgets/envelopes, recurring bills,
cashback and round-up rewards, a debt payoff planner, investment tracking
with UK capital-gains estimates, spend forecasting, and a phone-entry
bridge for logging transactions on the go.

```
cd ledger
python3 budget_app.py
```

This is the actively-developed, actively-used project in this repo.

## [Trip Budget Tracker](trip-budget/TRIP_BUDGET_README.md)
A smaller Excel + pandas tool: log trip spend on your phone in a shared
Excel workbook, sync it into a permanent CSV log, and get a budget-vs-actual
report and charts. Purpose-built for one specific trip (GBP/CAD), not yet
in daily use.

```
cd trip-budget
.venv/Scripts/python.exe dashboard.py
```

## For AI coding agents
[`CLAUDE.md`](CLAUDE.md) at the repo root has the full architecture,
commands, and mechanism-level detail both projects' READMEs don't try to
duplicate — read it before making changes to either project.

## Real data stays out of git
Real financial data (`ledger/Profiles/`, `trip-budget/data/`,
`trip-budget/Data.xlsx`, any bank `statements/`) is excluded via
`.gitignore` and never committed.
