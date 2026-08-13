# THE LEDGER — Custom Month Start Date

Date: 2026-08-13
Status: Approved, ready for implementation plan
Scope: `ledger/src/finance_core.py`, `ledger/budget_app.py`

## Context

This is sub-project F of a six-part feature list requested against THE
LEDGER (sub-projects B–E — reconciliation & balances, transfers & Trading
212 sub-accounts, cashback rules, custom recurring schedules — are already
built and merged). F is the largest and most invasive: THE LEDGER currently
defines "month" as a plain calendar month everywhere it aggregates data for
reporting (Dashboard, Budgets, Insights). The user is paid on the 25th and
wants their budgeting "month" to run 25th–24th instead, matching when money
actually arrives.

## Design

### The core primitive

A new module-level helper, `finance_core.month_bounds(db, year, month) ->
(start_date_str, end_date_str)`, becomes the single source of truth for
what real calendar dates a reporting "month" spans:

- Reads a new `month_start_day` setting (`db.get_setting_int("month_start_day",
  1)`, clamped to 1–28, same pattern already used for `budget_alert_threshold_pct`
  and account `due_day`).
- When `month_start_day == 1` (the default — nobody has touched the
  setting): `start_date = date(year, month, 1)`, `end_date` = the last day
  of that calendar month. **Byte-for-byte identical to current behavior.**
  This is what makes the whole feature safe to ship — every existing
  profile, with no setting changed, sees zero behavioral difference.
- When `month_start_day > 1`: `start_date = date(year, month, month_start_day)`,
  `end_date = date(year, month, month_start_day) + 1 calendar month - 1 day`.
  A month is **labeled by the calendar month it starts in** — "August" with
  `month_start_day=25` spans 25 Jul–24 Aug. This matches the user's own
  framing ("I get paid on the 25th, so month should start on the 25th") —
  the month is named for when the money arrives, not when it's spent down.

A second small helper, `finance_core.custom_month_for_date(db, a_date) ->
(year, month)`, answers "which reporting-month bucket does this real date
fall into" — needed once, at app startup and on "Today", to resolve
"today" into the right (year, month) pair. With `month_start_day == 1` this
is trivially `(a_date.year, a_date.month)`. Otherwise: if `a_date.day >=
month_start_day`, the bucket is `(a_date.year, a_date.month)`; otherwise
it's the previous calendar month (wrapping year at January).

### Why this doesn't require touching ~19 call sites

Every reporting function that currently takes `(db, year, month)` —
`monthly_totals`, `savings_rate`, `emergency_fund_ratio`, `debt_to_income`,
`housing_ratio`, `safe_to_spend`, `monthly_history`, `top_payees`,
`spend_by_kind`, `income_by_category`, `lifestyle_inflation_flags`,
`idle_cash_nudge`, `category_budget_status`, `budget_run_rate`,
`categories_over_threshold`, and the `Database.transactions_in_month`
method itself — either calls `transactions_in_month` directly or calls
something that does. **Only `transactions_in_month` and the two functions
that independently assume calendar-month day-counts need real changes:**

1. **`Database.transactions_in_month(year, month, include_transfers=False)`**
   — currently does `WHERE t.date LIKE 'YYYY-MM%'`. Rewritten to call
   `month_bounds(self, year, month)` and query `WHERE t.date >= ? AND
   t.date <= ?` instead. Every function built on top of this (the ~15
   listed above) is fixed automatically, with no changes of its own.

2. **`daily_spend_totals(db, year, month)`** — currently does
   `calendar.monthrange(year, month)[1]` to get "how many days in this
   month" and buckets by literal `int(date[8:10])` (day-of-calendar-month).
   Rewritten to use `month_bounds` for the real start/end dates, and bucket
   by day-offset-from-`start_date` (1-indexed) instead of the literal
   calendar day-of-month — so the heatmap still has one column per day of
   the reporting period, correctly ordered, regardless of where in the
   calendar month it starts.

3. **`budget_run_rate(db, year, month, today=None)`** — same
   `calendar.monthrange` dependency, for computing "days elapsed / days in
   month" to project month-end spend. Same fix: `month_bounds`-derived
   start/end, with "days elapsed" computed as `(today - start_date).days +
   1` (clamped to the period) instead of `today.day`.

`monthly_history`'s existing backward-walk (stepping the `(year, month)`
index back one at a time to build a trend) needs no change — it's already
just decrementing an abstract `(year, month)` pair, and every `(year,
month)` pair now correctly resolves to real dates via `month_bounds`
inside `transactions_in_month`. Its own month-label generation (`"%b"`
formatting for chart axis labels) also needs no change, since it already
labels by the `(year, month)` index — which under the new scheme already
means "the month that starts in calendar month `month`."

### Explicitly out of scope

- **Recurring bill due-dates** (`generate_due_recurring`, `_advance_date`,
  `upcoming_bills`) are untouched — a bill due on a specific calendar date
  posts on that real date regardless of the reporting-month setting. This
  setting only changes how transactions are *grouped* for reporting, never
  when things actually happen.
- **UK tax year** (`uk_tax_year_start`, the Tax tab's CGT calculations) is
  a separate, HMRC-fixed 6 Apr–5 Apr concept, already independent of
  calendar months in this codebase. Not touched, not conflated with this
  setting.

### GUI changes (`ledger/budget_app.py`)

- **`SettingsTab`**: new "Month start day (1 = calendar month)" field,
  same layout/pattern as the existing `budget_alert_threshold_pct` field
  (label + `Entry` + save button in the existing Preferences-style card).
  Validated 1–28 on save (matching the existing `due_day` validation
  range used for credit card payment days).
- **`App.__init__`**: `self.view_year, self.view_month` initialization
  changes from `self.today.year, self.today.month` to
  `finance_core.custom_month_for_date(self.db, self.today)`.
- **`App.goto_today()`**: same change — resolves through
  `custom_month_for_date` instead of reading `self.today`'s raw calendar
  fields directly.
- **`App._update_month_label()`**: when `month_start_day == 1`, keeps the
  existing simple `"%B %Y"` label (e.g. "August 2026") — zero visual
  change for anyone not using the feature. When `month_start_day > 1`,
  shows the real date range instead (e.g. "25 Jul – 24 Aug 2026"), per the
  user's own choice — unambiguous about what period is actually being
  viewed, since "August 2026" would be actively misleading once the
  period doesn't start August 1st.
- **`App.prev_month()` / `next_month()`**: unchanged — they already just
  decrement/increment the `(year, month)` index, which continues to work
  correctly since `month_bounds` handles the real-date translation.

## Testing approach

Test-first against `finance_core.py`. Critical cases for `month_bounds`:
default (`month_start_day=1`) reproduces exact current calendar-month
bounds; a mid-month start day (e.g. 25) produces the correct 25th-to-24th
range; year rollover (e.g. `month_start_day=25`, month=1 spans
25 Dec (prior year)–24 Jan). Day-31 edge case, resolved explicitly here to
remove any ambiguity for the implementer: `start_date` for a given
`(year, month)` is `date(year, month, min(month_start_day,
_last_day_of_month(year, month).day))` — clamped into that calendar
month exactly like `_advance_date` already clamps recurring-item dates —
and `end_date` is one day before what the SAME clamping rule produces for
`(year, month+1)`. E.g. `month_start_day=31`, month=Feb (28 days):
`start_date = Feb 28`; the following month's clamped start (`Mar 31`)
minus one day gives `end_date = Mar 30`. For `transactions_in_month`,
`daily_spend_totals`, and `budget_run_rate`: one test each confirming
default behavior is unchanged (regression protection — these functions
currently have partial or no test coverage, so establishing a baseline
before changing their internals matters), plus one test each with a
custom `month_start_day` confirming the new range is respected. For
`custom_month_for_date`: default behavior unchanged; a date before vs.
on-or-after the start day resolves to the correct bucket; year-rollover
at January.

GUI wiring (`App` init/`goto_today`/month label, `SettingsTab` field)
verified with a headless smoke script per this project's established
convention (construct `App` directly against a sandboxed `profiles.APP_DIR`,
drive the tab in code, assert on state) — no interactive/visual check,
since there's no screenshot tooling for native Tkinter in this
environment; worth clicking through by hand afterward.
