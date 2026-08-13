# Custom Month Start Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the reporting "month" used throughout THE LEDGER start on a custom day (e.g. the 25th, to match payday) instead of always being a plain calendar month.

**Architecture:** One new core primitive (`month_bounds`) becomes the single source of truth for what real date range a reporting "month" spans, reading a new `month_start_day` setting (default 1 = today's exact calendar-month behavior). Because every reporting function already funnels through `Database.transactions_in_month`, fixing that one method fixes ~15 downstream functions automatically. Only `transactions_in_month` and `budget_run_rate` need their internals touched; `daily_spend_totals` is deliberately left as pure calendar-month (its output feeds a weekday-grid calendar heatmap chart that can't sensibly represent a period spanning two calendar months). GUI changes are limited to `App`'s initial view/`goto_today`/month-label, plus one new Settings field.

**Tech Stack:** Python 3 (stdlib only: `sqlite3`, `tkinter`, `datetime`, `calendar`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-custom-month-start-design.md`

## Global Constraints

- `finance_core.py` and `budget_app.py` are stdlib-only — no third-party dependencies. Do not add one.
- Every `finance_core.py` addition is built test-first (RED-GREEN) into `ledger/tests/test_finance_core.py`. Run from `ledger/`: `py -3.12 -m pytest` (no `.venv` exists in this checkout — use the `py` launcher directly, not `.venv/Scripts/python.exe`).
- GUI changes in `budget_app.py` have no pytest coverage by established convention. Verify each with a one-off headless smoke script: construct `App` directly against a **sandboxed** `profiles.APP_DIR` (a fresh `tempfile.mkdtemp()`, never the real `Profiles/` folder), drive the tab/dialog in code, assert on state. Python for smoke scripts: `py -3.14`, prefixed with `PYTHONIOENCODING=utf-8` (cp1252 console).
- **`month_start_day == 1` (the default) must reproduce byte-for-byte identical behavior to the current codebase in every function this plan touches.** This is the safety property that makes the whole feature low-risk — verify it explicitly in tests, don't just assume it.
- **Recurring bill due-dates and the UK tax year are explicitly out of scope** — `_advance_date`, `generate_due_recurring`, `upcoming_bills`, and `uk_tax_year_start` must not be touched by this plan.
- **`daily_spend_totals` and `charts.draw_calendar_heatmap` are explicitly out of scope** — see spec's rationale (weekday-grid chart incompatible with a cross-calendar-month period). Do not modify either.
- A month is labeled by the calendar month it starts in (e.g. `month_start_day=25`, `(year=2026, month=8)` spans 25 Jul–24 Aug 2026).

---

## File Structure

| File | Responsibility |
|---|---|
| `ledger/src/finance_core.py` | Modify: new `Database.get_setting_int`, new module functions `month_bounds`, `custom_month_for_date`; rewrite `Database.transactions_in_month` and `budget_run_rate` internals |
| `ledger/tests/test_finance_core.py` | Modify: new tests for all of the above |
| `ledger/budget_app.py` | Modify: `SettingsTab` (new field), `App.__init__`/`goto_today`/`_update_month_label` |

No new files.

---

## Task 1: `get_setting_int`, `month_bounds`, `custom_month_for_date`

**Files:**
- Modify: `ledger/src/finance_core.py` (new `Database.get_setting_int` method, directly after `get_setting_float` around line 507; two new module-level functions, placed directly after `_last_day_of_month` around line 1825, since both depend on it)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Produces: `Database.get_setting_int(key, default=0) -> int` — same try/except-around-a-cast pattern as the existing `get_setting_float`.
- Produces: `month_bounds(db, year, month) -> (start_date_str, end_date_str)` — both ISO `YYYY-MM-DD` strings. Reads `db.get_setting_int("month_start_day", 1)`, clamped to `1..28` (values outside that range are clamped, not rejected — mirrors how `due_day` is already clamped elsewhere in this file).
- Produces: `custom_month_for_date(db, a_date) -> (year, month)` — `a_date` is a `datetime.date`. Used later (Task 5) to resolve "today" into the right reporting-month bucket.

- [ ] **Step 1: Write the failing tests**

Add to `ledger/tests/test_finance_core.py`:

```python
def test_get_setting_int_returns_default_when_unset(tmp_path):
    db = _db(tmp_path)
    assert db.get_setting_int("month_start_day", 1) == 1
    db.close()


def test_get_setting_int_parses_a_stored_value(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    assert db.get_setting_int("month_start_day", 1) == 25
    db.close()


def test_month_bounds_defaults_to_plain_calendar_month(tmp_path):
    db = _db(tmp_path)
    # month_start_day unset -> must reproduce exact current calendar-month
    # behavior: start=1st, end=last real day of that month.
    assert month_bounds(db, 2026, 2) == ("2026-02-01", "2026-02-28")
    assert month_bounds(db, 2024, 2) == ("2024-02-01", "2024-02-29")  # leap year
    db.close()


def test_month_bounds_with_a_custom_start_day(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    assert month_bounds(db, 2026, 8) == ("2026-08-25", "2026-09-24")
    db.close()


def test_month_bounds_custom_start_day_rolls_over_the_year(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    assert month_bounds(db, 2026, 12) == ("2026-12-25", "2027-01-24")
    db.close()


def test_month_bounds_clamps_start_day_31_into_shorter_months(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "31")
    # (year=2026, month=2): start clamps to Feb 28 (2026 isn't a leap year);
    # end is one day before March's clamped start (Mar 31) = Mar 30.
    assert month_bounds(db, 2026, 2) == ("2026-02-28", "2026-03-30")
    db.close()


def test_custom_month_for_date_defaults_to_plain_calendar_month(tmp_path):
    db = _db(tmp_path)
    assert custom_month_for_date(db, datetime.date(2026, 8, 15)) == (2026, 8)
    db.close()


def test_custom_month_for_date_before_the_start_day_belongs_to_the_prior_month(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    assert custom_month_for_date(db, datetime.date(2026, 8, 20)) == (2026, 7)
    db.close()


def test_custom_month_for_date_on_or_after_the_start_day_belongs_to_that_month(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    assert custom_month_for_date(db, datetime.date(2026, 8, 25)) == (2026, 8)
    db.close()


def test_custom_month_for_date_rolls_the_year_back_at_january(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    assert custom_month_for_date(db, datetime.date(2026, 1, 10)) == (2025, 12)
    db.close()
```

Add `month_bounds, custom_month_for_date` to the `from finance_core import (...)` block at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `ledger/`): `py -3.12 -m pytest tests/test_finance_core.py -k "get_setting_int or month_bounds or custom_month_for_date" -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'get_setting_int'` (and `ImportError` for the two module functions once that's fixed).

- [ ] **Step 3: Implement `get_setting_int`**

Directly after `get_setting_float` in `finance_core.py`:

```python
    def get_setting_int(self, key, default=0):
        try:
            return int(self.get_setting(key, default))
        except (TypeError, ValueError):
            return default
```

- [ ] **Step 4: Implement `month_bounds` and `custom_month_for_date`**

Directly after `_last_day_of_month` in `finance_core.py`:

```python
def _clamped_month_start(db, year, month):
    start_day = min(max(db.get_setting_int("month_start_day", 1), 1), 28)
    last_day = _last_day_of_month(year, month).day
    return datetime.date(year, month, min(start_day, last_day))


def month_bounds(db: Database, year, month):
    """The real calendar date range a reporting "month" (year, month)
    spans, given the month_start_day setting (default 1 = plain calendar
    month, byte-for-byte identical to date(year, month, 1)..last day of
    that month). A month is labeled by the calendar month it starts in:
    with month_start_day=25, (year, 8) spans 25 Jul-24 Aug."""
    start_date = _clamped_month_start(db, year, month)
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    next_start = _clamped_month_start(db, next_year, next_month)
    end_date = next_start - datetime.timedelta(days=1)
    return start_date.isoformat(), end_date.isoformat()


def custom_month_for_date(db: Database, a_date):
    """Which reporting-month bucket (year, month) a real date falls into,
    given month_start_day. Used to resolve "today" into the right bucket
    when the app opens or "Today" is clicked."""
    start_day = min(max(db.get_setting_int("month_start_day", 1), 1), 28)
    if a_date.day >= start_day:
        return a_date.year, a_date.month
    month = a_date.month - 1
    year = a_date.year
    if month < 1:
        month = 12
        year -= 1
    return year, month
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_finance_core.py -k "get_setting_int or month_bounds or custom_month_for_date" -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Run the full suite**

Run: `py -3.12 -m pytest`
Expected: PASS (all tests green)

- [ ] **Step 7: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: month_bounds/custom_month_for_date primitives for custom month start"
```

---

## Task 2: `transactions_in_month` uses `month_bounds`

**Files:**
- Modify: `ledger/src/finance_core.py:1057-1073` (`Database.transactions_in_month`)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Consumes: `month_bounds(db, year, month)` from Task 1.
- Produces: `transactions_in_month`'s public signature and return shape are UNCHANGED — every one of the ~15 functions built on top of it needs no changes of their own. This task only changes what date range gets queried internally.

- [ ] **Step 1: Write the failing tests**

```python
def test_transactions_in_month_default_behavior_is_unchanged(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_transaction("2026-07-31", "Old", None, -10.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-08-01", "In", None, -20.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-08-31", "Also in", None, -30.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-09-01", "Next", None, -40.0, "GBP", account_id=acc_id)

    rows = db.transactions_in_month(2026, 8)

    assert {r["payee"] for r in rows} == {"In", "Also in"}
    db.close()


def test_transactions_in_month_respects_a_custom_start_day(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_transaction("2026-07-24", "Before period", None, -10.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-07-25", "Period starts", None, -20.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-08-24", "Period ends", None, -30.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-08-25", "Next period", None, -40.0, "GBP", account_id=acc_id)

    rows = db.transactions_in_month(2026, 8)

    assert {r["payee"] for r in rows} == {"Period starts", "Period ends"}
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_finance_core.py -k "transactions_in_month_default or transactions_in_month_respects" -v`
Expected: `test_transactions_in_month_respects_a_custom_start_day` FAILS (the current `LIKE 'YYYY-MM%'` query includes "Next period" and excludes "Period starts"). The default-behavior test may already pass — that's fine, it's regression protection for Step 4, not meant to prove new behavior.

- [ ] **Step 3: Implement**

In `finance_core.py`, replace `transactions_in_month`'s body:

```python
    def transactions_in_month(self, year, month, include_transfers=False):
        """Transactions for the given reporting month, for financial
        aggregation (monthly totals, savings rate, budgets, anomaly
        detection, etc). The real date range is determined by
        month_bounds() (respects the month_start_day setting; defaults to
        a plain calendar month). Transfers between the user's own accounts
        are excluded by default — moving money from Checking to Savings
        isn't income or an expense, and counting both legs would
        double-count it as both. Pass include_transfers=True for
        ledger-style views that want to see everything that happened."""
        start_date, end_date = month_bounds(self, year, month)
        transfer_clause = "" if include_transfers else "AND t.is_transfer = 0 "
        return self.conn.execute(
            "SELECT t.*, c.name as category_name, c.kind as category_kind, a.name as account_name "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "LEFT JOIN accounts a ON t.account_id = a.id "
            f"WHERE t.date >= ? AND t.date <= ? {transfer_clause}ORDER BY date",
            (start_date, end_date),
        ).fetchall()
```

`month_bounds` is a module-level function defined above this class in the same file, so no import is needed — but since it's called as `month_bounds(self, ...)` from inside a method defined earlier in the file than `month_bounds` itself, this works fine in Python (names are resolved at call time, not definition time, and both live in the same module).

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_finance_core.py -k "transactions_in_month_default or transactions_in_month_respects" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `py -3.12 -m pytest`
Expected: PASS — this is the highest-blast-radius change in the whole plan (every function built on `transactions_in_month` is exercised transitively by the existing suite), so a full green run here is the key checkpoint.

- [ ] **Step 6: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: transactions_in_month respects the custom month start day"
```

---

## Task 3: `budget_run_rate` uses `month_bounds`

**Files:**
- Modify: `ledger/src/finance_core.py:2848-2868` (`budget_run_rate`)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Consumes: `month_bounds(db, year, month)` from Task 1.
- Produces: `budget_run_rate`'s public signature and return shape are UNCHANGED (still a list of dicts with `days_elapsed`, `days_in_month`, `projected`, `projected_over`, plus the spread `category_budget_status` row).

- [ ] **Step 1: Write the failing tests**

```python
def test_budget_run_rate_default_days_elapsed_is_unchanged(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Run Rate 2", "need", 300.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Run Rate 2")
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_transaction("2026-08-10", "Tesco", cat_id, -100.0, "GBP", account_id=acc_id)

    result = budget_run_rate(db, 2026, 8, today=datetime.date(2026, 8, 10))

    row = next(r for r in result if r["category"]["id"] == cat_id)
    assert row["days_elapsed"] == 10  # 10th of a plain-calendar August
    assert row["days_in_month"] == 31
    db.close()


def test_budget_run_rate_respects_a_custom_start_day(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    db.add_category("Groceries Run Rate 3", "need", 300.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Run Rate 3")
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    # Reporting month (2026, 8) with month_start_day=25 spans 25 Jul-24 Aug.
    db.add_transaction("2026-07-29", "Tesco", cat_id, -100.0, "GBP", account_id=acc_id)

    result = budget_run_rate(db, 2026, 8, today=datetime.date(2026, 7, 29))

    row = next(r for r in result if r["category"]["id"] == cat_id)
    assert row["days_elapsed"] == 5  # Jul 25 (day 1) .. Jul 29 (day 5)
    assert row["days_in_month"] == 31  # 25 Jul-24 Aug = 31 days
    db.close()


def test_budget_run_rate_clamps_days_elapsed_after_the_period_ends(tmp_path):
    db = _db(tmp_path)
    db.set_setting("month_start_day", "25")
    db.add_category("Groceries Run Rate 4", "need", 300.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Run Rate 4")
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_transaction("2026-07-26", "Tesco", cat_id, -310.0, "GBP", account_id=acc_id)

    # "Today" is well after this period (25 Jul-24 Aug) has closed.
    result = budget_run_rate(db, 2026, 8, today=datetime.date(2026, 9, 15))

    row = next(r for r in result if r["category"]["id"] == cat_id)
    assert row["days_elapsed"] == 31  # clamped to the full period, not still counting up
    assert row["projected"] == pytest.approx(310.0)  # spend-so-far == full month's projection
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.12 -m pytest tests/test_finance_core.py -k "budget_run_rate_default or budget_run_rate_respects or budget_run_rate_clamps" -v`
Expected: `test_budget_run_rate_respects_a_custom_start_day` and `test_budget_run_rate_clamps_days_elapsed_after_the_period_ends` FAIL — the current implementation compares `(today.year, today.month) == (year, month)` directly, which gives wrong answers once the reporting period no longer aligns with a literal calendar month.

- [ ] **Step 3: Implement**

In `finance_core.py`, replace `budget_run_rate`'s body:

```python
def budget_run_rate(db: Database, year, month, today: Optional[datetime.date] = None):
    """Projects each budgeted category's month-end spend from the pace set
    so far this reporting period (spend-so-far / days-elapsed * days-in-
    period), so an overspend can be caught while there's still time to
    react instead of only after the period closes. Respects the
    month_start_day setting via month_bounds()."""
    today = today or datetime.date.today()
    start_str, end_str = month_bounds(db, year, month)
    start_date = datetime.date.fromisoformat(start_str)
    end_date = datetime.date.fromisoformat(end_str)
    days_in_month = (end_date - start_date).days + 1
    if today < start_date:
        days_elapsed = 0
    elif today > end_date:
        days_elapsed = days_in_month
    else:
        days_elapsed = (today - start_date).days + 1

    out = []
    for row in category_budget_status(db, year, month):
        projected = (row["spent"] / days_elapsed * days_in_month) if days_elapsed > 0 else 0.0
        out.append({**row, "days_elapsed": days_elapsed, "days_in_month": days_in_month,
                     "projected": projected, "projected_over": projected > row["budget"]})
    out.sort(key=lambda r: -(r["projected"] - r["budget"]))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3.12 -m pytest tests/test_finance_core.py -k "budget_run_rate_default or budget_run_rate_respects or budget_run_rate_clamps" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `py -3.12 -m pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: budget_run_rate respects the custom month start day"
```

---

## Task 4: Settings field for `month_start_day`

**Files:**
- Modify: `ledger/budget_app.py:3387-3391` (`SettingsTab._build`, directly after the existing "Budget alert threshold" field), `SettingsTab.save_settings` (around line 3565-3581), `SettingsTab.refresh` (search for where `budget_alert_threshold_var` gets loaded, around line 3615)
- Smoke test: throwaway script, run via Bash, not committed to the repo

**Interfaces:**
- Consumes: `Database.get_setting`/`set_setting` (already exist).
- Produces: no new public interface — GUI-only, persists the `month_start_day` setting as a string via the existing `set_setting`/`get_setting` mechanism (matches every other numeric setting in this tab).

**Depends on:** nothing from Tasks 1-3 directly (this task is just a settings field), but it's the field that makes Task 5's behavior configurable, so do it before Task 5.

- [ ] **Step 1: Add the field to `SettingsTab._build()`**

In `budget_app.py`, directly after the existing block:

```python
        ttk.Label(general, text="Budget alert threshold (% of category budget)",
                  style="CardDim.TLabel").grid(row=6, column=0, sticky="w")
        self.budget_alert_threshold_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.budget_alert_threshold_var, width=10).grid(
            row=6, column=1, padx=6)
```

add:

```python
        ttk.Label(general, text="Month start day (1 = calendar month)",
                  style="CardDim.TLabel").grid(row=7, column=0, sticky="w")
        self.month_start_day_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.month_start_day_var, width=10).grid(
            row=7, column=1, padx=6)
        ttk.Label(general, wraplength=420, justify="left", style="CardDim.TLabel",
                  text="e.g. 25 if you're paid on the 25th — the Dashboard/Budgets/Insights "
                       "\"month\" then runs 25th-24th instead of the 1st-end of the calendar "
                       "month. Doesn't affect when bills are due or the UK tax year."
                  ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(2, 0))
```

Then change the existing "Save Settings" button (the only remaining widget in this `general` frame, at `row=7`, directly after the block above) from:

```python
        ttk.Button(general, text="Save Settings", style="Accent.TButton",
                   command=self.save_settings).grid(row=7, column=0, pady=10, sticky="w")
```

to:

```python
        ttk.Button(general, text="Save Settings", style="Accent.TButton",
                   command=self.save_settings).grid(row=9, column=0, pady=10, sticky="w")
```

(rows 7-8 are now occupied by the new field and its help text; the button moves to row 9). Nothing else in the `general` frame comes after this button — `self.fx_frame` immediately below it is a separate `Card`, not part of this grid.

- [ ] **Step 2: Save and load the setting**

In `save_settings()`, directly after the existing block:

```python
        try:
            float(self.budget_alert_threshold_var.get())
            db.set_setting("budget_alert_threshold_pct", self.budget_alert_threshold_var.get())
        except ValueError:
            pass
```

add:

```python
        try:
            day = int(self.month_start_day_var.get())
            if 1 <= day <= 28:
                db.set_setting("month_start_day", str(day))
        except ValueError:
            pass
```

In `refresh()` (search for `self.budget_alert_threshold_var.set(...)`), directly after that line, add:

```python
        self.month_start_day_var.set(db.get_setting("month_start_day", "1"))
```

- [ ] **Step 3: Write and run a headless smoke script**

Create `$CLAUDE_JOB_DIR/tmp/smoke_month_start_setting.py`:

```python
import sys
import tempfile

sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger")
sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger\src")

import profiles
profiles.APP_DIR = tempfile.mkdtemp()

import budget_app

profile = profiles.create_profile("Smoke Month Start Setting")
app = budget_app.App(profile)
db = app.db

app.show_page("settings")
settings_tab = app.pages["settings"]
settings_tab.refresh()
assert settings_tab.month_start_day_var.get() == "1", "default should be '1'"

settings_tab.month_start_day_var.set("25")
settings_tab.save_settings()
assert db.get_setting("month_start_day", "1") == "25"
print("save persists the setting: OK")

# Out-of-range values must not be saved (silently ignored, matching this
# form's existing float-field error handling style elsewhere in the tab)
settings_tab.month_start_day_var.set("99")
settings_tab.save_settings()
assert db.get_setting("month_start_day", "1") == "25", "out-of-range value should not overwrite"
print("out-of-range value rejected: OK")

settings_tab2_refresh_check = budget_app.App  # no-op reference, just documents intent
settings_tab.refresh()
assert settings_tab.month_start_day_var.get() == "25", "refresh should reload the saved value"
print("refresh reloads the saved value: OK")

app.db.close()
print("SMOKE TEST PASSED")
```

Run: `PYTHONIOENCODING=utf-8 py -3.14 "$CLAUDE_JOB_DIR/tmp/smoke_month_start_setting.py"`
Expected: `SMOKE TEST PASSED`, no traceback

- [ ] **Step 4: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: Settings field for custom month start day"
```

---

## Task 5: `App` navigates by the custom reporting month

**Files:**
- Modify: `ledger/budget_app.py:391-394` (`App.__init__`), `App.goto_today` (around line 587-589), `App._update_month_label` (around line 566-568)
- Smoke test: throwaway script, run via Bash, not committed to the repo

**Interfaces:**
- Consumes: `custom_month_for_date(db, a_date)` and `month_bounds(db, year, month)` from Task 1 (import both into `budget_app.py`'s existing `from finance_core import (...)` block).
- Produces: no new public interface — `App.view_year`/`view_month` now resolve through the custom-month scheme; every existing consumer of those two attributes (Dashboard, Budgets, Insights, `prev_month`/`next_month`) needs no changes, since they already just treat `(view_year, view_month)` as an opaque reporting-period index.

**Depends on:** Task 1 (the two functions), Task 4 (so there's a real setting to test against — write this task's smoke test using a profile with `month_start_day` set via `db.set_setting`, not through the Settings UI, so it doesn't also depend on Task 4's GUI code being correct).

- [ ] **Step 1: Add the import**

In `budget_app.py`, find the existing `from finance_core import (...)` block and add `custom_month_for_date` to it.

- [ ] **Step 2: Update `App.__init__`**

Change:

```python
        self.db = Database(profiles.db_path_for(profile["slug"]))
        self.today = datetime.date.today()
        self.view_year = self.today.year
        self.view_month = self.today.month
```

to:

```python
        self.db = Database(profiles.db_path_for(profile["slug"]))
        self.today = datetime.date.today()
        self.view_year, self.view_month = custom_month_for_date(self.db, self.today)
```

- [ ] **Step 3: Update `App.goto_today`**

Change:

```python
    def goto_today(self):
        self.view_year, self.view_month = self.today.year, self.today.month
        self.refresh_all()
```

to:

```python
    def goto_today(self):
        self.view_year, self.view_month = custom_month_for_date(self.db, self.today)
        self.refresh_all()
```

- [ ] **Step 4: Update `App._update_month_label`**

Change:

```python
    def _update_month_label(self):
        self.month_label.configure(
            text=datetime.date(self.view_year, self.view_month, 1).strftime("%B %Y"))
```

to:

```python
    def _update_month_label(self):
        if self.db.get_setting_int("month_start_day", 1) == 1:
            text = datetime.date(self.view_year, self.view_month, 1).strftime("%B %Y")
        else:
            start_str, end_str = month_bounds(self.db, self.view_year, self.view_month)
            start_date = datetime.date.fromisoformat(start_str)
            end_date = datetime.date.fromisoformat(end_str)
            text = f"{start_date.strftime('%d %b')} \u2013 {end_date.strftime('%d %b %Y')}"
        self.month_label.configure(text=text)
```

Add `month_bounds` to the same `from finance_core import (...)` import alongside `custom_month_for_date` from Step 1.

- [ ] **Step 5: Write and run a headless smoke script**

Create `$CLAUDE_JOB_DIR/tmp/smoke_custom_month_nav.py`:

```python
import sys
import tempfile
import datetime

sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger")
sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger\src")

import profiles
profiles.APP_DIR = tempfile.mkdtemp()

import budget_app

# --- Default (month_start_day=1): must behave exactly as before ---
profile = profiles.create_profile("Smoke Month Nav Default")
app = budget_app.App(profile)
today = datetime.date.today()
assert (app.view_year, app.view_month) == (today.year, today.month), (
    f"default view should be today's literal calendar month, got {(app.view_year, app.view_month)}")
app._update_month_label()
assert app.month_label.cget("text") == datetime.date(today.year, today.month, 1).strftime("%B %Y")
print("default month_start_day=1: view + label unchanged: OK")
app.db.close()

# --- Custom start day: view resolves to the right bucket, label shows the range ---
profile2 = profiles.create_profile("Smoke Month Nav Custom")
app2 = budget_app.App(profile2)
app2.db.set_setting("month_start_day", "25")
# Force a known "today" for deterministic assertions, bypassing the real clock.
app2.today = datetime.date(2026, 8, 20)  # before the 25th -> should resolve to July's bucket
app2.goto_today()
assert (app2.view_year, app2.view_month) == (2026, 7), (
    f"Aug 20 with start_day=25 should resolve to (2026, 7), got {(app2.view_year, app2.view_month)}")
app2._update_month_label()
assert app2.month_label.cget("text") == "25 Jul \u2013 24 Aug 2026", (
    f"unexpected label: {app2.month_label.cget('text')!r}")
print("custom month_start_day: goto_today resolves correctly, label shows real range: OK")

app2.today = datetime.date(2026, 8, 25)  # on the 25th -> should resolve to August's bucket
app2.goto_today()
assert (app2.view_year, app2.view_month) == (2026, 8)
print("boundary date (exactly on start day): resolves to the new period: OK")

app2.db.close()
print("SMOKE TEST PASSED")
```

Run: `PYTHONIOENCODING=utf-8 py -3.14 "$CLAUDE_JOB_DIR/tmp/smoke_custom_month_nav.py"`
Expected: `SMOKE TEST PASSED`, no traceback

- [ ] **Step 6: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: App navigates by the custom reporting month"
```

---

## Final check

- [ ] Run the full test suite once more from `ledger/`: `py -3.12 -m pytest` — expect all tests green, count increased by the new tests added in Tasks 1-3.
- [ ] Re-run all three smoke scripts from Tasks 4-5 in sequence to confirm no cross-task regression.
- [ ] Manually open the real app against a real profile (`matt` or `Matt_loaded`), go to Settings, set "Month start day" to a value like 25, and click through Dashboard/Budgets/Insights to confirm the reporting period, budget bars, and run-rate projections all shift to the new period sensibly. Confirm the Insights spending heatmap still shows a plain calendar month (deliberately unaffected). Set it back to 1 (or leave blank) afterward if you don't actually want this on for real use yet. This is the hands-on check the headless smoke scripts can't replace.
