# THE LEDGER — a budgeting app built from the research synthesis

A desktop budgeting app (Tkinter + SQLite, stdlib only — nothing to install,
no third-party packages, no network calls). Baseline currency is **GBP**,
with full multi-currency support if you need it.

## Run it
`budget_app.py` is the entry point — it lives one directory up from this README, at the top of `ledger/` (everything in this `src/` folder is what it imports).
```
cd ..
python3 budget_app.py
```
Requires Python 3 with Tkinter (usually built in; on Linux: `sudo apt install python3-tk`).

## Multiple profiles
The app opens to a launcher screen where you pick or create a profile (e.g.
"Personal", "Side Business", or one per household member). Each profile is a
fully separate SQLite database saved in a **`Profiles`** folder that sits
right next to `budget_app.py` — not buried in a hidden home-directory
folder, and not mixed in with the `.py` source files either, so it's easy to
find, back up, or move to another machine. No data ever crosses profiles.
Switch profiles anytime from the sidebar or the File menu.

If you ever see a "file is being used by another process" error deleting a
profile on Windows: that's fixed now — every path that closes or switches
away from a profile (Switch Profile, Exit, the window's close button) closes
its database connection first, and deleting a profile also retries a couple
of times before giving up, in case Windows' antivirus/indexing briefly holds
the file.

**Adding a profile from an existing `.db` file** (e.g. one shared with you,
or restored from a backup): don't hand-edit `Profiles/profiles.json` — it's
easy to get wrong, and if the JSON becomes invalid the app silently shows
*zero* profiles rather than erroring, which looks like data loss even though
nothing was actually deleted. Instead, drop the `.db` file into `Profiles/`
and open the launcher: any `.db` file sitting there that isn't registered
yet is auto-detected with a one-click "Add as a profile" button. You can
also use "Import Existing Profile…" to browse for a `.db` file anywhere
on disk.

## Accounts: cash, credit cards, and investments
Net Worth / FI is built around one unified accounts model, so everything
rolls into net worth correctly, but each type gets purpose-built treatment.
Every transaction you tag with a "Paid from" account — including ones
auto-posted from Recurring — keeps that account's balance in sync
automatically: cash accounts go down when you spend and up when income
lands; credit cards go **up** when you spend (that's the balance you owe)
and down when you pay them off. Deleting a transaction reverses the same
effect exactly, including any round-up it swept into the jar. Already
supports mixed currencies — if you log a transaction in a different
currency than the account it's paid from, it's converted using your FX
rates before adjusting the balance.

- **Cash / Bank** — current accounts, savings, cash. Mark as "liquid" to
  count toward your emergency-fund-months metric.
- **Credit Cards** — has a credit limit, a cashback rate, and an optional
  payment due day. The Net Worth tab shows a **utilization bar per card**
  (green under 30%, amber to 70%, red above — the thresholds that matter
  for credit scores), an overall utilization ring, and a due-date reminder
  that also surfaces on the Dashboard within 7 days of the payment date.
- **Investments** — has a contributions (cost-basis) figure separate from
  balance, so the app can show **growth in £ and %** (balance − what you
  actually put in), not just a raw number. Use "Add Contribution" when you
  pay money in, or "Update Value" for a mark-to-market price update — the
  two are tracked differently on purpose so growth stays meaningful. Set an
  expected annual return and a planned monthly contribution ("Set Growth
  Assumptions") to get an illustrative 10-year compounding **projection
  chart** — clearly labelled as illustrative, since no return is guaranteed.

The Net Worth tab shows a donut chart of net worth by type (cash / credit
card debt / investments / loans) alongside the net-worth trend line and FI
progress ring.

## Cashback and spare-change round-ups (Rewards tab)
- **Cashback** — set a cashback rate on any credit card. Pay for something
  with that card (via the "Paid from" selector on the Transactions tab) and
  the app computes and tracks the cashback automatically, live-previewed as
  you type the amount. The Rewards tab shows lifetime earned, what's
  unredeemed, a per-card bar chart, and a "Redeem Now" button that posts it
  as real income and optionally credits an account of your choice.
- **Round-ups** — Monzo/Acorns-style spare-change saving. Turn it on, pick
  a round-to amount (e.g. nearest £1) and a multiplier (1×–10×), and every
  card expense sweeps the difference into a Round-Up Jar automatically. The
  Rewards tab shows the jar balance, a cumulative round-ups-over-time chart,
  and a "Sweep Now" button to move the jar into savings or investments.

## Visual design
- A proper font stack (Segoe UI / SF Pro / Inter, whichever your OS has)
  instead of the Tk default font.
- Dark theme by default, with a light theme available in Settings.
- A left sidebar for navigation instead of plain notebook tabs, with a
  profile chip (avatar + name) up top.
- Cards with consistent padding, borders, and typography throughout.

## Charts
All hand-drawn on `tk.Canvas` — no matplotlib, no extra installs:
- Smoothed, gradient-filled net worth trend line.
- Grouped bar chart: income vs. expenses, last 6 months.
- Donut charts: this month's Need/Want/Saving split, and net worth by
  account type.
- Progress ring: FI progress.
- Per-card credit utilization bars.
- Cumulative round-up savings line chart and per-card cashback bar chart.
- 10-year investment growth projection line chart (illustrative only).

## Other features
- **Recurring bills & paychecks** — set up rent, a paycheck, subscriptions,
  etc. with a frequency (weekly/monthly/yearly). The app auto-posts
  anything that's come due since you last opened it, and shows what's
  coming up in the next 14 days on the Dashboard and the Recurring tab.
- **Debt payoff planner** — snowball vs. avalanche, real month-by-month
  amortization, not hand-waved.
- **CSV export** of your full transaction history, with reporting-currency
  conversion included.
- **Search/filter** in the Transactions list.
- **Life-energy view** — see any purchase as hours of work, based on an
  hourly wage you set once in Settings.

## What's inside (mapped to the original research's Part XII priority list)

| # | Feature | Where |
|---|---|---|
| 1 | Safe-to-spend / runway number | Dashboard hero |
| 2 | Savings target as a fixed line item | Settings → reserved before runway is calculated |
| 3 | Multi-currency ledger + editable FX table | Transactions tab + Settings → FX table |
| 4 | Net worth tracking + FI number (25× expenses) | Net Worth tab: trend chart + FI progress ring |
| 5 | Savings rate as headline metric | Dashboard metrics |
| 6 | Category envelopes (visual bars) | Budgets tab |
| 7 | Lifestyle-inflation flag (month-over-month >20%) | Dashboard flags panel |
| 8 | Debt payoff planner: snowball vs avalanche | Debt Planner tab |
| 9 | Financial health ratios (DTI, housing, savings rate) | Dashboard metrics |
| 10 | Idle-cash nudge | Dashboard flags panel |
| 11 | Statistical anomaly flags (stdev-based, no ML) | Dashboard flags panel |
| 12 | Life-energy cost view (hours of work per purchase) | Transactions tab, uses hourly wage from Settings |
| 13 | Light gamification (streaks/check-ins) | Dashboard |
| 14 | Low-friction "set once, check monthly" mode | Whole app is check-in based |
| 15 | Local-first SQLite storage | `Profiles/<profile>.db`, no network calls |
| 16 | Multiple isolated user profiles | Launcher screen + `profiles.py` |
| 17 | Recurring bills / paychecks | Recurring tab, auto-posts on open |
| 18 | CSV export | Transactions tab / File menu |
| 19 | Dark / light theme | Settings tab |
| 20 | Credit cards with utilization tracking | Net Worth tab |
| 21 | Investment accounts with contributions vs. growth | Net Worth tab |
| 22 | Cashback tracking + redemption | Rewards tab |
| 23 | Spare-change round-ups with multiplier | Rewards tab |
| 24 | Credit card payment due-date reminders | Net Worth tab + Dashboard nudge |
| 25 | Investment growth projection (illustrative) | Net Worth tab |

## Deliberately left out (per the research's Part X caution)
No GARCH, VaR, or trained ML anomaly detection — a few hundred manually entered
transactions don't meet the data requirements those techniques assume.
Anomaly detection here is a plain rolling mean/stdev comparison, which is the
honest version of the same idea. Likewise, no live FX rates or stock prices —
this is a local, offline tool; enter rates and valuations yourself in Settings
and the Net Worth tab.

## File layout
- `budget_app.py` — the UI: profile launcher, main window, all tabs.
- `finance_core.py` — SQLite data layer + all financial math (safe-to-spend,
  savings rate, debt payoff simulation, recurring transactions, cashback,
  round-ups, credit utilization, investment growth, etc.).
- `profiles.py` — the multi-profile registry (`Profiles/profiles.json`).
- `theme.py` — fonts, color palettes, and ttk styling.
- `crypto_utils.py` — stdlib-only password-lock cipher for profile encryption.
- `charts.py` — dependency-free Canvas chart drawing (line/area, bar, donut,
  progress ring).

## Changelog — data layer refactor (this update)
- **No more `profiles.json`.** Every `.db` in `Profiles/` is self-describing
  (its own `meta` table) and the launcher just scans the folder. Dropping a
  `.db` file in from a backup now makes it appear automatically.
- **Account-to-account transfers** are real, reconcilable ledger entries
  (two linked rows) with cross-currency `historical_rate` capture — Net
  Worth tab → "Transfer Between Accounts…".
- **Account detail ledger** — Net Worth tab → "View Ledger…" shows a running
  balance per account, transfers included.
- **Reconciliation/locking** — Transactions tab → select rows →
  Reconcile/Unreconcile. Reconciled rows can't be edited/deleted until
  unlocked.
- **Investment contributions/valuations** are now append-only logs, not a
  single overwritten number, so history is preserved; migrated
  automatically from any existing `contributions` balance.
- **CSV import** now stages and validates rows in a preview dialog
  (Transactions tab → "Import CSV…") before anything is committed.
- **Debt payoff planner** enforces that a planned payment can never be set
  below a debt's minimum payment.
- **Investment projections** show an illustrative low/high band based on a
  per-account volatility assumption, not just a single deterministic line.
- **Need/Want/Saving budgets** are enforced at entry time — adding an
  expense that would blow a category's monthly budget now warns before
  it's saved.
- All multi-row writes (transfers, CSV import, recurring auto-posting,
  cashback redemption, transaction delete + reversal) are now wrapped in
  explicit `with conn:` transactions for atomicity.
- **Profile-level encryption** is now real, not just a flag: Settings →
  "Lock This Profile With a Password…" encrypts the `.db` into a
  `.db.locked` sidecar (stdlib-only PBKDF2 + HMAC-SHA256 counter-mode
  cipher, since Python's `zipfile` can't actually write encrypted
  archives). Locked profiles show a 🔒 in the launcher and prompt for the
  password to reopen. Honest caveat: this is a solid deterrent against
  casual snooping, but it's a small hand-rolled construction, not a
  library that's had independent security review — full-disk encryption
  is still the stronger option for anything highly sensitive.

- **Editing transactions** is now possible everywhere they're shown:
  double-click a row (or "Edit Selected…") on the Transactions tab, or
  double-click a row in an account's Ledger view (Net Worth tab → View
  Ledger…) — both open the same edit dialog, backed by
  `finance_core.update_transaction()`, which atomically reverses the old
  balance/round-up/cashback effect and reapplies the new one. Reconciled
  transactions prompt before unlocking; transfer legs can't be edited
  directly (delete + recreate the transfer instead, since it's two linked
- **Bug fix: transfers were polluting monthly totals.** Once transfers
  became real ledger rows (this refactor), every function that sums up a
  month's activity — savings rate, safe-to-spend, budget envelopes,
  anomaly detection, lifestyle-inflation flags, debt-to-income/housing
  ratios — needed to exclude transfer legs, since moving money from
  Checking to Savings isn't income or an expense. `transactions_in_month()`
  now excludes `is_transfer` rows by default (with an `include_transfers`
  override for ledger-style views), and `category_anomalies` does the
  same. Caught this by testing a transfer against `savings_rate` directly
  rather than assuming the existing call sites were still correct after
  transfers changed shape.
- **Bug fix: budget-enforcement currency conversion was a no-op.** The
  "would this exceed your budget?" check introduced with Need/Want/Saving
  enforcement converted the new expense using
  `to_reporting(amount, reporting_currency)` — since that's a 1:1
  conversion, an expense logged in any currency other than your reporting
  currency was silently compared at face value instead of being converted
  (a €90 expense would've been treated as £90, not ~£76.50). Fixed by
  passing the transaction's actual currency through; verified with a
  multi-currency test.
- **Bug fix: a debt's "Planned Payment" was validated but never used.**
  `custom_payment` was checked against `min_payment` when you set it, but
  the payoff simulation itself still only ever paid the contractual
  minimum plus whatever you typed in the separate "extra payment" box —
  so setting a higher planned payment on a specific debt did nothing.
  Fixed: each debt's planned payment (if set) is now used as its actual
  monthly floor in the simulation, with the shared extra-payment pool
  still allocated by avalanche/snowball priority on top of that. Verified
  it meaningfully changes payoff time (a 20% APR card with a £25 minimum
  goes from a 600-month timeout to a 12-month payoff once its planned
  £200/month payment is actually applied).
- **Bug fix: redeeming cashback into an account bypassed the ledger.**
  `redeem_cashback(target_account_id=...)` bumped the target account's
  balance with a raw SQL update instead of going through a linked
  transaction — so the credit didn't show up in that account's ledger,
  ignored currency conversion if the account wasn't in the reporting
  currency, and (worse) editing or deleting the "Cashback redeemed"
  transaction afterward wouldn't reverse it, permanently stranding the
  balance. Fixed by inserting the transaction WITH the target account_id
  and applying the normal balance-effect path. Verified end-to-end: a €100
  card purchase earns cashback, redeeming it into a GBP account converts
  correctly, shows up in that account's ledger, and deleting the redeemed
  transaction now correctly reverses the credit.

## A few usage notes

- Everything defaults to **GBP**. Change it in Settings if you want a
  different base currency — existing profiles keep whatever they were set
  to; this only changes the default for new profiles.
- Set a **monthly savings target** so the safe-to-spend number reflects
  Pay-Yourself-First, not just "whatever's left."
- Add your rent/paycheck to **Recurring** once — the app auto-posts it every
  period from then on.
- If you ever sync your `Profiles` folder to the cloud, encrypt it first —
  it's plain SQLite.
- The whole `Profiles` folder is your backup unit: copy it to move your data
  to another machine, or zip it up before making risky changes.
