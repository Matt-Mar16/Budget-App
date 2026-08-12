# THE LEDGER — Quick Wins (Sub-project A)

Date: 2026-08-12
Status: Approved, ready for implementation plan
Scope: `ledger/` only (`budget_app.py` + `ledger/src/finance_core.py`)

## Context

This is sub-project A of a six-part feature list requested against THE LEDGER
(sub-projects B–F: reconciliation & balances tab, transfer tracking + Trading
212 sub-accounts, editable cashback rules, irregular recurring schedules,
custom month-start date — each to be brainstormed and built separately).
Sub-project A groups four independent, low-risk, additive features that don't
touch each other's code paths.

## A1 — Income category kind

**Problem:** `categories.kind` has `CHECK(kind IN ('need','want','saving'))`.
There is no way to create a category for salary/gifts/refunds/etc. Every
aggregation function that reads `kind` (`spend_by_kind`,
`_category_spend_entries`, `category_budget_status`) already skips
`amount >= 0` transactions before it ever looks at `kind`, so income
categories are inert for every existing budget calculation — this is purely
additive.

**Migration:** SQLite can't `ALTER` a `CHECK` constraint. Add a migration
function (same idiom as the existing `ALTER TABLE ... ADD COLUMN` guards in
`Database._migrate`/init): inspect `sqlite_master.sql` for the `categories`
table; if it doesn't contain `'income'`, rebuild the table (create
`categories_new` with the updated CHECK, copy all rows, drop old, rename),
inside the existing `with self.conn:` transaction pattern. Runs once per
database, no-ops forever after.

**`BudgetsTab` fix (required, not optional):** `refresh()` currently does
`groups = {"need": [], "want": [], "saving": []}` then
`groups[cat["kind"]].append(cat)` — an income category would raise
`KeyError` today. Add `"income"` as a fourth bucket. Per the "pure labeling"
decision: the Income card lists each income category's name and this
month's actual total (sum of positive transactions in that category) with
**no budget bar, no over/under framing** — just the figure. No change to
`category_budget_status`/`budget_run_rate` (they already only process
`monthly_budget`-having categories from spend, and income categories won't
usefully have one).

**Add Category form:** the kind `Combobox` gains `"income"` as a fourth
value alongside `need`/`want`/`saving`.

**No change needed:** `TransactionsTab`'s category dropdown, CSV
export/import (`export_categories_editable_csv`/`apply_categories_csv`),
and `RecurringTab`'s category dropdown already list `db.list_categories()`
unfiltered by kind — income categories show up there automatically.

## A2 — Delete category (blocked if in use)

**New method:** `Database.delete_category(category_id)`. Checks three
tables that reference `category_id` — `transactions`, `transaction_splits`,
`recurring` — via `COUNT(*)`. If the total is > 0, raises `ValueError`
naming the count and table breakdown (e.g. "12 transactions and 1 recurring
item use this category — recategorize them first"). If zero, deletes the
row. No cascade, no reassignment — matches the existing conservative
protection pattern used for reconciled transactions and transfer legs.

**UI:** a "Delete" button next to the existing "Set Budget" control on each
category row in `BudgetsTab`, calling the new method and showing the error
via `messagebox` if blocked.

## A3 — Transaction filters

**No new Database methods.** `TransactionsTab.refresh()` already filters
`db.list_transactions()` client-side against the free-text search box.
Extend the same loop with additional filter state, all applied in the same
pass:

- Account — `Combobox`, values from `list_accounts()` (same source as the
  existing "Paid from" dropdown), blank = all
- Category — `Combobox`, values from `list_categories()`, blank = all
- Date range — two `Entry` fields (from/to, `YYYY-MM-DD`), either may be
  blank
- Currency — `Combobox` populated from the distinct currencies seen in
  `list_transactions()`, blank = all
- Amount range — two `Entry` fields (min/max, compared against the
  transaction's raw `amount`, not the reporting-currency conversion, so it
  matches what's displayed), either may be blank

**UI:** a second toolbar row in `TransactionsTab` below the existing search
row, plus a "Clear Filters" button that resets all filter vars and calls
`refresh()`. Each filter var triggers `refresh()` on change via
`trace_add("write", ...)`, same pattern as the existing search box.

## A4 — Dismiss subscription suggestions

**New table:** `ignored_subscriptions(id INTEGER PRIMARY KEY, payee TEXT
NOT NULL, dismissed_date TEXT NOT NULL)`, with a case-insensitive uniqueness
guard enforced in `add_ignored_subscription` (check existing rows
case-insensitively before inserting, since SQLite `UNIQUE` is
case-sensitive by default and payee casing is inconsistent across sources).

**New methods:** `Database.add_ignored_subscription(payee, date=None)`,
`Database.remove_ignored_subscription(payee)` (un-ignore),
`Database.list_ignored_subscriptions()`.

**`detect_recurring_candidates` change:** add one more case-insensitive
exclusion check, alongside the existing "already tracked in `recurring`"
check it already performs — same shape, same place in the function.

**UI:**
- `RecurringTab`: an "Ignore" button next to the existing "Add to
  Recurring" button on each detected-candidate row, calling
  `add_ignored_subscription` then `refresh()`.
- `SettingsTab`: new "Ignored Subscriptions" card listing each dismissed
  payee with dismissed date and an "Un-ignore" button — same layout pattern
  as the existing "Customize Navigation" checklist card.

## Testing approach

Test-first against `finance_core.py` (new tests in
`tests/test_finance_core.py`) for: the categories-kind migration, the
income-card spend calculation, `delete_category` (blocked and successful
paths), `detect_recurring_candidates`'s new exclusion, and the three new
`ignored_subscriptions` methods. GUI wiring (`budget_app.py` changes)
verified with a headless smoke script per this project's established
pattern (construct `App` directly, drive the tab/dialog in code, assert on
state, mock `messagebox` where needed) — no interactive/visual check, since
there's no screenshot tooling for native Tkinter in this environment; worth
clicking through by hand afterward.

## Out of scope (deferred to later sub-projects)

Reconciliation/balances tab (B), transfer tracking + Trading 212
sub-accounts (C), editable cashback rate/cap (D), irregular recurring
schedules (E), custom month-start date (F).
