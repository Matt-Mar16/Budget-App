# THE LEDGER — a local-first budgeting app

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
fully separate SQLite database in its own subfolder under **`Profiles/`**
(`Profiles/<slug>/profile.db`) — a folder that sits right next to
`budget_app.py`, not buried in a hidden home-directory folder and not mixed
in with the `.py` source files, so it's easy to find, back up, or move to
another machine. No data ever crosses profiles. Switch profiles anytime from
the sidebar or the File menu; rename one from Settings → Profile.

**Adding a profile from an existing `.db` file** (e.g. one shared with you,
or restored from a backup): use "Import Existing Profile…" in the launcher
to browse for it anywhere on disk. Any `.db` file already sitting inside
`Profiles/` is picked up automatically the next time the launcher opens —
there's no registry file to keep in sync (`Profiles/profiles.json` is an old
artifact left over from an earlier version and is no longer read).

## The tabs
- **Dashboard** — safe-to-spend runway number, key ratios, this month's
  need/want/saving split, an income-vs-expenses trend chart, and a flags
  panel (lifestyle-inflation, idle cash, budget threshold, statistical
  anomalies).
- **Transactions** — add/edit/search/filter, split a transaction across
  categories, tag transactions, mark one as owed by someone else, import a
  bank CSV (staged preview before anything commits), export.
- **Budgets** — need/want/saving envelopes with reorderable categories,
  income categories (pure labeling, no envelope), an actual-vs-budgeted
  visual per category.
- **Insights** — top payees this month, a spending heatmap by day of month.
- **Forecast** — multi-month spend trend, a run-rate projection per budgeted
  category, actual-vs-budgeted donuts, a "What If…" tool to see the effect
  of spending more or less in a category without touching real data, and a
  savings/net-worth goal tracker.
- **Recurring** — bills/paychecks that auto-post when due, including
  irregular schedules (every N months) and one-off "I know this is coming"
  entries; a detector flags payees that look like an undeclared subscription.
- **Debt Planner** — snowball vs. avalanche payoff simulation, real
  month-by-month amortization.
- **Accounts** — add/edit/delete accounts, transfer between them, reconcile
  a balance to match a real statement, view an account's running-balance
  ledger, export a statement CSV, configure a credit card's cashback rate/
  cap/destination and payment due day.
- **Net Worth / FI** — net worth over time, FI progress, net worth by
  account type, investment holdings summary, an illustrative growth
  projection.
- **Investments** — buy/sell transactions per security with UK Section 104
  average-cost pooling (see caveat below), realized gains.
- **Tax** — this UK tax year's realized capital gains vs. the annual exempt
  amount (not tax advice — a rough estimate you should verify).
- **Rewards** — cashback earned/redeemed, the spare-change round-up jar.
- **Settings** — currency, theme, month start day, navigation customization,
  data files, profile management.

Any tab except Dashboard and Settings can be hidden from the sidebar
(Settings → Customize Navigation) if you don't use it.

## Accounts: cash, credit cards, and investments
Everything rolls into net worth correctly, but each account type gets
purpose-built treatment. Every transaction tagged with a "Paid from" account
— including ones auto-posted from Recurring — keeps that account's balance
in sync automatically: cash accounts go down when you spend and up when
income lands; credit cards go **up** when you spend (that's the balance you
owe) and down when you pay them off. Deleting a transaction reverses the
same effect exactly, including any round-up it swept into the jar. Mixed
currencies are handled — a transaction logged in a different currency than
its account is converted using your FX rates before adjusting the balance.

- **Cash / Bank** — current accounts, savings, cash. Mark as "liquid" to
  count toward your emergency-fund-months metric.
- **Credit Cards** — a credit limit, a cashback rate + optional monthly cap,
  a payment due day, and a cashback destination (accumulate for manual
  redemption, auto-invest into an investment account, or sweep into the
  Round-Up Jar). The Accounts tab shows a **utilization bar per card**
  (green under 30%, amber to 70%, red above — the thresholds that matter for
  credit scores) and a due-date reminder that surfaces on the Dashboard
  within 7 days.
- **Investments** — a contributions (cost-basis) figure separate from
  balance, so the app can show **growth in £ and %** (balance − what you
  actually put in), not just a raw number. Use "Add Contribution" when you
  pay money in, or "Update Market Value" for a mark-to-market price update —
  the two are tracked differently on purpose so growth stays meaningful. Set
  an expected annual return, a planned monthly contribution, and a return
  volatility to get an illustrative 10-year compounding **projection chart**
  with a low/high range, clearly labelled as illustrative since no return is
  guaranteed.
- **"Edit Selected Account…"** lets you correct name/currency/balance/
  liquid/credit-limit/cashback/due-day/investment-assumption fields directly
  with no transaction recorded — for backfilling a starting balance without
  logging every historical transaction. Use "Reconcile…" instead if you
  want the correction to show up as a real, traceable ledger entry.

## Custom month start day
By default the app's reporting "month" is the calendar month. If you're paid
on, say, the 25th, set **Month start day** in Settings to `25` and every
month-based number (Dashboard, Budgets, Insights, Forecast's run-rate) shifts
to run 25th-to-24th instead — budgets and safe-to-spend line up with when
money actually arrives, not the calendar. Doesn't affect recurring bill due
dates or the UK tax year, which stay on their own real-world schedules. The
Insights spending heatmap deliberately stays on the plain calendar month,
since a weekday-grid chart can't represent a period that spans two calendar
months.

## Cashback and spare-change round-ups (Rewards tab)
- **Cashback** — set a cashback rate on any credit card. Pay for something
  with that card (via the "Paid from" selector on the Transactions tab) and
  the app computes and tracks the cashback automatically, live-previewed as
  you type the amount, and correctable by hand afterward if the card issuer
  actually paid out something different. The Rewards tab shows lifetime
  earned, what's unredeemed, a per-card bar chart, and a "Redeem Now" button
  that posts it as real income and optionally credits an account of your
  choice.
- **Round-ups** — Monzo/Acorns-style spare-change saving. Turn it on, pick a
  round-to amount (e.g. nearest £1) and a multiplier (1×–10×), and every
  card expense sweeps the difference into a Round-Up Jar automatically. The
  Rewards tab shows the jar balance, a cumulative round-ups-over-time chart,
  and a "Sweep Now" button to move the jar into savings or investments.

## Phone entry
`../src/inbox_sync.py`/`sync_inbox.py` (needs `openpyxl` — see below) build
an `Inbox.xlsx` workbook with a `Transactions` table plus `Accounts`/
`Categories` dropdown sheets pulled live from a profile. Enter transactions
on your phone in that workbook (it needs to live somewhere phone-synced,
e.g. OneDrive); running `sync_inbox.py --profile <slug>` on the laptop reads
whatever's there, turns it into real transactions (including paired
"Currency Exchange" rows, which become a proper linked transfer), backs up
what it read, and clears the sheet.

## Bulk-editing via CSV
Every profile gets four editable CSV files (`transactions.csv`,
`accounts.csv`, `categories.csv`, `investments.csv`) for quick bulk edits or
backfilling historical data outside the GUI — Settings → Data Files →
"Refresh CSVs from App" to export, "Apply Changes from CSVs…" to read edits
back in (backs up the database first). A blank `id` column adds a row, an
edited existing `id` edits it, and removing a row's `id` from the file
deletes it — except transfers, reconciled transactions, and split
transactions, which are shown for visibility but protected from
edit-or-delete-by-omission.

## Visual design
- A proper font stack (Segoe UI / SF Pro / Inter, whichever your OS has)
  instead of the Tk default font.
- Dark theme by default, with a light theme available in Settings.
- A left sidebar for navigation, grouped and collapsible, with a profile
  chip (avatar + name) up top.
- Cards with consistent padding, borders, and typography throughout.
- Every scrollable area's scrollbar only shows up when there's actually
  something to scroll.

## Charts
All hand-drawn on `tk.Canvas` — no matplotlib, no extra installs:
- Smoothed, gradient-filled net worth and expense-trend lines.
- Grouped bar charts: income vs. expenses over a selectable range.
- Donut charts: need/want/saving split, actual vs. budgeted spend, net
  worth by account type.
- A calendar-grid heatmap for day-of-month spending.
- Progress ring: FI progress.
- Per-card credit utilization bars.
- Cumulative round-up savings line chart and per-card cashback bar chart.
- 10-year investment growth projection with an illustrative low/high band.

## Investments — known limitation
Capital-gains tracking implements **plain UK Section 104 average-cost
pooling only**. It does **not** implement HMRC's same-day rule or the
30-day "bed and breakfast" rule, both of which would need to apply before
pooling for a fully correct UK CGT figure — the Tax tab's own copy flags
this too. Treat the Tax tab's numbers as a starting estimate, not a filing.

## Profile encryption
Settings → "Lock This Profile With a Password…" encrypts a profile's `.db`
into a `.db.locked` sidecar using a stdlib-only PBKDF2-HMAC-SHA256 +
HMAC-SHA256 counter-mode cipher (Python's `zipfile` can't actually write
encrypted archives, hence the hand-rolled construction). Locked profiles
show a 🔒 in the launcher and prompt for the password to reopen. Honest
caveat: this is a solid deterrent against casual snooping, but it's a small
hand-rolled construction that hasn't had the independent security review a
maintained library gets — full-disk encryption (BitLocker/FileVault/LUKS)
is still the stronger option for anything highly sensitive.

## File layout
- `budget_app.py` (one level up) — the UI: profile launcher, main window,
  all tabs.
- `finance_core.py` — SQLite data layer + all financial math (safe-to-spend,
  savings rate, debt payoff simulation, recurring transactions, cashback,
  round-ups, credit utilization, investment growth, forecasting, etc.).
- `profiles.py` — the multi-profile registry (scans `Profiles/` directly).
- `theme.py` — fonts, color palettes, and ttk styling.
- `crypto_utils.py` — stdlib-only password-lock cipher for profile encryption.
- `charts.py` — dependency-free Canvas chart drawing.
- `inbox_sync.py` / `sync_inbox.py` — the phone-entry bridge (needs
  `openpyxl`, isolated in its own use — see `requirements.txt`).

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
