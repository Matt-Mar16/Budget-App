# THE LEDGER — "Ultimate" Dashboard

Date: 2026-08-14
Status: Approved, ready for implementation plan
Scope: `ledger/src/finance_core.py`, `ledger/budget_app.py`

## Context

Follows directly on the earlier "default colors + colorful Dashboard" round
(see CLAUDE.md's "Default colors & Dashboard colorization"). That round made
the existing Dashboard visually richer; this round makes it functionally
richer — surfacing things the user currently has to leave the Dashboard for,
and letting the layout be customized rather than fixed.

Today's `DashboardTab` (`budget_app.py:826`) has, in fixed order: a
safe-to-spend hero, a 6-cell metrics grid, a donut (need/want/saving split)
and a trend chart side-by-side, and a Flags & Nudges text panel. Everything
else — net worth, goal tracking, run-rate projections, top payees, spending
heatmap — deliberately stays on its own tab (Net Worth, Forecast, Insights)
and is **out of scope** here; the user's stated priority was actionable
items and quick actions, not pulling net worth/FI data onto this screen.

## Design

### 1. `Database.post_recurring_item` — the one new capability

Every other piece of this feature reuses existing `finance_core`/`Database`
methods as-is. This is the sole exception: there is currently no way to post
a *single* recurring item on demand. `Database.generate_due_recurring(today)`
(`src/finance_core.py:1409`) loops every active recurring item and posts
each one only while its `next_date <= today`, advancing `next_date` each
time, capped at 36 iterations per item — but it always processes the full
set, gated on due-ness, with no `recurring_id` parameter.

The Needs Attention card (below) needs a "Post Now" button per upcoming
bill — including bills that are upcoming but not literally due yet (`upcoming_bills()`
returns anything due within 14 days, not just `next_date <= today`). This is
a deliberately different semantic from the auto-scan: an explicit,
user-initiated "record this one now," not a due-date gate.

`generate_due_recurring`'s per-item posting body (apply balance/round-up
effects via `_apply_balance_effect_nocommit`/`_apply_roundup_nocommit`,
insert the transaction, advance `next_date` via `_advance_date`) gets
extracted into a shared internal helper, `_post_recurring_once_nocommit(item,
post_date)`, called from both:

- `generate_due_recurring(today)` — unchanged behavior, still loops
  `while next_date <= today`, calling the helper each iteration.
- **New:** `post_recurring_item(recurring_id, today=None)` — looks up the
  one recurring item (raises `ValueError` if not found or not active),
  calls the helper exactly once using the item's own `next_date` as the
  transaction date (matching `generate_due_recurring`'s existing choice —
  the transaction is dated to when it was scheduled, not to whenever the
  button happened to be clicked), and returns the new transaction id.

### 2. Needs Attention card (new)

New card in `DashboardTab`, placed between the charts section and Flags &
Nudges. Combines three existing data sources — no new "combiner" function in
`finance_core`; `DashboardTab.refresh()` calls each directly and renders
three short sub-lists, the same way it already assembles Flags & Nudges from
several independent sources:

- **Bills due soon** — `upcoming_bills(db, within_days=14, today=...)`
  (already used for the existing Flags "bill" nudge). Each row gets a
  **Post Now** button calling the new `post_recurring_item(r["id"])`, then
  `self.app.refresh_all()`.
- **Outstanding reimbursements** — `db.list_outstanding_reimbursements()`.
  Each row gets a **Mark Settled** button calling `db.settle_reimbursement(r["id"])`
  then `refresh_all()` — identical to `TransactionsTab`'s existing
  "Outstanding Reimbursements" card (`budget_app.py:1429-1451`), just
  duplicated onto the Dashboard for visibility (that card stays where it
  is; this isn't a move, it's a second surface for the same data/actions).
- **Detected subscription candidates** — `detect_recurring_candidates(db)`.
  Each row gets **Add to Recurring** (navigates to the Recurring tab and
  calls its existing `_prefill_from_candidate(c)`) and **Ignore**
  (`db.add_ignored_subscription(cand["payee"])` then `refresh_all()`) —
  same actions `RecurringTab`'s "Detected Subscriptions" card already
  offers (`budget_app.py:2227-2247`).

Each of the three sub-lists is capped at 4 items (matching the existing
`bills[:4]` cap already used in Flags & Nudges; `RecurringTab`'s own
"Detected Subscriptions" card caps at 8, but the Dashboard's version is
denser — showing three lists in one card — so 4 is used consistently across
all three here) and shows a "Nothing here" label when empty, matching the
existing `TransactionsTab` reimbursements empty-state pattern. If all three
sub-lists are empty, the whole card shows one "You're all caught up" line
rather than three separate empty-states.

### 3. Quick Actions row (new)

A small button row near the top of the Dashboard (below the hero, above the
metrics grid, itself part of the reorderable layout — see below):
**Add Transaction** and **Transfer Between Accounts**.

These two are not symmetric today. **Transfer Between Accounts** is already
a standalone `Toplevel` dialog (`AccountsTab`, built at `budget_app.py:2743`,
triggered from a button at `budget_app.py:2538`) — the Dashboard's button
calls the same dialog-building method as-is, no changes needed.

**Add Transaction** is *not* a popup today — it's an inline form built
directly into `TransactionsTab` (`self.date_var`/`self.payee_var`/etc. are
the tab's own instance variables; `TransactionsTab.add_transaction()`,
`budget_app.py:1596`, reads them directly and validates/writes in one
method). To give the Dashboard a real quick-entry popup without duplicating
that validation logic, `TransactionsTab.add_transaction()`'s validate-and-write
body (date/amount parsing, category/account name resolution, the
`would_exceed_budget()` warning, the `db.add_transaction(...)` call) is
extracted into a shared module-level function, e.g.
`submit_new_transaction(app, date, payee, category_name, amount_raw, currency, note, account_name)`,
returning `(ok, error_message)`. `TransactionsTab.add_transaction()` becomes
a thin wrapper that reads its own StringVars and calls this function. A new
small `Toplevel` dialog (built the same way `make_scrollable_toplevel` builds
every other dialog in the app) collects the same fields and calls the same
shared function — one validation/write path, two entry points (the
Transactions tab's inline form, and the Dashboard's popup).

### 4. Customizable layout

Six reorderable/hideable sections, each a full-width stacked card in a
fixed key → label mapping:

```python
DASHBOARD_SECTIONS = [
    ("hero", "Safe to Spend"),
    ("metrics", "Key Metrics"),
    ("quick_actions", "Quick Actions"),
    ("charts", "Charts (Spend Split & Trend)"),
    ("needs_attention", "Needs Attention"),
    ("flags", "Flags & Nudges"),
]
```

`charts` stays as **one** section covering the existing donut+trend
side-by-side row — not split into two independently-movable cards. Splitting
them would mean abandoning today's side-by-side layout (the drag-reorder
helper only handles a single vertical stack of full-width rows), which is a
bigger visual change than the customization request asked for; the pair
moves and hides together instead.

**Storage** mirrors the existing `hidden_nav_tabs` setting
(`get_hidden_nav_tabs()`/`set_hidden_nav_tabs()`) but adds ordering: one new
JSON setting, `dashboard_layout`, holding an ordered list of
`{"key": ..., "visible": bool}`. New `Database` methods:

- `get_dashboard_layout()` — reads the setting; if unset, returns
  `DASHBOARD_SECTIONS`' keys in their default order, all visible. If set,
  reconciles against the current known keys: drops any saved key no longer
  in `DASHBOARD_SECTIONS` (e.g. a section removed in a future version),
  appends any known key missing from the saved list (e.g. a section added
  in a future version) as visible, at the end. This keeps old saved layouts
  forward-compatible with no migration needed, since it's a JSON setting
  blob, not a schema column.
- `set_dashboard_layout(layout)` — validates every entry has a known `key`
  and a boolean `visible`, writes the JSON.

**Reordering** reuses `enable_drag_reorder()` (`budget_app.py`, module-level,
already used by `BudgetsTab`'s category cards) exactly as-is: each visible
section's container frame gets a small grip handle; on drop,
`on_reorder(keys_in_final_order)` merges the new order for visible keys with
the existing hidden keys (appended at the end, since hidden sections aren't
in the draggable list) and calls `set_dashboard_layout()`.

**Visibility** is toggled from a new "Customize Dashboard" card in
`SettingsTab`'s existing Advanced section, mirroring the existing "Customize
Navigation" card (`hidden_nav_tabs`) one-for-one: one checkbox per section
name, toggling calls `set_dashboard_layout()` (flipping that key's
`visible`, keeping order otherwise unchanged) then `self.app.refresh_all()`.
No section is protected/un-hideable (unlike `PROTECTED_NAV_KEYS` for nav
tabs) — hiding every Dashboard section just leaves the page blank, which
isn't a navigational dead-end the way hiding Settings/Dashboard from the nav
would be, so no guard is needed.

`DashboardTab._build()` builds each section's widget once as today, but
instead of `pack()`-ing them directly in fixed order, wraps each in a
container frame stored in `self.section_frames = {key: frame}`. A new
`DashboardTab._apply_layout()` reads `get_dashboard_layout()` and
packs/`pack_forget()`s each container in the saved order/visibility — called
once at the end of `_build()`, and again at the top of every `refresh()` (so
a layout change made from Settings while looking at another tab is picked up
next time Dashboard is shown, consistent with how `refresh_all()` already
refreshes every tab's data regardless of which is currently visible).

## Explicitly out of scope

- Net worth, FI progress, account balances on the Dashboard — user's stated
  priority was actionable items and quick actions, not big-picture data
  already covered by the Net Worth tab.
- A compact/inline Add Transaction or Transfer form embedded in the
  Dashboard — reusing the existing dialogs was the explicit choice, to avoid
  a second form implementation to keep in sync with the real one.
- Splitting the donut/trend charts into independently-reorderable cards —
  see "Customizable layout" above; the user chose to keep them paired.
- Per-cell reordering within the 6-cell metrics grid — the grid moves as one
  `metrics` section; individual metric cards are not independently
  reorderable.
- A "mark bill paid" action that *doesn't* post a transaction (e.g. a
  dismiss-only checkbox) — not requested; "Post Now" always posts a real
  transaction via the same mechanism `generate_due_recurring` uses.

## Testing approach

Test-first against `finance_core.py`:

- `post_recurring_item`: posts the item exactly once regardless of whether
  `next_date <= today` (the "not due yet" case that motivates this method);
  applies the same balance/round-up effects as `generate_due_recurring`
  (verify via an `_apply_balance_effect_nocommit` scenario already covered
  in existing recurring tests, adapted); advances `next_date` by one
  interval, matching `_advance_date`'s existing frequency handling
  (weekly/monthly/yearly/custom-interval/once); raises `ValueError` for an
  unknown or inactive `recurring_id`. A regression test confirms
  `generate_due_recurring`'s existing behavior/test suite is unaffected by
  the extraction into `_post_recurring_once_nocommit`.
- `get_dashboard_layout`/`set_dashboard_layout`: default (nothing saved)
  returns `DASHBOARD_SECTIONS`' keys in order, all visible; round-trip
  (`set` then `get` returns what was set); an unknown saved key is dropped;
  a known key missing from a saved layout is appended, visible; `set_dashboard_layout`
  rejects a payload with a missing/unknown key or non-boolean `visible`.

GUI wiring (Quick Actions buttons, Needs Attention rows/actions, drag-reorder
on Dashboard sections, the Customize Dashboard settings checkboxes) verified
with a headless smoke script per this project's established convention
(construct `App` directly against a sandboxed `profiles.APP_DIR`, drive the
tab in code, assert on state) — no interactive/visual check, since there's
no screenshot tooling for native Tkinter in this environment; worth clicking
through by hand afterward. The `submit_new_transaction()` extraction itself
is a plain function (no Tkinter dependency beyond reading already-parsed
values) and gets ordinary `pytest` coverage: valid input adds a transaction
and returns `(True, None)`; an invalid date/amount returns `(False,
<message>)` without touching the database; a regression test confirms
`TransactionsTab`'s inline Add form still behaves identically after being
rewired to call the extracted function (existing `test_budget_app.py`
coverage of the Add form, if any, must still pass unchanged).
