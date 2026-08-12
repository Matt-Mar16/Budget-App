# THE LEDGER — Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add income categories, category deletion, transaction filtering, and dismissible subscription suggestions to THE LEDGER, per the approved design in `docs/superpowers/specs/2026-08-12-quick-wins-design.md`.

**Architecture:** Four independent additive features, built core-first: schema migration, aggregation function, CRUD methods, and detector integration land in `ledger/src/finance_core.py` test-first (RED-GREEN against `ledger/tests/test_finance_core.py`), then GUI wiring lands in `ledger/budget_app.py` verified with headless smoke scripts — matching this codebase's established layering (`Database`/module functions are stdlib-only and fully tested; Tkinter code is headless-smoke-verified only) and its "block, don't silently drop" protection philosophy for destructive operations.

**Tech Stack:** Python 3 (stdlib only: `sqlite3`, `tkinter`), pytest.

## Global Constraints

- `finance_core.py` and `budget_app.py` are stdlib-only — no third-party dependencies, per CLAUDE.md. Do not add one.
- Every `finance_core.py` addition is built test-first (RED-GREEN) into `ledger/tests/test_finance_core.py`. Run from `ledger/`: `.venv/Scripts/python.exe -m pytest`.
- GUI changes in `budget_app.py` have no pytest coverage by established convention (Tkinter has no headless test harness here). Verify each with a one-off headless smoke script: construct `App` directly against a **sandboxed** `profiles.APP_DIR` (a fresh `tempfile.mkdtemp()`, never the real `Profiles/` folder), drive the tab/dialog in code, assert on state, and mock `tkinter.messagebox` functions that would otherwise block waiting for a click.
- Windows: invoke Python directly as `C:/Users/mateu/AppData/Local/Programs/Python/Python314/python.exe` for one-off scripts (`python3` is not on PATH). The console is cp1252 — prefix smoke-script runs with `PYTHONIOENCODING=utf-8` rather than printing £/emoji characters raw.
- User-facing validation errors in this codebase are plain `ValueError` with a message naming the specific problem — not custom exception classes (matches `apply_transactions_csv`, `set_transaction_splits`, etc. already in `finance_core.py`).
- This repo was just initialized with git specifically to run this plan (root commit `f08b2f7`, real financial data/PDFs/`.venv` excluded via `.gitignore`). Execution happens in an isolated worktree; Commit steps below run for real, one commit per task.

---

## File Structure

| File | Responsibility |
|---|---|
| `ledger/src/finance_core.py` | Modify: categories schema (income kind), `_migrate()`, new `Database` methods (`delete_category`, `add_ignored_subscription`, `remove_ignored_subscription`, `list_ignored_subscriptions`), new module function `income_by_category`, extend `detect_recurring_candidates` |
| `ledger/tests/test_finance_core.py` | Modify: new tests for every item above |
| `ledger/budget_app.py` | Modify: `BudgetsTab` (income card, delete button), `TransactionsTab` (filter toolbar), `RecurringTab` (ignore button), `SettingsTab` (ignored-subscriptions card) |

No new files. Every change is additive to existing files, following existing patterns (migration guards, `Card` widget, `trace_add("write", ...)` live-filtering).

---

## Task 1: Categories table — allow `kind='income'`

**Files:**
- Modify: `ledger/src/finance_core.py:69-74` (schema), `ledger/src/finance_core.py:244-...` (`_migrate`, insert new block after the `debt_cols` guard, i.e. after the existing line `c.execute("ALTER TABLE debts ADD COLUMN custom_payment REAL DEFAULT 0")`)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Produces: `categories.kind` accepts `'income'` in addition to `'need'`/`'want'`/`'saving'`. No new method signatures — `add_category(name, kind, monthly_budget=0)` and `list_categories()` are unchanged and now simply accept/return the new kind value.

**Verified separately:** SQLite can't `ALTER` a `CHECK` constraint, and `DROP TABLE categories` while other tables hold FK references to it fails under `PRAGMA foreign_keys=ON` — confirmed empirically. The fix (SQLite's own documented safe procedure) is `PRAGMA foreign_keys=OFF` → rebuild inside `with conn:` → `PRAGMA foreign_keys=ON`, run **outside** any open transaction (bare `ALTER TABLE` calls earlier in `_migrate()` do not leave one open — also confirmed empirically).

- [ ] **Step 1: Write the failing tests**

Add to `ledger/tests/test_finance_core.py`:

```python
def test_categories_table_allows_income_kind_after_migration(tmp_path):
    db = _db(tmp_path)
    db.add_category("Salary", "income", 0)
    cats = {c["name"]: c for c in db.list_categories()}
    assert cats["Salary"]["kind"] == "income"
    db.close()


def test_categories_migration_preserves_existing_rows_ids_and_is_idempotent(tmp_path):
    path = str(tmp_path / "reopen.db")
    db = Database(path)
    db.add_category("Groceries", "need", 200)
    before = {c["name"]: (c["id"], c["kind"], c["monthly_budget"]) for c in db.list_categories()}
    db.close()

    # Reopening re-runs _migrate() against an already-migrated file — must no-op cleanly.
    db2 = Database(path)
    after = {c["name"]: (c["id"], c["kind"], c["monthly_budget"]) for c in db2.list_categories()}
    assert after == before
    db2.add_category("Salary", "income", 0)  # still works after a second migration pass
    assert any(c["kind"] == "income" for c in db2.list_categories())
    db2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `ledger/`): `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k income_kind_after_migration -v`
Expected: FAIL with `sqlite3.IntegrityError: CHECK constraint failed: kind IN ('need','want','saving')`

- [ ] **Step 3: Update the schema definition**

In `ledger/src/finance_core.py`, change the `categories` table definition (around line 72):

```python
            kind TEXT NOT NULL CHECK(kind IN ('need','want','saving','income')),
```

- [ ] **Step 4: Add the migration block**

In `_migrate()`, immediately after the existing `debt_cols` block (after `c.execute("ALTER TABLE debts ADD COLUMN custom_payment REAL DEFAULT 0")`), add:

```python
        cat_row = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='categories'"
        ).fetchone()
        if cat_row and "'income'" not in cat_row["sql"]:
            c.execute("PRAGMA foreign_keys=OFF")
            with c:
                c.execute(
                    "CREATE TABLE categories_new ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "name TEXT UNIQUE NOT NULL, "
                    "kind TEXT NOT NULL CHECK(kind IN ('need','want','saving','income')), "
                    "monthly_budget REAL DEFAULT 0)"
                )
                c.execute(
                    "INSERT INTO categories_new(id, name, kind, monthly_budget) "
                    "SELECT id, name, kind, monthly_budget FROM categories"
                )
                c.execute("DROP TABLE categories")
                c.execute("ALTER TABLE categories_new RENAME TO categories")
            c.execute("PRAGMA foreign_keys=ON")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k "income_kind_after_migration or categories_migration" -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite to confirm nothing else broke**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (all existing tests still green — the migration only widens the CHECK constraint and preserves every column/row/id)

- [ ] **Step 7: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: allow an 'income' category kind"
```

---

## Task 2: `income_by_category` aggregation function

**Files:**
- Modify: `ledger/src/finance_core.py` (add module-level function near `top_payees`/`spend_by_kind`, e.g. directly after `spend_by_kind` around line 1776)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Consumes: `Database.transactions_in_month(year, month)` (already returns `category_id`, `category_name`, `category_kind`, `amount`, `currency` per row — confirmed in `finance_core.py:942-954`), `Database.to_reporting(amount, currency)`.
- Produces: `income_by_category(db, year, month) -> list[dict]`, each dict `{"category_id": int, "category_name": str, "total": float}`, sorted by `total` descending. Only includes categories with at least one positive transaction that month. Used by Task 5 (BudgetsTab Income card).

- [ ] **Step 1: Write the failing test**

```python
def test_income_by_category_totals_this_months_positive_transactions(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_category("Salary", "income", 0)
    db.add_category("Groceries", "need", 200)
    salary_id = next(c["id"] for c in db.list_categories() if c["name"] == "Salary")
    groceries_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries")
    db.add_transaction("2026-08-01", "Employer", salary_id, 2000.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-08-05", "Employer", salary_id, 500.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-08-10", "Tesco", groceries_id, -50.0, "GBP", account_id=acc_id)
    db.add_transaction("2026-07-01", "Employer", salary_id, 999.0, "GBP", account_id=acc_id)  # different month

    result = income_by_category(db, 2026, 8)

    assert len(result) == 1
    assert result[0]["category_id"] == salary_id
    assert result[0]["category_name"] == "Salary"
    assert result[0]["total"] == pytest.approx(2500.0)
    db.close()
```

Add `income_by_category` to the import block at the top of `test_finance_core.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k income_by_category -v`
Expected: FAIL with `ImportError: cannot import name 'income_by_category'`

- [ ] **Step 3: Implement**

Add directly after `spend_by_kind` in `finance_core.py`:

```python
def income_by_category(db: Database, year, month):
    """This month's income total per income-kind category, in reporting
    currency — feeds the Budgets tab's Income card. Labeling only, no
    budget/target framing: 'over budget' doesn't apply to income."""
    totals = {}
    for t in db.transactions_in_month(year, month):
        if t["amount"] <= 0 or t["category_kind"] != "income":
            continue
        entry = totals.setdefault(t["category_id"], {
            "category_id": t["category_id"], "category_name": t["category_name"], "total": 0.0,
        })
        entry["total"] += db.to_reporting(t["amount"], t["currency"])
    return sorted(totals.values(), key=lambda r: -r["total"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k income_by_category -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: add income_by_category aggregation"
```

---

## Task 3: `Database.delete_category` (blocked if in use)

**Files:**
- Modify: `ledger/src/finance_core.py` (add method directly after `update_category`, around line 528)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Produces: `Database.delete_category(category_id) -> None`. Raises `ValueError` (message names which table(s) and how many rows) if `transactions`, `transaction_splits`, or `recurring` reference the category. Deletes the row otherwise. Used by Task 5 (BudgetsTab Delete button).

- [ ] **Step 1: Write the failing tests**

```python
def test_delete_category_removes_an_unused_category(tmp_path):
    db = _db(tmp_path)
    db.add_category("Unused", "want", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Unused")

    db.delete_category(cat_id)

    assert cat_id not in {c["id"] for c in db.list_categories()}
    db.close()


def test_delete_category_blocked_when_a_transaction_references_it(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_category("Groceries", "need", 200)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries")
    db.add_transaction("2026-08-10", "Tesco", cat_id, -50.0, "GBP", account_id=acc_id)

    with pytest.raises(ValueError, match="transaction"):
        db.delete_category(cat_id)
    assert cat_id in {c["id"] for c in db.list_categories()}
    db.close()


def test_delete_category_blocked_when_a_recurring_item_references_it(tmp_path):
    db = _db(tmp_path)
    db.add_category("Rent", "need", 800)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Rent")
    db.add_recurring("Rent", "Landlord", cat_id, -800.0, "GBP", "monthly", "2026-09-01")

    with pytest.raises(ValueError, match="recurring"):
        db.delete_category(cat_id)
    db.close()


def test_delete_category_blocked_when_a_split_references_it(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_category("Groceries", "need", 200)
    db.add_category("Household", "want", 100)
    groceries_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries")
    household_id = next(c["id"] for c in db.list_categories() if c["name"] == "Household")
    db.add_transaction("2026-08-10", "Tesco", groceries_id, -50.0, "GBP", account_id=acc_id)
    tx_id = db.list_transactions()[0]["id"]
    db.set_transaction_splits(tx_id, [
        {"category_id": groceries_id, "amount": -30.0, "note": ""},
        {"category_id": household_id, "amount": -20.0, "note": ""},
    ])

    with pytest.raises(ValueError, match="split"):
        db.delete_category(household_id)
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k delete_category -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'delete_category'`

- [ ] **Step 3: Implement**

Add directly after `update_category` in `finance_core.py`:

```python
    def delete_category(self, category_id):
        tx_count = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        split_count = self.conn.execute(
            "SELECT COUNT(*) FROM transaction_splits WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        rec_count = self.conn.execute(
            "SELECT COUNT(*) FROM recurring WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        if tx_count or split_count or rec_count:
            parts = []
            if tx_count:
                parts.append(f"{tx_count} transaction(s)")
            if split_count:
                parts.append(f"{split_count} transaction split(s)")
            if rec_count:
                parts.append(f"{rec_count} recurring item(s)")
            raise ValueError(
                "Cannot delete category — still used by " + ", ".join(parts) +
                ". Recategorize them first."
            )
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k delete_category -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: add Database.delete_category, blocked while in use"
```

---

## Task 4: Ignored subscriptions (table, CRUD, detector integration)

**Files:**
- Modify: `ledger/src/finance_core.py` — schema (add table after `recurring`, around line 177), new `Database` methods (add after `list_recurring`, around line 1390s), `detect_recurring_candidates` (around line 1699-1736)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Produces:
  - `Database.add_ignored_subscription(payee, date=None) -> None` (case-insensitive dedup; `date` defaults to today, ISO string)
  - `Database.remove_ignored_subscription(payee) -> None` (case-insensitive match)
  - `Database.list_ignored_subscriptions() -> list[Row]` — each row has `payee`, `dismissed_date`, ordered newest-dismissed-first
  - `detect_recurring_candidates` excludes any payee present in `list_ignored_subscriptions()` (case-insensitive), same as its existing "already tracked in `recurring`" exclusion
- Used by Task 7 (RecurringTab Ignore button, SettingsTab Ignored Subscriptions card)

- [ ] **Step 1: Write the failing tests**

```python
def test_add_ignored_subscription_is_case_insensitively_deduped(tmp_path):
    db = _db(tmp_path)
    db.add_ignored_subscription("Netflix")
    db.add_ignored_subscription("netflix")
    assert len(db.list_ignored_subscriptions()) == 1
    db.close()


def test_remove_ignored_subscription_deletes_it_case_insensitively(tmp_path):
    db = _db(tmp_path)
    db.add_ignored_subscription("Netflix")
    db.remove_ignored_subscription("netflix")
    assert db.list_ignored_subscriptions() == []
    db.close()


def test_detect_recurring_candidates_excludes_ignored_payees(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    for d in ("2026-06-01", "2026-07-01", "2026-08-01"):
        db.add_transaction(d, "Spotify", None, -9.99, "GBP", account_id=acc_id)

    assert len(detect_recurring_candidates(db)) == 1

    db.add_ignored_subscription("Spotify")
    assert detect_recurring_candidates(db) == []
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k "ignored_subscription" -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'add_ignored_subscription'`

- [ ] **Step 3: Add the schema table**

In `_create_schema()`'s `executescript`, directly after the `recurring` table definition (before `roundups`):

```sql
        CREATE TABLE IF NOT EXISTS ignored_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payee TEXT NOT NULL,
            dismissed_date TEXT NOT NULL
        );
```

- [ ] **Step 4: Add the CRUD methods**

Add directly after `list_recurring` in `finance_core.py`:

```python
    def add_ignored_subscription(self, payee, date=None):
        date = date or datetime.date.today().isoformat()
        existing = self.conn.execute(
            "SELECT id FROM ignored_subscriptions WHERE LOWER(payee)=LOWER(?)", (payee,)
        ).fetchone()
        if existing:
            return
        self.conn.execute(
            "INSERT INTO ignored_subscriptions(payee, dismissed_date) VALUES (?, ?)",
            (payee, date),
        )
        self.conn.commit()

    def remove_ignored_subscription(self, payee):
        self.conn.execute(
            "DELETE FROM ignored_subscriptions WHERE LOWER(payee)=LOWER(?)", (payee,)
        )
        self.conn.commit()

    def list_ignored_subscriptions(self):
        return self.conn.execute(
            "SELECT * FROM ignored_subscriptions ORDER BY dismissed_date DESC"
        ).fetchall()
```

- [ ] **Step 5: Wire the exclusion into `detect_recurring_candidates`**

In `finance_core.py`, change:

```python
    known_payees = {r["payee"].strip().lower() for r in db.list_recurring(active_only=True) if r["payee"]}
```

to:

```python
    known_payees = {r["payee"].strip().lower() for r in db.list_recurring(active_only=True) if r["payee"]}
    ignored_payees = {r["payee"].strip().lower() for r in db.list_ignored_subscriptions()}
```

and change:

```python
        if payee_key in known_payees or len(txs) < min_occurrences:
```

to:

```python
        if payee_key in known_payees or payee_key in ignored_payees or len(txs) < min_occurrences:
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k "ignored_subscription" -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (all tests green)

- [ ] **Step 8: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: add dismissible (ignorable) subscription suggestions"
```

---

## Task 5: BudgetsTab — income card + delete category button

**Files:**
- Modify: `ledger/budget_app.py:46-57` (import `income_by_category`), `ledger/budget_app.py:1488-1604` (`BudgetsTab`)
- Smoke test: throwaway script, run via Bash, not committed to the repo

**Interfaces:**
- Consumes: `income_by_category(db, year, month)` (Task 2), `Database.delete_category(category_id)` (Task 3).
- Produces: no new public interface — GUI-only. `BudgetsTab.add_category` unchanged; `BudgetsTab._delete_category(cat_id, name)` is new (internal).

**Depends on:** Task 1 (income kind), Task 2, Task 3.

- [ ] **Step 1: Add `income_by_category` to the import block**

In `budget_app.py`, change:

```python
    budget_run_rate, categories_over_threshold, top_payees, daily_spend_totals,
    detect_recurring_candidates, refresh_profile_csvs, apply_profile_csvs,
)
```

to:

```python
    budget_run_rate, categories_over_threshold, top_payees, daily_spend_totals,
    detect_recurring_candidates, refresh_profile_csvs, apply_profile_csvs,
    income_by_category,
)
```

- [ ] **Step 2: Add `"income"` to the Add Category form's kind combobox**

In `BudgetsTab._build()`, change:

```python
        ttk.Combobox(add_frame, textvariable=self.new_kind, values=["need", "want", "saving"],
                     width=10, state="readonly").grid(row=0, column=1, padx=4)
```

to:

```python
        ttk.Combobox(add_frame, textvariable=self.new_kind, values=["need", "want", "saving", "income"],
                     width=10, state="readonly").grid(row=0, column=1, padx=4)
```

- [ ] **Step 3: Bucket income categories in `refresh()` and add the Delete button to existing rows**

In `BudgetsTab.refresh()`, change:

```python
        groups = {"need": [], "want": [], "saving": []}
        for cat in db.list_categories():
            groups[cat["kind"]].append(cat)
```

to:

```python
        groups = {"need": [], "want": [], "saving": [], "income": []}
        for cat in db.list_categories():
            groups[cat["kind"]].append(cat)
        income_totals = {r["category_id"]: r["total"] for r in income_by_category(db, y, m)}
```

Then, inside the existing `for kind in ("need", "want", "saving"):` loop, directly after the existing `edit_row`/`budget_var`/`ttk.Entry`/`ttk.Button(edit_row, text="Set Budget", ...)` block, add:

```python
                ttk.Button(edit_row, text="Delete",
                           command=lambda cid=cat["id"], name=cat["name"]:
                               self._delete_category(cid, name)).pack(side="left", padx=4)
```

- [ ] **Step 4: Render the Income card after the need/want/saving loop**

Directly after the closing of the `for kind in ("need", "want", "saving"):` loop (end of the `refresh()` method body as it currently stands), add:

```python
        income_frame = Card(self.canvas_frame, title="Income")
        income_frame.grid(row=0, column=col, sticky="nsew", padx=6)
        self.canvas_frame.columnconfigure(col, weight=1)
        if not groups["income"]:
            ttk.Label(income_frame, text="No income categories yet.",
                      style="CardDim.TLabel").pack(anchor="w")
        for cat in groups["income"]:
            total = income_totals.get(cat["id"], 0.0)
            row = ttk.Frame(income_frame, style="Card.TFrame")
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=f"{cat['name']}: {fmt_money(total, cur)}",
                      style="Card.TLabel").pack(side="left")
            ttk.Button(row, text="Delete",
                       command=lambda cid=cat["id"], name=cat["name"]:
                           self._delete_category(cid, name)).pack(side="right")
```

- [ ] **Step 5: Add the `_delete_category` method**

Directly after `_set_budget` in `BudgetsTab`:

```python
    def _delete_category(self, cat_id, name):
        if not messagebox.askyesno("Delete Category", f"Delete '{name}'?"):
            return
        try:
            self.app.db.delete_category(cat_id)
        except ValueError as e:
            messagebox.showerror("Cannot Delete", str(e))
            return
        self.app.refresh_all()
```

- [ ] **Step 6: Write and run a headless smoke script**

Create `$CLAUDE_JOB_DIR/tmp/smoke_budgets_tab.py`:

```python
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger")
sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger\src")

import profiles
profiles.APP_DIR = tempfile.mkdtemp()

import budget_app

profile = profiles.create_profile("Smoke Budgets")

with patch("tkinter.messagebox.askyesno", return_value=True), \
     patch("tkinter.messagebox.showerror") as mock_error:
    app = budget_app.App(profile)
    db = app.db

    db.add_category("Salary", "income", 0)
    db.add_category("Unused", "want", 0)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    salary_id = next(c["id"] for c in db.list_categories() if c["name"] == "Salary")
    unused_id = next(c["id"] for c in db.list_categories() if c["name"] == "Unused")
    db.add_transaction(app.today.isoformat(), "Employer", salary_id, 2000.0, "GBP", account_id=acc_id)

    app.show_page("budgets")
    budgets_tab = app.pages["budgets"]
    budgets_tab.refresh()

    income_cards = [w for w in budgets_tab.canvas_frame.winfo_children()
                    if isinstance(w, budget_app.Card) and w.cget("text") == "Income"]
    assert len(income_cards) == 1, "Income card not rendered"

    # Delete an unused category directly (bypassing the button click) and confirm it's gone
    db.delete_category(unused_id)
    assert unused_id not in {c["id"] for c in db.list_categories()}

    # Deleting a category still in use raises, and the tab's own handler surfaces it via messagebox
    budgets_tab._delete_category(salary_id, "Salary")
    assert mock_error.called, "_delete_category did not report the in-use error"
    assert salary_id in {c["id"] for c in db.list_categories()}, "in-use category was deleted anyway"

    app.db.close()
    print("SMOKE TEST PASSED")
```

Run: `PYTHONIOENCODING=utf-8 "C:/Users/mateu/AppData/Local/Programs/Python/Python314/python.exe" "$CLAUDE_JOB_DIR/tmp/smoke_budgets_tab.py"`
Expected: `SMOKE TEST PASSED`, no traceback

- [ ] **Step 7: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: BudgetsTab income card and delete-category button"
```

---

## Task 6: TransactionsTab — filters (account, category, currency, date range, amount range)

**Files:**
- Modify: `ledger/budget_app.py:1046-1067` (toolbar, `_build()`), `ledger/budget_app.py:1197-1227` (`refresh()`)
- Smoke test: throwaway script, run via Bash, not committed to the repo

**Interfaces:**
- Produces: no new public interface — GUI-only, filters reuse `Database.list_transactions()` already called by `refresh()`. New internal method `TransactionsTab.clear_filters()`.

**Depends on:** nothing new (independent of Tasks 1-4).

- [ ] **Step 1: Add the filter toolbar row in `_build()`**

Directly after the existing toolbar block (after `ttk.Button(toolbar, text="Export Full CSV…", ...)` and its `.pack(side="right", padx=6)`), before `list_frame = ttk.Frame(list_card, style="Card.TFrame")`, add:

```python
        filter_bar = ttk.Frame(list_card, style="Card.TFrame")
        filter_bar.pack(fill="x", pady=(0, 8))

        ttk.Label(filter_bar, text="Account", style="CardDim.TLabel").pack(side="left")
        self.filter_account_var = tk.StringVar()
        self.filter_account_combo = ttk.Combobox(filter_bar, textvariable=self.filter_account_var,
                                                  width=14, state="readonly")
        self.filter_account_combo.pack(side="left", padx=(4, 12))
        self.filter_account_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Category", style="CardDim.TLabel").pack(side="left")
        self.filter_category_var = tk.StringVar()
        self.filter_category_combo = ttk.Combobox(filter_bar, textvariable=self.filter_category_var,
                                                   width=14, state="readonly")
        self.filter_category_combo.pack(side="left", padx=(4, 12))
        self.filter_category_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Currency", style="CardDim.TLabel").pack(side="left")
        self.filter_currency_var = tk.StringVar()
        self.filter_currency_combo = ttk.Combobox(filter_bar, textvariable=self.filter_currency_var,
                                                   width=8, state="readonly")
        self.filter_currency_combo.pack(side="left", padx=(4, 12))
        self.filter_currency_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Date from", style="CardDim.TLabel").pack(side="left")
        self.filter_date_from_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_date_from_var, width=10).pack(
            side="left", padx=(4, 6))
        ttk.Label(filter_bar, text="to", style="CardDim.TLabel").pack(side="left")
        self.filter_date_to_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_date_to_var, width=10).pack(
            side="left", padx=(4, 12))
        self.filter_date_from_var.trace_add("write", lambda *a: self.refresh())
        self.filter_date_to_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Amount min", style="CardDim.TLabel").pack(side="left")
        self.filter_amount_min_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_amount_min_var, width=8).pack(
            side="left", padx=(4, 6))
        ttk.Label(filter_bar, text="max", style="CardDim.TLabel").pack(side="left")
        self.filter_amount_max_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_amount_max_var, width=8).pack(
            side="left", padx=(4, 12))
        self.filter_amount_min_var.trace_add("write", lambda *a: self.refresh())
        self.filter_amount_max_var.trace_add("write", lambda *a: self.refresh())

        ttk.Button(filter_bar, text="Clear Filters", command=self.clear_filters).pack(side="left")
```

- [ ] **Step 2: Add `clear_filters`**

Directly after `_build()` (or anywhere in the class body):

```python
    def clear_filters(self):
        self.filter_account_var.set("")
        self.filter_category_var.set("")
        self.filter_currency_var.set("")
        self.filter_date_from_var.set("")
        self.filter_date_to_var.set("")
        self.filter_amount_min_var.set("")
        self.filter_amount_max_var.set("")
```

- [ ] **Step 3: Populate filter dropdown values and apply filters in `refresh()`**

In `TransactionsTab.refresh()`, directly after the existing:

```python
        accs = [a for a in self.app.db.list_accounts() if a["subtype"] != "roundup_pot"]
        self.accounts_by_name = {a["name"]: a for a in accs}
        self.account_combo["values"] = [""] + list(self.accounts_by_name.keys())
```

add:

```python
        self.filter_account_combo["values"] = [""] + list(self.accounts_by_name.keys())
        self.filter_category_combo["values"] = [""] + list(self.categories_by_name.keys())
        all_txs = db.list_transactions()
        self.filter_currency_combo["values"] = [""] + sorted({t["currency"] for t in all_txs})
```

Then change the main loop from `for t in db.list_transactions():` to `for t in all_txs:`, and directly after the existing:

```python
            if query and query not in haystack:
                continue
```

add:

```python
            if self.filter_account_var.get() and t["account_name"] != self.filter_account_var.get():
                continue
            if self.filter_category_var.get() and t["category_name"] != self.filter_category_var.get():
                continue
            if self.filter_currency_var.get() and t["currency"] != self.filter_currency_var.get():
                continue
            date_from = self.filter_date_from_var.get().strip()
            if date_from and t["date"] < date_from:
                continue
            date_to = self.filter_date_to_var.get().strip()
            if date_to and t["date"] > date_to:
                continue
            amt_min = self.filter_amount_min_var.get().strip()
            if amt_min:
                try:
                    if t["amount"] < float(amt_min):
                        continue
                except ValueError:
                    pass
            amt_max = self.filter_amount_max_var.get().strip()
            if amt_max:
                try:
                    if t["amount"] > float(amt_max):
                        continue
                except ValueError:
                    pass
```

- [ ] **Step 4: Write and run a headless smoke script**

Create `$CLAUDE_JOB_DIR/tmp/smoke_transactions_filters.py`:

```python
import sys
import tempfile

sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger")
sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger\src")

import profiles
profiles.APP_DIR = tempfile.mkdtemp()

import budget_app

profile = profiles.create_profile("Smoke Filters")
app = budget_app.App(profile)
db = app.db

db.add_account("Checking", "asset", 0.0, currency="GBP")
db.add_account("Savings", "asset", 0.0, currency="GBP")
checking_id = next(a["id"] for a in db.list_accounts() if a["name"] == "Checking")
savings_id = next(a["id"] for a in db.list_accounts() if a["name"] == "Savings")
db.add_category("Groceries", "need", 200)
groceries_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries")

db.add_transaction("2026-08-01", "Tesco", groceries_id, -50.0, "GBP", account_id=checking_id)
db.add_transaction("2026-08-02", "Sainsburys", groceries_id, -20.0, "GBP", account_id=savings_id)
db.add_transaction("2026-08-03", "Biedronka", groceries_id, -30.0, "PLN", account_id=checking_id)

app.show_page("transactions")
tx_tab = app.pages["transactions"]
tx_tab.refresh()
assert len(tx_tab.tree.get_children()) == 3, "expected 3 unfiltered rows"

tx_tab.filter_account_var.set("Checking")
assert len(tx_tab.tree.get_children()) == 2, "account filter did not narrow to 2 rows"

tx_tab.filter_currency_var.set("PLN")
assert len(tx_tab.tree.get_children()) == 1, "combined account+currency filter did not narrow to 1 row"

tx_tab.clear_filters()
assert len(tx_tab.tree.get_children()) == 3, "clear_filters did not restore all rows"

app.db.close()
print("SMOKE TEST PASSED")
```

Run: `PYTHONIOENCODING=utf-8 "C:/Users/mateu/AppData/Local/Programs/Python/Python314/python.exe" "$CLAUDE_JOB_DIR/tmp/smoke_transactions_filters.py"`
Expected: `SMOKE TEST PASSED`, no traceback

- [ ] **Step 5: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: TransactionsTab filter toolbar (account, category, currency, date, amount)"
```

---

## Task 7: RecurringTab ignore button + SettingsTab ignored-subscriptions card

**Files:**
- Modify: `ledger/budget_app.py:1756-1767` (`RecurringTab.refresh()`, detected-candidates loop), `ledger/budget_app.py:3100-3115` area (`SettingsTab._build()`), `ledger/budget_app.py:3286-3313` (`SettingsTab.refresh()`)
- Smoke test: throwaway script, run via Bash, not committed to the repo

**Interfaces:**
- Consumes: `Database.add_ignored_subscription`, `Database.remove_ignored_subscription`, `Database.list_ignored_subscriptions` (Task 4).
- Produces: no new public interface — GUI-only. New internal methods `RecurringTab._ignore_candidate(cand)`, `SettingsTab._unignore_subscription(payee)`.

**Depends on:** Task 4.

- [ ] **Step 1: Add the Ignore button to each detected-candidate row**

In `RecurringTab.refresh()`, change:

```python
                ttk.Label(row, text=text, style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Add to Recurring",
                           command=lambda c=cand: self._prefill_from_candidate(c)).pack(side="right")
```

to:

```python
                ttk.Label(row, text=text, style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Add to Recurring",
                           command=lambda c=cand: self._prefill_from_candidate(c)).pack(side="right")
                ttk.Button(row, text="Ignore",
                           command=lambda c=cand: self._ignore_candidate(c)).pack(side="right", padx=6)
```

- [ ] **Step 2: Add `_ignore_candidate` to `RecurringTab`**

Directly after `_prefill_from_candidate`:

```python
    def _ignore_candidate(self, cand):
        self.app.db.add_ignored_subscription(cand["payee"])
        self.refresh()
```

- [ ] **Step 3: Add the "Ignored Subscriptions" card to `SettingsTab._build()`**

Directly after the existing `nav_card` block ends (after `ttk.Button(nav_card, text="Save Navigation", ...).pack(anchor="w", pady=(8, 0))`), before `profile_card = Card(self, title="Profile")`, add:

```python
        ignored_subs_card = Card(self, title="Ignored Subscriptions")
        ignored_subs_card.pack(fill="x", pady=(0, 10))
        ttk.Label(ignored_subs_card,
                  text="Dismissed from the Recurring tab's Detected Subscriptions list.",
                  style="CardDim.TLabel").pack(anchor="w")
        self.ignored_subs_frame = ttk.Frame(ignored_subs_card, style="Card.TFrame")
        self.ignored_subs_frame.pack(fill="x", pady=(6, 0))
```

- [ ] **Step 4: Populate it in `SettingsTab.refresh()`**

Directly after the existing:

```python
        self.signed_in_label.config(text=f"Signed in as: {self.app.profile['name']}")
```

add:

```python
        for w in self.ignored_subs_frame.winfo_children():
            w.destroy()
        ignored = db.list_ignored_subscriptions()
        if not ignored:
            ttk.Label(self.ignored_subs_frame, text="None ignored.",
                      style="CardDim.TLabel").pack(anchor="w")
        for row in ignored:
            r = ttk.Frame(self.ignored_subs_frame, style="Card.TFrame")
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=f"{row['payee']} (dismissed {row['dismissed_date']})",
                      style="Card.TLabel").pack(side="left")
            ttk.Button(r, text="Un-ignore",
                       command=lambda p=row["payee"]: self._unignore_subscription(p)).pack(side="right")
```

- [ ] **Step 5: Add `_unignore_subscription` to `SettingsTab`**

```python
    def _unignore_subscription(self, payee):
        self.app.db.remove_ignored_subscription(payee)
        self.app.refresh_all()
```

- [ ] **Step 6: Write and run a headless smoke script**

Create `$CLAUDE_JOB_DIR/tmp/smoke_ignore_subscriptions.py`:

```python
import sys
import tempfile

sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger")
sys.path.insert(0, r"C:\Users\mateu\PycharmProjects\Budget_Tracker\ledger\src")

import profiles
profiles.APP_DIR = tempfile.mkdtemp()

import budget_app

profile = profiles.create_profile("Smoke Ignore")
app = budget_app.App(profile)
db = app.db

db.add_account("Checking", "asset", 0.0, currency="GBP")
acc_id = db.list_accounts()[0]["id"]
for d in ("2026-06-01", "2026-07-01", "2026-08-01"):
    db.add_transaction(d, "Spotify", None, -9.99, "GBP", account_id=acc_id)

app.show_page("recurring")
recurring_tab = app.pages["recurring"]
recurring_tab.refresh()

from finance_core import detect_recurring_candidates
candidates = detect_recurring_candidates(db)
assert len(candidates) == 1, "expected Spotify to be detected before ignoring"

recurring_tab._ignore_candidate(candidates[0])
assert detect_recurring_candidates(db) == [], "candidate still detected after being ignored"

app.show_page("settings")
settings_tab = app.pages["settings"]
settings_tab.refresh()
labels = [w.cget("text") for frame in settings_tab.ignored_subs_frame.winfo_children()
          for w in frame.winfo_children() if isinstance(w, budget_app.ttk.Label)]
assert any("Spotify" in t for t in labels), "Ignored Subscriptions card did not list Spotify"

settings_tab._unignore_subscription("Spotify")
assert len(detect_recurring_candidates(db)) == 1, "un-ignore did not restore the candidate"

app.db.close()
print("SMOKE TEST PASSED")
```

Run: `PYTHONIOENCODING=utf-8 "C:/Users/mateu/AppData/Local/Programs/Python/Python314/python.exe" "$CLAUDE_JOB_DIR/tmp/smoke_ignore_subscriptions.py"`
Expected: `SMOKE TEST PASSED`, no traceback

- [ ] **Step 7: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: dismiss/un-ignore Detected Subscriptions suggestions"
```

---

## Final check

- [ ] Run the full test suite once more from `ledger/`: `.venv/Scripts/python.exe -m pytest` — expect all tests green, count increased by the new tests added in Tasks 1-4.
- [ ] Re-run all four smoke scripts from Tasks 5-7 in sequence to confirm no cross-task regression (e.g. Task 6's filter changes didn't disturb Task 5's Income card, both live in the same file).
- [ ] Manually open the real app (`cd ledger && python3 budget_app.py`, or the Windows Python path) against the `Matt_loaded` or `matt` profile and click through: add an income category, categorize a salary transaction, confirm the Income card shows the total; delete an unused category; delete a category still in use and confirm the block message; filter the Transactions list by account/category/currency/date/amount; ignore a detected subscription and confirm it disappears, then un-ignore it from Settings. This is the hands-on check the headless smoke scripts can't replace (no screenshot tooling for native Tkinter in this environment).
