# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Always invoke `/superpowers:using-superpowers` at the start of any task in this repository, before taking any other action.**

## Repository layout

This repo holds **two independent, unrelated projects**, each in its own subfolder — they share no dependencies, test suite, or run command. Check which project a file belongs to before assuming a convention carries over from the other.

- **THE LEDGER** — `ledger/`: a desktop Tkinter + SQLite budgeting app. `budget_app.py` is the one file at the top of `ledger/` — it's the entry point you actually run. Everything it imports lives in `ledger/src/`: `finance_core.py`, `profiles.py`, `theme.py`, `crypto_utils.py`, `charts.py`, plus the phone-entry bridge (`inbox_sync.py`, `sync_inbox.py`), `README.md`, and `requirements.txt`. `Profiles/` (real per-profile SQLite data), `tests/`, and `.venv/` stay at the top of `ledger/` alongside `budget_app.py`.
- **Trip Budget Tracker** — `trip-budget/`: an Excel + pandas trip budget tool — `dashboard.py`, `analyze.py`, `build_template.py`, `finance.py`, `sync_transactions.py`, `tests/`, `data/`, `Data.xlsx`, `requirements.txt`, `.venv/`, `TRIP_BUDGET_README.md`, `budget-tracker-plan.md` — left flat, not reorganized.

A separate, much larger aspirational document, `personal-finance-hub-features.md` (repo root), covers a future "Personal Finance & Markets Hub" — trading/quant, IB valuation, asset management, risk, macro tools — that's explicitly out of scope for both projects above. THE LEDGER's Investments/Tax tabs are a deliberately narrower placeholder for part of that vision; see below.

---

## THE LEDGER

### Layout
`budget_app.py` sits alone at the top of `ledger/` as the one entry point. Everything it imports — `finance_core.py`, `profiles.py`, `theme.py`, `crypto_utils.py`, `charts.py`, `inbox_sync.py`, `sync_inbox.py`, plus `README.md`/`requirements.txt` — lives in `ledger/src/`. `budget_app.py` adds `src/` to `sys.path` at the top of the file before its own imports, so every module inside `src/` keeps using plain `import finance_core`/`import profiles`-style imports unchanged. `profiles.py`'s `APP_DIR` (where `Profiles/` lives) is computed two directories up from its own file — `src/`'s parent — so real per-profile data is never mixed in with source code. `tests/conftest.py` adds both `ledger/` and `ledger/src/` to `sys.path` for pytest.

### Commands
- Run the GUI: `cd ledger && python3 budget_app.py` (needs Tkinter; on Linux, `sudo apt install python3-tk` if missing)
- `budget_app.py`/`src/finance_core.py`/`src/profiles.py`/`src/theme.py`/`src/crypto_utils.py`/`src/charts.py` have no third-party dependencies — stdlib only (`tkinter`, `sqlite3`, `datetime`, `uuid`, `dataclasses`, `statistics`, `typing`, `os`, `re`, `hashlib`, `hmac`, `struct`). This is deliberate — don't add a dependency to the GUI app itself.
- `src/inbox_sync.py`/`src/sync_inbox.py` (phone-entry bridge, see below) need `openpyxl` — isolated in their own `ledger/.venv` (`pip install -r src/requirements.txt`) so the GUI stays dependency-free.
- Run the tests (from `ledger/`): `.venv/Scripts/python.exe -m pytest` (173 tests across `tests/test_finance_core.py`, `tests/test_budget_app.py`, `tests/test_profiles.py`, `tests/test_inbox_sync.py`)
- Regenerate the inbox workbook for a profile: `.venv/Scripts/python.exe src/sync_inbox.py --profile <slug> --build`
- Load phone-entered transactions and clear the inbox: `.venv/Scripts/python.exe src/sync_inbox.py --profile <slug>`

### Architecture
Layered, no service/repo indirection: `budget_app.py` (Tkinter UI, one tab class per screen) imports specific functions/classes from `finance_core` plus the whole `profiles`, `theme`, `charts` modules. `finance_core.py`/`profiles.py` are stdlib-only; `profiles.py` does lazy/local imports of `finance_core.Database` and `crypto_utils` to avoid import cycles and keep encryption fully opt-in.

The data layer is `finance_core.Database` (`finance_core.py:32`), wrapping one `sqlite3.Connection` and exposing ~70 CRUD/finance methods. Read-only aggregation (net worth, savings rate, safe-to-spend, payoff simulation, etc.) is separate: plain module-level functions that take a `Database` instance rather than methods on it.

UI tabs hold `self.app.db` and call `Database` methods directly — e.g. `TransactionsTab.add_transaction()` calls `finance_core.would_exceed_budget()` for the budget-enforcement warning, then `self.app.db.add_transaction(...)`, then `self.app.refresh_all()`.

**Entry point flow**: `if __name__ == "__main__"` builds `ProfileLauncher` (a `tk.Tk` subclass) and calls `.mainloop()`. Picking a profile calls `ProfileLauncher._open()`, which prompts for a password via `simpledialog` if the profile is locked (`profiles.unlock_profile()`), then builds `App(profile)` — this opens `Database(profiles.db_path_for(slug))`, runs `generate_due_recurring()`, and builds the sidebar/tabs. `switch_profile()`/`on_close()` explicitly call `db.close()` before destroying the window (a deliberate Windows file-lock fix — don't remove it).

**Page lifecycle**: every tab is built once, up front, in `App._build_layout()` — switching tabs never recreates widgets, `App.show_page()` just raises the target tab (`tkraise()`) and refreshes only that one tab's data. `App.refresh_all()`, by contrast, refreshes every tab's data regardless of which is visible — called after any action that changes the database, so a tab never shows stale data the next time it's switched to.

**Nav structure**: `NAV_GROUPS` (`budget_app.py`) is a "Daily" group (Dashboard, Transactions, Budgets, Insights, Forecast — always expanded) and a "Planning" group (Recurring, Debt Planner, Accounts, Net Worth/FI, Investments, Tax, Rewards — starts collapsed). `NAV_ITEMS` is the flattened version, used where the full flat list is needed (page-title lookup, Settings checklist). Settings itself lives in its own pinned sidebar footer row, not in either group. Per-tab visibility (`hidden_nav_tabs` setting, `get_hidden_nav_tabs()`/`set_hidden_nav_tabs()`) lets any tab except Dashboard/Settings be hidden from a "Customize Navigation" card in `SettingsTab` — `PROTECTED_NAV_KEYS = {"dashboard", "settings"}` enforces that defensively even against a hand-edited setting.

### Key mechanisms (know these before touching financial logic)
- **Balance effects**: `_apply_balance_effect_nocommit()` (`finance_core.py`) is the single source of truth for how a transaction changes an account balance (asset vs. liability accounts move in opposite directions). Called from `add_transaction`, `generate_due_recurring`, `transfer_between_accounts`, and reversed manually inside `update_transaction`/`_delete_transaction_row_nocommit` — all four call sites must stay consistent if this logic changes.
- **Round-ups**: computed inline in `_apply_roundup_nocommit()` on every negative-amount insert/edit/recurring post; reversed by looking up the `roundups` table by `transaction_id` on delete/edit.
- **Transfers**: `transfer_between_accounts()` inserts two linked rows sharing a `transfer_group_id`, both `is_transfer=1`; cross-currency rate is frozen as `historical_rate` on the destination leg (an optional `to_amount` param lets the caller supply the real observed destination amount instead of a computed one). A leg can't be edited directly (`update_transaction` refuses if `is_transfer`); deleting one deletes both unless `delete_transfer_pair=False`.
- **`is_transfer` exclusion**: `transactions_in_month(year, month, include_transfers=False)` and `category_anomalies` filter out transfer legs by default — this keeps internal transfers (and balance-reconciliation adjustments, which reuse the same flag) out of savings-rate/safe-to-spend/budget/anomaly math, while `account_ledger()` always includes them for the per-account statement view. Any new aggregate function needs to make the same choice explicitly.
- **Reconciliation**: `reconciled`/`reconciled_date` columns plus `reconcile_transaction()`/`unreconcile_transaction()`/`reconcile_many()`. `update_transaction`/`delete_transaction` raise `ReconciledTransactionError` unless called with `force_unreconciled=True`.
- **Balance adjustments**: `add_balance_adjustment(account_id, actual_balance, date=None)` computes the delta between a stated real-world balance and the tracked one and posts it as a transaction with `apply_cashback_roundup=False, is_transfer=True` (so it doesn't pollute cash-flow aggregates). Wired into `AccountsTab` as "Reconcile…", with a before/after diff preview.
- **Custom reporting month**: the "month" the app reports on doesn't have to be the calendar month — `month_start_day` (Settings, 1-28, default 1) shifts it, e.g. `25` makes the period run 25th-to-24th for a payday-aligned budget. `month_bounds(db, year, month) -> (start_date, end_date)` and `custom_month_for_date(db, a_date) -> (year, month)` are exact inverses and the two primitives everything else builds on; `_month_start_day(db)` reads/clamps the setting. **Convention: a period is labeled by the calendar month it *starts* in** — with `month_start_day=25`, label `(2026, 8)` means 25 Aug-24 Sep, not 25 Jul-24 Aug (easy to get backwards — verify against `month_bounds` directly, not intuition, if touching this). `daily_spend_totals()` is a deliberate exception, kept on plain calendar months, since it feeds `charts.draw_calendar_heatmap`, a literal weekday-grid chart that can't represent a cross-calendar-month period.
- **Profile encryption**: `crypto_utils.py` is a stdlib-only PBKDF2-HMAC-SHA256 + HMAC-SHA256-counter-mode cipher (hand-rolled, not independently reviewed — see README caveat). `profiles.lock_profile()`/`unlock_profile()` swap `<slug>.db` ↔ `<slug>.db.locked`.
- **Recurring auto-post**: `generate_due_recurring(today)` runs at `App.__init__` and via `RecurringTab.post_due()`; loops while `next_date <= today`, applying balance/round-up effects and advancing via `_advance_date()` (supports weekly/monthly/yearly, an every-N-months `"custom"` frequency via `custom_interval_months`, and a one-shot `"once"` frequency that deactivates the item after posting instead of advancing it), capped at 36 iterations per item.
- **Cashback destination**: `accounts.cashback_auto_invest_account_id` (nullable FK, name predates the feature but kept rather than churned) lets a credit card route earned cashback straight into another account instead of sitting unredeemed. In `add_transaction()`, an investment-subtype target gets the same balance+contributions treatment `add_investment_contribution()` uses (inlined to stay in one atomic transaction) with `investment_contributions` logged; any other target (in practice, the Round-Up Jar) gets a plain balance credit, since a spare-change pot has no cost-basis concept. Configured per-card via `AccountsTab`'s "Set Cashback Destination" button. `cashback_monthly_cap` (0 = no cap) is enforced in both `add_transaction` and `update_transaction` — the latter must exclude the transaction's own pre-edit cashback from the "already earned this month" baseline when the edit stays within the same account+month, since the old row hasn't been replaced yet at that point. `update_transaction`'s optional `cashback` param lets a value be corrected by hand; given explicitly it's used as-is (not re-clamped against the cap), omitted the normal auto-calc runs.
- **Category ordering**: `categories.sort_order` (not alphabetical) — `Database.move_category(category_id, direction)` swaps it with the same-kind neighbor immediately above/below, a no-op at either end and never crossing into a different kind. `categories.csv` export/import is unaffected; reordering is GUI-only (Up/Down buttons in `BudgetsTab`).

### Known stale artifact
`Profiles/profiles.json` still exists on disk but is no longer read — `profiles.py`'s own docstring says there's deliberately no central registry anymore; `list_profiles()` scans `Profiles/*.db` directly.

### Phone-entry bridge (`inbox_sync.py` / `sync_inbox.py`)
Same phone-inbox pattern as Trip Budget Tracker (below), adapted to write into THE LEDGER's SQLite database instead of a CSV log — added as the first piece of a longer-term plan to make THE LEDGER a general-purpose lifetime budget tracker, superseding Trip Budget Tracker's Excel-only approach for that goal (Trip Budget Tracker itself is unaffected).

- **`build_inbox_workbook(db, path)`** — generates `Inbox.xlsx`: a `Transactions` table (`Date, Account, Category, Payee, Amount, Currency, Note`) plus `Accounts`/`Categories` reference sheets exported live from the profile's database, used as dropdown sources. Regenerate with `--build` whenever accounts/categories change.
- **`sync_inbox(excel_path, db, backups_dir, now=None)`** — reads the inbox, resolves `Account`/`Category` names to internal IDs (raising a clear `ValueError` naming the bad value on a mismatch), backs up exactly what it read to `--backups-dir` (default `Profiles/inbox_backups/`), calls `Database.add_transaction()` per row (reuses THE LEDGER's own balance-effect/round-up logic), then clears the sheet. Same safety philosophy as Trip Budget Tracker: backup-before-clear, no automatic dedup, validate-before-mutate.
- **Currency exchanges**: a `Category` of `"Currency Exchange"` marks a row as one leg of an exchange rather than a normal transaction. `sync_inbox()` groups these by `Date`, requires exactly 2 rows per date (one negative, one positive), and calls `transfer_between_accounts(..., to_amount=...)` instead of `add_transaction()`. An unpaired or malformed exchange row raises a `ValueError` naming the date.
- **`sync_inbox.py`** (CLI) — `--profile <slug>` targets a specific profile; prompts via `getpass` and unlocks it (same as the GUI) if password-locked.
- **Deployed**: `Inbox.xlsx` is generated for the real `matt_loaded` profile at `C:\Users\mateu\OneDrive\Budget Tracker\Inbox.xlsx` (the personal OneDrive root, not either Swansea University org one). Loading entries back in is `sync_inbox.py --profile matt_loaded --excel "<path>"` (no `--build`).
- **Not yet done**: no combined single-command version yet (the `dashboard.py` equivalent for this — sync + open the app in one step).

### Scrollable tabs
Every tab (`ScrollableTab` base class, `budget_app.py`) scrolls cleanly: a tab's `self` is embedded into a `Canvas` via `create_window` instead of being gridded directly into the page container, so every `_build()` method keeps using `self` as its widget parent unchanged — only `grid()`/`tkraise()` are overridden to act on the canvas+scrollbar wrapper. The scrollbar auto-hides when a page's content fits the viewport and shows when it doesn't (`_update_scrollbar_visibility`, re-measured on every `<Configure>`). Every `Treeview` across the app has its own scrollbar too. Hovering a Treeview/Text widget scrolls that widget, not the outer page — the outer wheel handler explicitly skips those widget types, since Tk otherwise invokes both the widget's own class-level scroll binding and the outer canvas's at once.

### Investments tab — capital gains (`InvestmentsTab`, `TaxTab`)
`security_lots` table (account_id, security, date, action buy/sell, quantity, price, fees, realized_gain) tracks individual buy/sell transactions per security, separate from the account-level `investment_contributions`/`investment_valuations` tables (cash-in / mark-to-market, unaffected). `add_security_transaction()` and the capital-gains methods implement **plain UK Section 104 average-cost pooling only** — every buy/sell of a security within one account pools into a single running average cost via `_recompute_realized_gains_nocommit()`, which replays the full history in date order on every insert. **HMRC's same-day and 30-day "bed and breakfast" matching rules are NOT implemented** — both must apply before pooling for a fully correct UK CGT figure; flagged in the Tax tab's own UI copy too.

`TaxTab`: net realized gain for the current UK tax year (6 Apr-5 Apr, `uk_tax_year_start()`) vs. a **user-editable** CGT annual exempt amount (`cgt_annual_exempt_amount` setting, defaults to 3000 but not guaranteed current — HMRC changes this figure). Explicit disclaimer that this isn't tax advice. Investments/Tax can be hidden from the sidebar via Settings → Customize Navigation without losing any data — see the Accounts/Net Worth split below for why nothing here was removed even though a future separate "Markets Hub" dashboard is meant to eventually supersede it.

### Other budgeting apps — feature gaps considered
Looked at YNAB, Monarch Money, Copilot, Empower, Kubera. Explicitly **not pursued**: bank/account auto-sync, credit score monitoring, bill negotiation — all three need paid third-party APIs, incompatible with "local, stdlib-only, nothing leaves the machine" being a deliberate design principle, not an oversight. (Manual bank-statement CSV import, unlike live sync, needs no API and *is* built.) Not built: investment fee/expense-ratio impact analysis (Empower's standout feature); a shared/household view across profiles (Monarch's differentiator — profiles here are deliberately fully separate).

### Grouped/collapsible sidebar + hideable tabs
`NAV_GROUPS`/hidden-tab mechanism described under Architecture above. The underlying logic (`get_hidden_nav_tabs`, `set_hidden_nav_tabs`, `visible_nav_groups`) is factored into three pure functions specifically so they're unit-testable without Tkinter (`tests/test_budget_app.py`) — a narrow, deliberate exception to "GUI code gets headless smoke tests, not pytest," not a reversal of that convention.

### Per-profile folders + two-way editable CSV sync
Each profile lives in its own subfolder, `Profiles/<slug>/profile.db`, so its editable CSV exports (below) can sit next to its database. `profiles._migrate_flat_profiles()` runs at the top of every `list_profiles()` call and transparently moves any old flat `.db`/`.db.locked` file into the new layout. `delete_profile()` removes the whole subfolder.

Four CSV files per profile — `transactions.csv`, `accounts.csv`, `categories.csv`, `investments.csv` — for bulk editing outside the GUI and backfilling historical data. Each has an `id` column: blank = new row, an edited existing id = an edit, an id missing from the file = a deletion. Two explicit buttons in Settings' "Data Files" card — nothing syncs automatically:
- **`refresh_profile_csvs(db, profile_dir)`** — regenerates all 4 files from current data (read-only).
- **`apply_profile_csvs(db, profile_dir, db_path)`** — backs up `profile.db` first, then applies files in a fixed order (accounts/categories before transactions/investments, so a same-pass reference by name already exists when needed), returns one combined `{"added", "edited", "deleted", "skipped"}` report.

Per-file apply functions route every change through the same methods the GUI itself uses — never raw SQL. Transfer legs, reconciled transactions, and split transactions are exported for visibility but protected: an edit to one is skipped and reported, and one is never deleted just because it's missing from the file. `accounts.csv`/`categories.csv` support add+edit only (both referenced by id elsewhere, no clean delete-by-omission); `investments.csv` supports full add/edit/delete.

**Known-fixed footgun**: in `apply_transactions_csv`/`apply_investments_csv`, an id must be resolved and marked "seen" *before* any other field validation runs on that row — otherwise a mere typo on an existing row's edit (e.g. an unknown account name) makes the row look intentionally removed from the file, and the cleanup pass silently deletes it. Caught by TDD before ever running against real data; if adding a new apply-from-CSV function, preserve this ordering.

`Profiles_backup_20260812_172011/` and a same-day post-restore backup still sit at the top of `ledger/` from when this feature was built — safe to delete once trusted, kept for now just in case.

### Statement loading: "Matt_loaded" profile (2026-08-12)
A one-off historical data load, not a repo feature — real derived data worth knowing about. Statements from `statements/` (Barclays, Lloyds, one Trading 212 PDF, one Revolut CSV) were parsed into profile `Matt_loaded`: 5 accounts, 670 transactions, 243 auto-categorized by merchant. Every source was validated against its own statement's stated totals before being committed. Three things to know if you open this profile:
- **"Trading 212 Card"**'s negative balance is not real money owed — the card uses just-in-time funding from an untracked Invest wallet, so only purchases are modeled, no top-ups; the figure is cumulative net card spend, not a real balance.
- **"Own Account (Untracked)"** is a placeholder for self-transfers whose real destination (mostly Trading 212 sub-accounts) wasn't distinguishable from the statements provided — excluded from spend/income analytics like any transfer.
- **PLN and CAD FX rates are rough approximations**, not real historical per-transaction rates — worth updating in Settings → FX Rates.

### Feature rounds — what exists and how it works

Everything below was built test-first (`finance_core.py` changes) with headless smoke-script verification for GUI wiring (no screenshot tooling for native Tkinter in this environment — hands-on manual click-through has not been done for any round). Grouped by mechanism, not chronologically; dig into git history for the build-by-build story if it's ever needed.

**Transactions & categories**
- `categories.kind` has four values: `need`/`want`/`saving`/`income`. Income is pure labeling — no budget bar, no over/under framing (`BudgetsTab`'s Income card just shows the month's actual total). `finance_core.income_by_category()`.
- `delete_category(category_id)` is blocked (`ValueError` naming the table+count) if still referenced by `transactions`, `transaction_splits`, or `recurring` (does *not* check `import_staging` — deleting a category referenced by an uncommitted staged CSV import raises an unhandled but harmless `IntegrityError` on Commit).
- `TransactionsTab`'s Add form's Category dropdown filters to `kind='income'` categories when the typed amount is positive, need/want/saving otherwise; a selection that no longer matches on a sign flip is cleared, not silently kept. Shows every category while the amount is blank/unparseable.
- Client-side filter toolbar (account/category/currency/date-range/amount-range) against the same transaction list the search box already filters — note `list_transactions()`'s default 500-row cap applies to what the filters see too.
- **Split transactions**: `transaction_splits(id, transaction_id, category_id, amount, note)`, reporting-only — the parent row still moves the full amount for balance/roundup/cashback; splits only change budgeting attribution. `set_transaction_splits(tx_id, splits)` validates amounts sum to the parent's (raises otherwise) and replaces atomically; empty list un-splits. `_category_spend_entries()` is the shared split-aware helper both `category_budget_status()` and `spend_by_kind()` use.
- **Tags**: `tags`/`transaction_tags` junction table, cross-cutting labels separate from category. `set_transaction_tags(tx_id, tag_names)` creates unknown tags on the fly. Search includes tags.
- **Reimbursement/IOU tracking**: `reimbursements(id, transaction_id, owed_by, amount, status, settled_date, note)` — `add_reimbursement()`/`settle_reimbursement()`/`list_outstanding_reimbursements()`.
- **CSV import** (`csv_import_preview`/`csv_import_staged_rows`/`csv_import_commit`/`csv_import_discard`, staged-preview-commit pipeline): a `likely_duplicate` column set during preview by matching `(account_id, date, amount)` against existing transactions, pre-selected for exclusion — matching this repo's "no automatic dedup" philosophy, `csv_import_commit()` never silently drops a row; skipping only happens via the explicit (editable) `skip_row_ids` the UI passes.
- **"once" frequency** for a known one-off transaction (e.g. an insurance renewal): reuses the `recurring` mechanism rather than a new subsystem — `generate_due_recurring()` posts it like any due item, then deactivates it instead of advancing. Gets Dashboard "upcoming" visibility (`upcoming_bills()`) and Recurring-tab list management for free.
- **Custom recurring intervals**: `recurring.custom_interval_months` posts every N months (e.g. rent 3x/year = every 4 months) instead of only weekly/monthly/yearly.

**Budgeting & planning**
- **Run-rate projection**: `budget_run_rate(db, year, month, today=None)` projects each budgeted category's month-end spend from spend-so-far ÷ days-elapsed × days-in-period. Shown per-category in `BudgetsTab` and as one sorted worst-first list in the Forecast tab.
- **Budget threshold alerts**: `categories_over_threshold()`, default threshold from `budget_alert_threshold_pct` setting (default 80).
- **Category reordering**: see Key Mechanisms above.
- **Forecast tab** (nav key `"forecast"`, Daily group, after Insights — Insights looks back, Forecast looks forward): the multi-month income/expense trend chart; the Run-Rate Projection list; the actual-vs-budgeted donuts (two `charts.draw_donut_chart` calls, per-category actual spend vs. budgeted allocation — a `CATEGORY_CHART_COLORS` palette is cycled through since the theme only defines 4 semantic colors); a **What If…** tool (`whatif_category_adjustment(db, year, month, category_kind, delta_amount)`, purely computational, never writes to the database — projects the savings-rate effect of spending more/less in a category type, correctly moving the explicit savings bucket too when the adjusted kind is `'saving'`); and a **goal tracker** (`goal_projection(db, target_amount, target_date, today=None)`, target stored as two plain settings keys — compares the last 6 months' average income-minus-expenses against the monthly pace needed to hit a net-worth target by a date).
- **Detected subscriptions**: `detect_recurring_candidates(db, min_occurrences=3, interval_tolerance_days=6)` scans actual transaction history (not the curated `recurring` table) for regularly-spaced payees, flags a price change between the two most recent occurrences, skips payees already in `recurring` or ignored. A genuinely separate mechanism from Recurring's own date-rollforward posting. "Add to Recurring" pre-fills the Add form rather than saving directly.
- **Ignored subscriptions**: soft-delete (`ignored_subscriptions.deleted_at`, migration-guarded) rather than a hard `DELETE` — an ignored payee can resurface as a candidate again once removed, and a removal itself is recoverable via `restore_ignored_subscription()` from the "Recently Deleted" section of its own management window (opened from Settings), with a confirmation prompt before deleting. `add_ignored_subscription()` revives a soft-deleted row on re-ignore rather than no-op'ing.

**Accounts & net worth**
- `AccountsTab` (nav key `"accounts"`) owns account management: Add/Edit/Delete/Transfer/Reconcile/Ledger/Statement-export, the Transfers list (`list_transfers()`), and Credit Cards — Utilization (due day, cashback rate/cap, cashback destination). `NetWorthTab` owns aggregate reporting only: net worth hero + snapshot button, FI progress ring, Investments summary, Net Worth by Type + Net Worth Over Time charts, Investment Growth Projection. Split out because the two concerns had grown into one ~825-line tab.
- **Edit Account dialog** covers name/currency/balance/liquid/credit limit always, plus cashback rate/cap/due day (credit cards) or expected return/monthly contribution/volatility (investments) conditional on subtype — everything *except* `kind` (asset vs. liability, excluded because it drives balance-sign math elsewhere in a way that isn't safe to blind-edit) and `subtype` (excluded because changing it would shift which of these fields even apply). Directly sets values with no transaction recorded — for backfilling a starting balance, distinct from "Reconcile…" which posts an adjustment transaction.
- Account "Type" display in the Accounts list is keyed by `(subtype, kind)` (`ACCOUNT_TYPE_BY_SUBTYPE_KIND`), not `subtype` alone — "Other Asset" and "Other Liability" share `subtype="other"` and would otherwise collide.
- Multi-select delete on the Transfers list (`delete_selected_transfer` loops the full Treeview selection, matching the pattern other `delete_selected` methods use).

**Insights**
- `InsightsTab`: top payees this month (`top_payees()`, via `charts.draw_bar_chart` reused as a single-series ranking) and a spending heatmap by day-of-month (`daily_spend_totals()` + `charts.draw_calendar_heatmap()`, a from-scratch calendar-grid chart).
- Trend range selector (6/12/24/36 months) on the Dashboard's income-vs-expenses chart, backed by `monthly_history(n_months=...)`; month labels switch to `"%b '%y"` once the range exceeds 12 months (bare `"%b"` collides across years).
- `category_anomalies()`: flags a transaction well outside its own category's rolling average via a plain z-score (>=2.0 by default), skipping categories with under 4 data points as too noisy to judge.

**Statement/report export**
- `export_transactions_csv_full` (account/transfer/reconciled columns) — "Export Full CSV…" in the Transactions toolbar.
- `export_account_statement_csv(db, account_id, path)` wraps `account_ledger()` into a single-account, newest-first CSV — "Export Statement…" in `AccountsTab`, useful as lightweight proof-of-funds documentation.
- PDF export was not built — would mean a third-party dependency, breaking the stdlib-only constraint (same reasoning as Investments' CSV-only import).

**Known, deliberately deferred minor gaps** (none block use): `add_ignored_subscription` dedupes case-insensitively but not whitespace-insensitively; `income_by_category` doesn't account for split transactions or net off a negative amount in an income category; `clear_filters()` on Transactions fires several redundant `refresh()` passes; the Budgets tab's multi-column layout has no horizontal scroll on narrow windows.

**Process lessons worth knowing if reusing these patterns**:
- Subagents spawned via the Agent tool are pinned to the *parent* session's worktree regardless of a "Work from: <dir>" instruction in the prompt — that's just text, not a sandbox boundary. Use the Agent tool's own `isolation: "worktree"` option for genuine parallel-worktree isolation instead of manually pre-creating worktrees.
- A `ttk.Entry`/`ttk.Combobox`'s `.get()` can return a stale/empty value in a headless smoke script if its `textvariable` was set programmatically before the widget was ever mapped and no event loop has run — the underlying Tcl variable is correct (verify via `root.getvar(widget.cget('textvariable'))`, or just read the `tk.StringVar` directly). Test-harness-only artifact, not a production bug; real interaction through a live `mainloop()` doesn't hit it.

---

## Trip Budget Tracker

### Commands
All commands below assume `cd trip-budget` first (or prefix paths with `trip-budget/`).
- Install deps: `.venv/Scripts/python.exe -m pip install -r requirements.txt` (pandas, openpyxl, matplotlib, plotly, pytest)
- Run all tests: `.venv/Scripts/python.exe -m pytest`
- Run a single test: `.venv/Scripts/python.exe -m pytest tests/test_finance.py::test_budget_vs_actual_flags_overspend_and_computes_remaining`
- Daily use — load new entries, report, clear the sheet, all in one step: `.venv/Scripts/python.exe dashboard.py`
- Just sync phone-entered transactions into the persistent log (no report): `.venv/Scripts/python.exe sync_transactions.py`
- Just regenerate the report + charts (no sync): `.venv/Scripts/python.exe analyze.py`
- Regenerate a fresh workbook: `.venv/Scripts/python.exe build_template.py --out "Data.xlsx"`

All scripts accept `--excel` / `--log` / `--charts-dir` / `--backups-dir` overrides; defaults assume everything sits in `trip-budget/` alongside `Data.xlsx`.

### Architecture
Built test-first. The whole design turns on one idea: `Data.xlsx`'s `Transactions` sheet is a **transient inbox**, not the permanent record.

```
[Phone/laptop] --Excel entry--> Data.xlsx Transactions table (cleared after each sync)
                                        |
                              sync_transactions.py: read -> backup -> append -> clear
                                        |
                              data/transactions_log.csv (permanent, append-only)
                                        |
                              analyze.py: reads log + Accounts/Categories sheets -> report + charts
```

- **`finance.py`** — pure calculation functions only, no I/O: `parse_label` (splits a `"Category (Currency)"` dropdown label back apart), `load_transactions_log`, `budget_vs_actual`, `account_running_balance`, `effective_exchange_rate` (aggregates both currency legs of every exchange independently — deliberately never pairs individual rows), `sankey_flows`, `is_below_threshold`.
- **`build_template.py`** — generates the workbook: `Accounts`/`Categories`/`Transactions` sheets, the `Categories.Label` helper column, and dropdown validations plus one example row carrying the `XLOOKUP` currency auto-fill formula (Excel's table calculated-column auto-fill needs at least one existing row with the formula to propagate it to new rows).
- **`sync_transactions.py`** — the only script allowed to write to the Excel file. Deliberately has **no automatic dedup**: a content-based fingerprint would silently drop legitimate same-day duplicate transactions (e.g. two identical coffees); safety instead comes from the backup-before-clear ordering, recoverable by hand from `data/backups/`.
- **`analyze.py`** — `build_report()` wires every `finance.py` function together into one dict; `print_report()`/`draw_bar_charts()`/`draw_sankey()` are thin presentation layers over it.
- **`dashboard.py`** — daily-use entry point: `sync_transactions.sync()` then `analyze.py`'s report/chart functions against the freshly-updated log, so one command loads entries, reports, and clears the sheet.
- Reference data (`Accounts`/`Categories` sheets) is read straight from the Excel file on every `analyze.py` run — only `Transactions` is ever treated as transient/clearable.

Full spec and design rationale live in `budget-tracker-plan.md`; day-to-day usage instructions are in `TRIP_BUDGET_README.md`.

### Current state
Not yet in real use — `Data.xlsx` still holds `build_template.py`'s default placeholder data; no sync has ever run. All 37 tests pass.

**Blocker: the phone-sync workflow won't work from this location yet.** The repo lives at `C:\Users\mateu\PycharmProjects\Budget_Tracker`, not under a OneDrive-synced path. Until `Data.xlsx` (or the whole project) is moved into or symlinked from a OneDrive tree, editing it on a phone won't reach the laptop copy. Owner is handling this separately — the repo location itself is staying put. No validation step has confirmed the phone/laptop round-trip actually works yet.

### Known gaps
- **Excel file locking**: `sync_transactions.py`/`dashboard.py` open `Data.xlsx` with `openpyxl.load_workbook`/`wb.save` — if the file is open in Excel (desktop or, per OneDrive co-authoring, sometimes mobile) at sync time, the save can fail or conflict. Not handled or documented as a caution.
- **Hardcoded to exactly two currencies (GBP/CAD)** in a few places — `effective_exchange_rate()` and the Sankey flow builder assume exactly one GBP-side and one CAD-side leg per exchange. Generalizing to arbitrary currencies/accounts (needed for reuse as a general ongoing budget beyond this one trip) is a real design change, not started.
- Everything under "Stretch" in `budget-tracker-plan.md` is still unbuilt: manual balance check-ins/mismatch flagging, run-rate overspend projection, market-rate FX comparison, multi-month trends, bank CSV import, recurring-payment detection.
- No cost-basis tracking (FIFO or weighted-average) for exchanged currency, and no average/typical-price tracking per item or category — both requested, not yet designed.

Note: `.gitignore` at the repo root now excludes `trip-budget/data/` and `Data.xlsx` (real data) — this project is covered by the same git repo as THE LEDGER, initialized 2026-08-12.
