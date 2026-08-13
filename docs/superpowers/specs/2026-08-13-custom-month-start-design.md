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
  `month_start_day=25` spans 25 Aug–24 Sep. This matches the user's own
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
something that does. **Only `transactions_in_month` and one function that
independently assumes calendar-month day-counts (`budget_run_rate`) need
real changes** — a second function with the same day-count dependency,
`daily_spend_totals`, is deliberately left alone (see below):

1. **`Database.transactions_in_month(year, month, include_transfers=False)`**
   — currently does `WHERE t.date LIKE 'YYYY-MM%'`. Rewritten to call
   `month_bounds(self, year, month)` and query `WHERE t.date >= ? AND
   t.date <= ?` instead. Every function built on top of this (the ~15
   listed above) is fixed automatically, with no changes of its own.

2. **`daily_spend_totals(db, year, month)`** is deliberately **NOT**
   changed, and this needs to be explicit rather than assumed: its output
   feeds `charts.draw_calendar_heatmap`, which renders a literal
   weekday-aligned calendar grid via
   `calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)` for
   one specific real calendar month — that's the entire point of the
   chart (spotting weekday spending patterns, e.g. "I always overspend on
   Fridays"). A custom reporting period spanning two calendar months has
   no sensible weekday-grid rendering, so rebucketing this function would
   either break the chart or produce a visualization that no longer means
   what it claims to. **Scope decision: the Insights tab's spending
   heatmap always shows a literal calendar month's pattern, independent of
   `month_start_day`** — a deliberate, documented exception, not an
   oversight. Everything else in the app (Dashboard, Budgets, every other
   Insights card) respects the custom reporting period; only this one
   chart stays calendar-month-shaped because its visual metaphor requires
   it.

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
  shows the real date range instead (e.g. "25 Aug – 24 Sep 2026" for the
  month labeled August), per the user's own choice — unambiguous about
  what period is actually being viewed, since "August 2026" would be
  actively misleading once the period doesn't start August 1st.
- **`App.prev_month()` / `next_month()`**: unchanged — they already just
  decrement/increment the `(year, month)` index, which continues to work
  correctly since `month_bounds` handles the real-date translation.

## Testing approach

Test-first against `finance_core.py`. Critical cases for `month_bounds`:
default (`month_start_day=1`) reproduces exact current calendar-month
bounds; a mid-month start day (e.g. 25) produces the correct 25th-to-24th
range; year rollover (e.g. `month_start_day=25`, month=12 spans
25 Dec–24 Jan of the following year). `month_start_day` is itself clamped to
`1..28` before any date math runs — same convention this codebase already
uses for credit card `due_day`, chosen specifically so no day-of-month
edge case (a month shorter than the configured start day) can ever arise:
every month has at least 28 days. A test should confirm an out-of-range
stored value (e.g. a hand-edited `31`) is defensively clamped to `28`
rather than trusted raw. For `transactions_in_month` and `budget_run_rate`
(the two functions this plan actually changes — `daily_spend_totals` is
out of scope, see above): one test each confirming default behavior is
unchanged (regression protection — these functions currently have partial
or no test coverage, so establishing a baseline before changing their
internals matters), plus one test each with a custom `month_start_day`
confirming the new range is respected. For `custom_month_for_date`:
default behavior unchanged; a date before vs. on-or-after the start day
resolves to the correct bucket; year-rollover at January.

GUI wiring (`App` init/`goto_today`/month label, `SettingsTab` field)
verified with a headless smoke script per this project's established
convention (construct `App` directly against a sandboxed `profiles.APP_DIR`,
drive the tab in code, assert on state) — no interactive/visual check,
since there's no screenshot tooling for native Tkinter in this
environment; worth clicking through by hand afterward.
