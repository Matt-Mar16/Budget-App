# "Ultimate" Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give THE LEDGER's Dashboard a single new on-demand recurring-post
capability, a "Needs Attention" action card, a Quick Actions row, and a
customizable (drag-reorder + show/hide) section layout.

**Architecture:** One new `Database` capability
(`post_recurring_item`/`_post_recurring_once_nocommit`) plus one new
settings-backed layout primitive (`get_dashboard_layout`/
`set_dashboard_layout`/`resolve_dashboard_layout`) in the existing
`finance_core.py`/`budget_app.py` layering. Everything else is `DashboardTab`
being rebuilt around six independently reorderable/hideable sections, three
of which (Needs Attention, Quick Actions) are new content wired to already-
existing `Database`/module-level functions — no new data model beyond the
layout setting itself.

**Tech Stack:** Python stdlib only (`tkinter`, `sqlite3`, `json`) — no new
dependencies, matching this project's existing constraint.

**Spec:** `docs/superpowers/specs/2026-08-14-dashboard-ultimate-design.md`

## Global Constraints

- Stdlib-only: `ledger/budget_app.py` and `ledger/src/finance_core.py` take
  no third-party dependencies. `json` is stdlib, so the new settings blob is
  fine.
- TDD for every `finance_core.py` change and every pure (non-Tkinter)
  `budget_app.py` function: write the failing test first.
- Any new helper that could be tested without a live Tkinter event loop must
  stay testable that way — e.g. the over-budget confirmation in
  `submit_new_transaction()` (Task 4) takes an injectable callable instead of
  calling `messagebox.askyesno` directly, so a test can supply a fake instead
  of driving a real modal dialog.
- Pure Tkinter widget-wiring changes (Tasks 5–8) are **not** pytest-covered —
  this codebase verifies GUI wiring with a disposable headless smoke script
  (construct `App` against a sandboxed `profiles.APP_DIR`, drive the tab in
  code, assert on state, then delete the script) rather than a Tkinter test
  suite, since there's no screenshot tooling for native Tkinter here. Each
  such task's "test" step is a smoke script, not a `pytest` file.
- New dialogs use `make_scrollable_toplevel()` (`budget_app.py:271`), like
  every other dialog in the app. New primary-action buttons use
  `"Accent.TButton"`; new additive/creation buttons use `"Good.TButton"`
  (`theme.py` — see CLAUDE.md's "Button color meaning").
- Any new recurring-item transaction insert must apply the exact same
  balance/round-up effects `generate_due_recurring` already applies — no
  second, divergent posting code path.
- Only create git commits as directed by the step-by-step instructions below
  (this plan's own commit steps) — no extra unrequested commits.

---

## Task 1: `Database.post_recurring_item` — post one recurring item on demand

**Files:**
- Modify: `ledger/src/finance_core.py:1409-1444` (`generate_due_recurring`)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Consumes: nothing new — reuses existing `self.get_account`,
  `self._apply_balance_effect_nocommit`, `self._apply_roundup_nocommit`,
  `self._advance_date`, `self.conn`.
- Produces: `Database._post_recurring_once_nocommit(self, r, post_date) -> int`
  (returns the new transaction id; caller wraps in `with self.conn:`) and
  `Database.post_recurring_item(self, recurring_id) -> int` (returns the new
  transaction id; raises `ValueError` if `recurring_id` doesn't match an
  active recurring item). No `today` parameter: the transaction is always
  dated to the item's own `next_date` regardless of when the button is
  clicked (see spec), so a `today` argument would be accepted and silently
  ignored — dropped instead of kept as dead API surface. Task 7's Needs
  Attention "Post Now" button calls `post_recurring_item(recurring_id)`.

- [ ] **Step 1: Write the failing tests**

Add to `ledger/tests/test_finance_core.py` (near the existing
`test_generate_due_recurring_*` tests, e.g. after line 497):

```python
def test_post_recurring_item_posts_once_even_if_not_yet_due(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 1000.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_recurring("Netflix", "Netflix", None, -15.0, "GBP", "monthly",
                      "2026-09-20", account_id=acc_id)
    recurring_id = db.list_recurring()[0]["id"]

    # next_date (2026-09-20) hasn't arrived yet -- post_recurring_item must
    # still post, unlike generate_due_recurring which would skip it.
    tx_id = db.post_recurring_item(recurring_id)

    assert isinstance(tx_id, int)
    tx = db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    assert tx["amount"] == -15.0
    assert tx["date"] == "2026-09-20"  # dated to the item's own next_date, not "today"
    assert db.get_account(acc_id)["balance"] == pytest.approx(985.0)
    db.close()


def test_post_recurring_item_advances_next_date_like_generate_due_recurring(tmp_path):
    db = _db(tmp_path)
    db.add_recurring("Netflix", "Netflix", None, -15.0, "GBP", "monthly", "2026-09-20")
    recurring_id = db.list_recurring()[0]["id"]

    db.post_recurring_item(recurring_id)

    item = db.list_recurring()[0]
    assert item["next_date"] == "2026-10-20"
    db.close()


def test_post_recurring_item_deactivates_a_once_item_instead_of_advancing(tmp_path):
    db = _db(tmp_path)
    db.add_recurring("Car Insurance Renewal", "Insurer", None, -400.0, "GBP", "once",
                      "2026-09-15")
    recurring_id = db.list_recurring()[0]["id"]

    db.post_recurring_item(recurring_id)

    item = db.list_recurring()[0]
    assert item["active"] == 0
    assert item["next_date"] == "2026-09-15"
    db.close()


def test_post_recurring_item_raises_for_unknown_id(tmp_path):
    db = _db(tmp_path)

    with pytest.raises(ValueError):
        db.post_recurring_item(999999)

    db.close()


def test_post_recurring_item_raises_for_inactive_item(tmp_path):
    db = _db(tmp_path)
    db.add_recurring("Car Insurance Renewal", "Insurer", None, -400.0, "GBP", "once",
                      "2026-09-15")
    recurring_id = db.list_recurring()[0]["id"]
    db.post_recurring_item(recurring_id)  # deactivates it

    with pytest.raises(ValueError):
        db.post_recurring_item(recurring_id)

    db.close()


def test_generate_due_recurring_still_advances_a_custom_frequency_item_after_extraction(tmp_path):
    # Regression check: the shared _post_recurring_once_nocommit extraction
    # must not change generate_due_recurring's existing behavior.
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 2000.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_recurring("Rent", "Landlord", None, -500.0, "GBP", "custom", "2026-01-01",
                      account_id=acc_id, custom_interval_months=4)

    posted = db.generate_due_recurring(today=datetime.date(2026, 1, 5))

    assert len(posted) == 1
    assert db.list_recurring()[0]["next_date"] == "2026-05-01"
    assert db.get_account(acc_id)["balance"] == pytest.approx(1500.0)
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k post_recurring_item -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'post_recurring_item'`

- [ ] **Step 3: Extract the shared helper and add `post_recurring_item`**

Replace `generate_due_recurring` (`ledger/src/finance_core.py:1409-1444`)
with:

```python
    def _post_recurring_once_nocommit(self, r, post_date):
        """Inserts one transaction for recurring item `r`, dated `post_date`,
        with the same balance/round-up effects add_transaction's callers
        get elsewhere. No-commit: caller wraps this in `with self.conn:`.
        Shared by generate_due_recurring (the automatic due-date scan) and
        post_recurring_item (an explicit single-item post on demand) so
        there's exactly one place that knows how a recurring item becomes
        a real transaction."""
        acc = self.get_account(r["account_id"]) if r["account_id"] else None
        cur = self.conn.execute(
            "INSERT INTO transactions(date, payee, category_id, amount, currency, note, account_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (post_date, r["payee"] or r["name"], r["category_id"], r["amount"],
             r["currency"], f"Auto: {r['name']}", r["account_id"]),
        )
        tx_id = cur.lastrowid
        if acc:
            self._apply_balance_effect_nocommit(acc, r["amount"], r["currency"])
        if r["amount"] < 0:
            self._apply_roundup_nocommit(tx_id, post_date, r["amount"])
        return tx_id

    def generate_due_recurring(self, today: Optional[datetime.date] = None):
        """Posts a real transaction for any active recurring item whose next_date
        has arrived, then rolls next_date forward. Safe to call every time the
        app opens / refreshes — it only ever posts each due date once."""
        if today is None:
            today = datetime.date.today()
        posted = []
        with self.conn:
            for r in self.list_recurring(active_only=True):
                guard = 0
                while r["next_date"] <= today.isoformat() and guard < 36:
                    self._post_recurring_once_nocommit(r, r["next_date"])
                    posted.append((r["name"], r["next_date"], r["amount"]))
                    if r["frequency"] == "once":
                        # A one-off planned transaction has no next occurrence --
                        # deactivate instead of advancing, so it posts exactly once.
                        self.conn.execute("UPDATE recurring SET active=0 WHERE id=?", (r["id"],))
                        break
                    new_next = self._advance_date(r["next_date"], r["frequency"],
                                                   custom_interval_months=r["custom_interval_months"])
                    self.conn.execute("UPDATE recurring SET next_date=? WHERE id=?", (new_next, r["id"]))
                    r = dict(r)
                    r["next_date"] = new_next
                    guard += 1
        return posted

    def post_recurring_item(self, recurring_id):
        """Posts recurring item `recurring_id` exactly once, right now --
        unlike generate_due_recurring, this ignores whether next_date has
        actually arrived (it's an explicit user action, e.g. the Dashboard's
        Needs Attention 'Post Now' button on a bill that's upcoming but not
        yet due). Dates the transaction to the item's own next_date (matching
        generate_due_recurring's existing choice) -- not to "today", which is
        why this takes no today parameter: nothing in this method would ever
        read it. Then advances next_date (or deactivates, for a 'once' item)
        the same way generate_due_recurring does. Returns the new transaction
        id. Raises ValueError if recurring_id doesn't match an active
        recurring item."""
        with self.conn:
            r = self.conn.execute(
                "SELECT * FROM recurring WHERE id=? AND active=1", (recurring_id,)
            ).fetchone()
            if r is None:
                raise ValueError(f"No active recurring item with id {recurring_id}")
            tx_id = self._post_recurring_once_nocommit(r, r["next_date"])
            if r["frequency"] == "once":
                self.conn.execute("UPDATE recurring SET active=0 WHERE id=?", (r["id"],))
            else:
                new_next = self._advance_date(r["next_date"], r["frequency"],
                                               custom_interval_months=r["custom_interval_months"])
                self.conn.execute("UPDATE recurring SET next_date=? WHERE id=?", (new_next, r["id"]))
        return tx_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k "recurring" -v`
Expected: PASS (all `recurring`-matching tests, including the pre-existing
`generate_due_recurring` ones — confirms the extraction didn't regress them)

- [ ] **Step 5: Run the full suite**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (baseline was 172 before this plan)

- [ ] **Step 6: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: add Database.post_recurring_item for on-demand single-item posting"
```

---

## Task 2: `Database.get_dashboard_layout` / `set_dashboard_layout`

**Files:**
- Modify: `ledger/src/finance_core.py` (add `import json` near the top;
  add the two new methods near `get_setting`/`set_setting`, `finance_core.py:426-448`)
- Test: `ledger/tests/test_finance_core.py`

**Interfaces:**
- Consumes: `self.get_setting`/`self.set_setting` (`finance_core.py:426-436`).
- Produces: `Database.get_dashboard_layout(self) -> list[dict]` (each dict
  `{"key": str, "visible": bool}`, in saved order; `[]` if nothing saved or
  the stored value is malformed) and `Database.set_dashboard_layout(self,
  layout: list[dict]) -> None` (raises `ValueError` if any entry lacks a
  string `"key"` or boolean `"visible"`). These are a **raw storage layer**
  only — they know nothing about which section keys currently exist in the
  UI; Task 3's `resolve_dashboard_layout()` does that reconciliation.

- [ ] **Step 1: Write the failing tests**

Add to `ledger/tests/test_finance_core.py`:

```python
def test_get_dashboard_layout_is_empty_by_default(tmp_path):
    db = _db(tmp_path)

    assert db.get_dashboard_layout() == []

    db.close()


def test_set_and_get_dashboard_layout_round_trips(tmp_path):
    db = _db(tmp_path)
    layout = [{"key": "hero", "visible": True}, {"key": "flags", "visible": False}]

    db.set_dashboard_layout(layout)

    assert db.get_dashboard_layout() == layout
    db.close()


def test_set_dashboard_layout_rejects_an_entry_missing_a_key(tmp_path):
    db = _db(tmp_path)

    with pytest.raises(ValueError):
        db.set_dashboard_layout([{"visible": True}])

    db.close()


def test_set_dashboard_layout_rejects_a_non_boolean_visible(tmp_path):
    db = _db(tmp_path)

    with pytest.raises(ValueError):
        db.set_dashboard_layout([{"key": "hero", "visible": "yes"}])

    db.close()


def test_get_dashboard_layout_defensively_returns_empty_for_corrupted_setting(tmp_path):
    # simulates a hand-edited or pre-JSON settings row
    db = _db(tmp_path)
    db.set_setting("dashboard_layout", "not json at all")

    assert db.get_dashboard_layout() == []

    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k dashboard_layout -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'get_dashboard_layout'`

- [ ] **Step 3: Add `import json` and the two methods**

Add near the top of `ledger/src/finance_core.py` (alongside the existing
`import sqlite3` / `import datetime` block, around line 10-16):

```python
import json
```

Add right after `get_setting_int` (`ledger/src/finance_core.py:444-448`):

```python
    # ---- Dashboard layout (raw storage only -- see budget_app.resolve_dashboard_layout
    # for reconciliation against the currently-known section keys) ----
    def get_dashboard_layout(self):
        raw = self.get_setting("dashboard_layout", "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for entry in data:
            if (isinstance(entry, dict) and isinstance(entry.get("key"), str)
                    and isinstance(entry.get("visible"), bool)):
                out.append({"key": entry["key"], "visible": entry["visible"]})
        return out

    def set_dashboard_layout(self, layout):
        for entry in layout:
            if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) \
                    or not isinstance(entry.get("visible"), bool):
                raise ValueError(f"Invalid dashboard layout entry: {entry!r}")
        self.set_setting(
            "dashboard_layout",
            json.dumps([{"key": e["key"], "visible": e["visible"]} for e in layout]),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_finance_core.py -k dashboard_layout -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ledger/src/finance_core.py ledger/tests/test_finance_core.py
git commit -m "feat: add Database.get_dashboard_layout/set_dashboard_layout storage"
```

---

## Task 3: `resolve_dashboard_layout()` and the section key/label list

**Files:**
- Modify: `ledger/budget_app.py` (add near `get_hidden_nav_tabs`/
  `set_hidden_nav_tabs`/`visible_nav_groups`, `budget_app.py:511-536`)
- Test: `ledger/tests/test_budget_app.py`

**Interfaces:**
- Consumes: `db.get_dashboard_layout()` / `db.set_dashboard_layout()` (Task 2).
- Produces: `DASHBOARD_SECTIONS: list[tuple[str, str]]`,
  `DASHBOARD_SECTION_KEYS: list[str]`, and
  `resolve_dashboard_layout(db) -> list[dict]` (every key in
  `DASHBOARD_SECTION_KEYS`, in display order, each `{"key", "visible"}` —
  Task 5's `DashboardTab._apply_layout()` and Task 8's Settings card both
  call this).

- [ ] **Step 1: Write the failing tests**

Add to `ledger/tests/test_budget_app.py` (extend the existing `from
budget_app import (...)` at the top to also pull in the new names):

```python
from budget_app import (
    get_hidden_nav_tabs, set_hidden_nav_tabs, visible_nav_groups, NAV_GROUPS, PROTECTED_NAV_KEYS,
    DASHBOARD_SECTION_KEYS, resolve_dashboard_layout,
)
```

Then add:

```python
def test_resolve_dashboard_layout_defaults_to_every_known_key_visible(tmp_path):
    db = _db(tmp_path)

    result = resolve_dashboard_layout(db)

    assert [entry["key"] for entry in result] == DASHBOARD_SECTION_KEYS
    assert all(entry["visible"] for entry in result)
    db.close()


def test_resolve_dashboard_layout_round_trips_a_saved_layout(tmp_path):
    db = _db(tmp_path)
    saved = [{"key": k, "visible": (k != "flags")} for k in DASHBOARD_SECTION_KEYS]
    db.set_dashboard_layout(saved)

    result = resolve_dashboard_layout(db)

    assert result == saved
    db.close()


def test_resolve_dashboard_layout_appends_a_known_key_missing_from_saved_layout(tmp_path):
    db = _db(tmp_path)
    partial = [{"key": k, "visible": True} for k in DASHBOARD_SECTION_KEYS if k != "flags"]
    db.set_dashboard_layout(partial)

    result = resolve_dashboard_layout(db)

    assert result[-1] == {"key": "flags", "visible": True}
    assert {e["key"] for e in result} == set(DASHBOARD_SECTION_KEYS)
    db.close()


def test_resolve_dashboard_layout_drops_an_unknown_saved_key(tmp_path):
    db = _db(tmp_path)
    stale = [{"key": "hero", "visible": True}, {"key": "old_removed_section", "visible": True}]
    db.set_dashboard_layout(stale)

    result = resolve_dashboard_layout(db)

    assert "old_removed_section" not in {e["key"] for e in result}
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_budget_app.py -k dashboard_layout -v`
Expected: FAIL with `ImportError: cannot import name 'DASHBOARD_SECTION_KEYS'`

- [ ] **Step 3: Add the constants and the function**

Add to `ledger/budget_app.py` right after `visible_nav_groups`
(`budget_app.py:527-536`):

```python
DASHBOARD_SECTIONS = [
    ("hero", "Safe to Spend"),
    ("metrics", "Key Metrics"),
    ("quick_actions", "Quick Actions"),
    ("charts", "Charts (Spend Split & Trend)"),
    ("needs_attention", "Needs Attention"),
    ("flags", "Flags & Nudges"),
]
DASHBOARD_SECTION_KEYS = [key for key, _ in DASHBOARD_SECTIONS]


def resolve_dashboard_layout(db):
    """Reconciles the saved dashboard_layout setting against the currently
    known section keys: drops any saved key no longer in DASHBOARD_SECTIONS
    (e.g. a section removed in a later version), appends any known key
    missing from the saved list (e.g. a section added later) as visible, at
    the end. Returns a list of {"key", "visible"} covering every key in
    DASHBOARD_SECTION_KEYS, in display order. Pure function so it's
    unit-testable without Tkinter, matching get_hidden_nav_tabs/
    visible_nav_groups above."""
    saved = db.get_dashboard_layout()
    known = set(DASHBOARD_SECTION_KEYS)
    result = [entry for entry in saved if entry["key"] in known]
    present = {entry["key"] for entry in result}
    for key in DASHBOARD_SECTION_KEYS:
        if key not in present:
            result.append({"key": key, "visible": True})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_budget_app.py -v`
Expected: PASS (whole file, confirming the import-line change didn't break
existing nav tests)

- [ ] **Step 5: Commit**

```bash
git add ledger/budget_app.py ledger/tests/test_budget_app.py
git commit -m "feat: add resolve_dashboard_layout and DASHBOARD_SECTIONS"
```

---

## Task 4: Extract `submit_new_transaction()` from the Transactions inline form

**Files:**
- Modify: `ledger/budget_app.py:1596-1639` (`TransactionsTab.add_transaction`)
- Test: `ledger/tests/test_budget_app.py`

**Interfaces:**
- Consumes: `Database.add_transaction`, `Database.set_transaction_tags`,
  `finance_core.would_exceed_budget`, `App.reporting_currency()`.
- Produces: `submit_new_transaction(app, date, payee, category_name,
  amount_raw, currency, note, account_name, tag_names_raw="",
  confirm_over_budget=None) -> tuple[bool, str | None]`. `confirm_over_budget`
  defaults to `messagebox.askyesno` in production but can be overridden with
  a plain callable in tests — no real Tkinter dialog involved when testing.
  Task 6's new Add Transaction popup dialog calls this exact function.

- [ ] **Step 1: Write the failing tests**

Add to `ledger/tests/test_budget_app.py` (needs `Database` already
imported at the top of the file; add `submit_new_transaction` to the
existing `from budget_app import (...)` line):

```python
from budget_app import (
    get_hidden_nav_tabs, set_hidden_nav_tabs, visible_nav_groups, NAV_GROUPS, PROTECTED_NAV_KEYS,
    DASHBOARD_SECTION_KEYS, resolve_dashboard_layout, submit_new_transaction,
)
```

```python
class _FakeApp:
    """Minimal stand-in for App -- submit_new_transaction only touches
    .db and .reporting_currency(), never any Tkinter widget."""
    def __init__(self, db):
        self.db = db

    def reporting_currency(self):
        return "GBP"


def test_submit_new_transaction_writes_a_valid_transaction(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries", "need")
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Tesco", "Groceries", "-42.50", "GBP", "weekly shop", "")

    assert ok is True
    assert error is None
    tx = db.list_transactions()[0]
    assert tx["payee"] == "Tesco"
    assert tx["amount"] == -42.5
    db.close()


def test_submit_new_transaction_rejects_an_invalid_date(tmp_path):
    db = _db(tmp_path)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(app, "not-a-date", "Tesco", "", "-10", "GBP", "", "")

    assert ok is False
    assert error is not None
    assert db.list_transactions() == []
    db.close()


def test_submit_new_transaction_rejects_a_non_numeric_amount(tmp_path):
    db = _db(tmp_path)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(app, "2026-09-01", "Tesco", "", "abc", "GBP", "", "")

    assert ok is False
    assert error is not None
    assert db.list_transactions() == []
    db.close()


def test_submit_new_transaction_saves_tags(tmp_path):
    db = _db(tmp_path)
    app = _FakeApp(db)

    submit_new_transaction(app, "2026-09-01", "Tesco", "", "-10", "GBP", "", "", "food, weekly")

    tx = db.list_transactions()[0]
    assert set(tx["tags"].split(",")) == {"food", "weekly"} if tx["tags"] else False
    db.close()


def test_submit_new_transaction_asks_before_exceeding_budget_and_respects_decline(tmp_path):
    db = _db(tmp_path)
    cat_id = db.add_category("Dining", "want")
    db.set_category_budget(cat_id, 20.0)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Restaurant", "Dining", "-50", "GBP", "", "",
        confirm_over_budget=lambda *a: False)

    assert ok is False
    assert db.list_transactions() == []
    db.close()


def test_submit_new_transaction_proceeds_when_over_budget_confirmed(tmp_path):
    db = _db(tmp_path)
    cat_id = db.add_category("Dining", "want")
    db.set_category_budget(cat_id, 20.0)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Restaurant", "Dining", "-50", "GBP", "", "",
        confirm_over_budget=lambda *a: True)

    assert ok is True
    assert len(db.list_transactions()) == 1
    db.close()
```

If `Database.list_transactions()` rows don't include a `"tags"` field the
way the test above assumes, adjust that one assertion to whatever
`list_transactions()` actually returns for tags (check
`ledger/src/finance_core.py`'s `list_transactions` implementation) — every
other assertion in this task is independent of that detail.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_budget_app.py -k submit_new_transaction -v`
Expected: FAIL with `ImportError: cannot import name 'submit_new_transaction'`

- [ ] **Step 3: Extract the function, rewire the inline form**

Add a new module-level function to `ledger/budget_app.py`, placed right
after `resolve_dashboard_layout` (end of Task 3's addition):

```python
def submit_new_transaction(app, date, payee, category_name, amount_raw, currency, note,
                            account_name, tag_names_raw="", confirm_over_budget=None):
    """Validates and writes a new transaction -- the exact logic
    TransactionsTab's inline Add form uses, extracted so the Dashboard's
    Add Transaction popup (see DashboardTab.open_add_transaction_dialog)
    can share it instead of re-implementing validation. Returns
    (ok, error_message); error_message is None on success. On success the
    transaction (and any tags) has already been written to app.db -- the
    caller still calls app.refresh_all() afterward, same as before.
    confirm_over_budget defaults to messagebox.askyesno but can be swapped
    for a plain callable in tests, so this function needs no live Tkinter
    event loop to test."""
    if confirm_over_budget is None:
        confirm_over_budget = messagebox.askyesno

    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        return False, "Please use YYYY-MM-DD format."
    try:
        amount = float(amount_raw)
    except ValueError:
        return False, "Amount must be a number (negative for expenses)."

    categories_by_name = {c["name"]: c["id"] for c in app.db.list_categories()}
    accounts_by_name = {a["name"]: a for a in app.db.list_accounts()}
    cat_id = categories_by_name.get(category_name.strip())
    account = accounts_by_name.get(account_name.strip())
    account_id = account["id"] if account else None
    currency = currency.strip().upper() or app.reporting_currency()
    payee = payee.strip()
    note = note.strip()

    if cat_id and amount < 0:
        from finance_core import would_exceed_budget
        exceeds, spent_after, budget = would_exceed_budget(app.db, cat_id, amount, currency)
        if exceeds:
            cur = app.reporting_currency()
            proceed = confirm_over_budget(
                "Over budget",
                f"This would bring '{category_name}' spending to {fmt_money(spent_after, cur)}, "
                f"over its {fmt_money(budget, cur)} monthly budget. Add it anyway?")
            if not proceed:
                return False, None

    tx_id = app.db.add_transaction(date, payee, cat_id, amount, currency, note,
                                    account_id=account_id)
    tag_names = [t.strip() for t in tag_names_raw.split(",") if t.strip()]
    if tag_names:
        app.db.set_transaction_tags(tx_id, tag_names)
    return True, None
```

Then replace `TransactionsTab.add_transaction` (`budget_app.py:1596-1639`)
with a thin wrapper over it:

```python
    def add_transaction(self):
        ok, error = submit_new_transaction(
            self.app, self.date_var.get(), self.payee_var.get(), self.category_var.get(),
            self.amount_var.get(), self.currency_var.get(), self.note_var.get(),
            self.account_var.get(), self.tags_var.get())
        if not ok:
            if error:
                messagebox.showerror("Invalid entry", error)
            return
        self.payee_var.set("")
        self.amount_var.set("")
        self.note_var.set("")
        self.tags_var.set("")
        self.app.refresh_all()
```

Note the previous version showed two *different* `messagebox.showerror`
titles ("Invalid date" / "Invalid amount") for the two validation failures;
`submit_new_transaction` folds both into one `(False, message)` result, so
the wrapper shows one generic "Invalid entry" title with the specific
message as the body — the user-facing text (the message itself) is
unchanged, only the dialog title is now shared between the two cases.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest tests/test_budget_app.py -v`
Expected: PASS

- [ ] **Step 5: Regression-check the inline form with a headless smoke script**

Write `ledger/../smoke_add_transaction.py`-equivalent under a scratch temp
dir (not committed), matching this project's established convention:

```python
import sys, tempfile, datetime
sys.path.insert(0, r"ledger")
sys.path.insert(0, r"ledger/src")
import profiles
profiles.APP_DIR = tempfile.mkdtemp()
import budget_app

app = budget_app.App(profiles.create_profile("smoketest"))
db = app.db
db.add_account("Checking", kind="asset", subtype="checking", currency="GBP", balance=100)
db.add_category("GroceriesXYZ", kind="need")
app.refresh_all()

tx_tab = app.pages["transactions"]
tx_tab.date_var.set(datetime.date.today().isoformat())
tx_tab.payee_var.set("Tesco")
tx_tab.category_var.set("GroceriesXYZ")
tx_tab.amount_var.set("-12.50")
tx_tab.account_var.set("Checking")
tx_tab.add_transaction()

assert len(db.list_transactions()) == 1, "inline Add form must still work after extraction"
print("SMOKE TEST PASSED")
app.destroy()
```

Run it with the project's venv Python, confirm it prints `SMOKE TEST
PASSED`, then delete the script (matches this project's established
"throwaway, never committed" smoke-script convention).

- [ ] **Step 6: Run the full suite**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add ledger/budget_app.py ledger/tests/test_budget_app.py
git commit -m "refactor: extract submit_new_transaction from TransactionsTab.add_transaction"
```

---

## Task 5: Rebuild `DashboardTab` around reorderable/hideable sections

**Files:**
- Modify: `ledger/budget_app.py:826-905` (`DashboardTab._build`) and the top
  of `DashboardTab.refresh` (`budget_app.py:906-911`)

**Interfaces:**
- Consumes: `resolve_dashboard_layout` (Task 3), `enable_drag_reorder`
  (`budget_app.py:130`), `Card`, `metric_cell`, `theme.Fonts`.
- Produces: `DashboardTab.section_frames: dict[str, ttk.Frame]`,
  `DashboardTab._apply_layout()`, `DashboardTab._on_reorder(ordered_keys)`.
  `quick_actions` and `needs_attention` sections exist as empty containers
  in this task (`self.quick_actions_row`, `self.needs_attention_rows_frame`)
  — Task 6 and Task 7 fill them in without touching the layout plumbing
  built here.

- [ ] **Step 1: Replace `_build()`**

Replace `DashboardTab._build` (`budget_app.py:832-904`) with:

```python
    def _build(self):
        c = self.app.c
        self.section_frames = {}
        self.section_handles = {}

        def start_section(key, label):
            outer = ttk.Frame(self)
            handle_row = ttk.Frame(outer)
            handle_row.pack(fill="x")
            handle = ttk.Label(handle_row, text="⠿", style="Dim.TLabel", cursor="fleur")
            handle.pack(side="left")
            ttk.Label(handle_row, text=label, style="Dim.TLabel").pack(side="left", padx=(4, 0))
            self.section_frames[key] = outer
            self.section_handles[key] = handle
            return outer

        # Safe-to-spend hero
        hero_section = start_section("hero", "Safe to Spend")
        hero = Card(hero_section, title="")
        hero.pack(fill="x", pady=(0, 10))
        ttk.Label(hero, text="SAFE TO SPEND / DAY", style="CardDim.TLabel").pack(anchor="w")
        self.safe_to_spend_label = ttk.Label(hero, text="—", style="Hero.TLabel")
        self.safe_to_spend_label.pack(anchor="w")
        self.safe_to_spend_sub = ttk.Label(hero, text="", style="CardDim.TLabel")
        self.safe_to_spend_sub.pack(anchor="w", pady=(4, 0))

        # Metrics grid
        metrics_section = start_section("metrics", "Key Metrics")
        grid = ttk.Frame(metrics_section)
        grid.pack(fill="x", pady=(0, 10))
        self.metric_labels = {}
        metrics = [
            ("Savings Rate", "#9B6BDE"), ("Emergency Fund", "#4AB8C4"),
            ("Debt-to-Income", "#E0A93E"), ("Housing Ratio", "#D46FB0"),
            ("Income (mo.)", c["good"]), ("Expenses (mo.)", c["bad"]),
        ]
        for i, (m, accent) in enumerate(metrics):
            cell, val = metric_cell(grid, m, accent_color=accent)
            cell.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            grid.columnconfigure(i % 3, weight=1)
            self.metric_labels[m] = val

        # Quick Actions -- content added in Task 6
        quick_actions_section = start_section("quick_actions", "Quick Actions")
        qa_card = Card(quick_actions_section, title="Quick Actions")
        qa_card.pack(fill="x", pady=(0, 10))
        self.quick_actions_row = ttk.Frame(qa_card, style="Card.TFrame")
        self.quick_actions_row.pack(fill="x")

        # Charts row: allocation donut + 6-month trend bar chart
        charts_section = start_section("charts", "Charts")
        charts_row = ttk.Frame(charts_section)
        charts_row.pack(fill="x", pady=(0, 10))
        charts_row.columnconfigure(0, weight=1)
        charts_row.columnconfigure(1, weight=2)

        donut_card = Card(charts_row, title="This Month's Spend — Need / Want / Saving")
        donut_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.donut_canvas = tk.Canvas(donut_card, height=200, highlightthickness=0,
                                       bg=c["card"])
        self.donut_canvas.pack(fill="both", expand=True)

        trend_card = Card(charts_row, title="Income vs. Expenses")
        trend_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        range_row = ttk.Frame(trend_card, style="Card.TFrame")
        range_row.pack(fill="x", anchor="e")
        ttk.Label(range_row, text="Range:", style="CardDim.TLabel").pack(side="left")
        self.trend_range_var = tk.StringVar(value="6 months")
        self.trend_range_labels = {
            "6 months": 6, "12 months": 12, "24 months": 24, "36 months": 36,
        }
        trend_range_combo = ttk.Combobox(range_row, textvariable=self.trend_range_var,
                                          values=list(self.trend_range_labels), width=10, state="readonly")
        trend_range_combo.pack(side="left", padx=(4, 0))
        trend_range_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.trend_canvas = tk.Canvas(trend_card, height=200, highlightthickness=0,
                                       bg=c["card"])
        self.trend_canvas.pack(fill="both", expand=True)

        # Needs Attention -- content added in Task 7
        needs_attention_section = start_section("needs_attention", "Needs Attention")
        na_card = Card(needs_attention_section, title="Needs Attention")
        na_card.pack(fill="x", pady=(0, 10))
        self.needs_attention_rows_frame = ttk.Frame(na_card, style="Card.TFrame")
        self.needs_attention_rows_frame.pack(fill="x")

        # Flags panel
        flags_section = start_section("flags", "Flags & Nudges")
        flags_card = Card(flags_section, title="Flags & Nudges")
        flags_card.pack(fill="both", expand=True)
        self.flags_text = tk.Text(flags_card, wrap="word", state="disabled", height=10,
                                   bg=c["card"], fg=c["text"], insertbackground=c["text"],
                                   relief="flat", font=theme.Fonts.body, padx=4, pady=4)
        self.flags_text.pack(fill="both", expand=True)
        self.flags_text.tag_configure("warn", foreground=c["warn"])
        self.flags_text.tag_configure("good", foreground=c["good"])
        self.flags_text.tag_configure("info", foreground=c["accent"])
        self.flags_text.tag_configure("bill", foreground="#6E7FE0")
        self.flags_text.tag_configure("reward", foreground="#E0A93E")
        self.flags_text.tag_configure("idle", foreground="#4AB8C4")

        self._apply_layout()

    def _apply_layout(self):
        layout = resolve_dashboard_layout(self.app.db)
        for entry in layout:
            self.section_frames[entry["key"]].pack_forget()
        for entry in layout:
            if entry["visible"]:
                self.section_frames[entry["key"]].pack(fill="x", pady=5)
        visible_rows = [
            (self.section_handles[e["key"]], self.section_frames[e["key"]], e["key"])
            for e in layout if e["visible"]
        ]
        if visible_rows:
            enable_drag_reorder(visible_rows, self._on_reorder)

    def _on_reorder(self, ordered_keys):
        layout = resolve_dashboard_layout(self.app.db)
        hidden_entries = [e for e in layout if not e["visible"]]
        new_layout = [{"key": k, "visible": True} for k in ordered_keys] + hidden_entries
        self.app.db.set_dashboard_layout(new_layout)
        self._apply_layout()
```

- [ ] **Step 2: Add `_apply_layout()` to the top of `refresh()`**

At the very start of `DashboardTab.refresh` (`budget_app.py:906`, right
after the `def refresh(self):` line), add one line:

```python
    def refresh(self):
        self._apply_layout()
        db = self.app.db
        c = self.app.c
        y, m = self.app.view_year, self.app.view_month
        cur = self.app.reporting_currency()
```

(everything after `cur = ...` is unchanged from the existing method body)

- [ ] **Step 3: Verify with a headless smoke script**

Write, run, and then delete a throwaway smoke script (project convention —
see Task 4 Step 5 for the exact scaffold: sandboxed `profiles.APP_DIR`,
build `App`, drive it in code):

```python
import sys, tempfile
sys.path.insert(0, r"ledger")
sys.path.insert(0, r"ledger/src")
import profiles
profiles.APP_DIR = tempfile.mkdtemp()
import budget_app

app = budget_app.App(profiles.create_profile("smoketest"))
dash = app.pages["dashboard"]

# every declared section has a real frame
assert set(dash.section_frames.keys()) == set(budget_app.DASHBOARD_SECTION_KEYS)

# default layout: everything visible, in declared order
layout = budget_app.resolve_dashboard_layout(app.db)
assert [e["key"] for e in layout] == budget_app.DASHBOARD_SECTION_KEYS
assert all(e["visible"] for e in layout)

# hide "flags" via the same path Settings will use (Task 8), confirm it
# actually unpacks
app.db.set_dashboard_layout(
    [{"key": k, "visible": (k != "flags")} for k in budget_app.DASHBOARD_SECTION_KEYS])
dash.refresh()
assert not dash.section_frames["flags"].winfo_ismapped()
assert dash.section_frames["hero"].winfo_ismapped()

# reordering: move "flags" (still hidden) aside, "hero" to the front of the
# remaining visible set via _on_reorder directly
visible_keys_before = [k for k in budget_app.DASHBOARD_SECTION_KEYS if k != "flags"]
dash._on_reorder(list(reversed(visible_keys_before)))
new_layout = budget_app.resolve_dashboard_layout(app.db)
visible_ordered = [e["key"] for e in new_layout if e["visible"]]
assert visible_ordered == list(reversed(visible_keys_before))
assert any(e["key"] == "flags" and not e["visible"] for e in new_layout), \
    "hidden section must survive a reorder of the visible ones"

print("SMOKE TEST PASSED")
app.destroy()
```

Run it with the project's venv Python, confirm `SMOKE TEST PASSED`, delete
the script.

- [ ] **Step 4: Run the full suite**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (this task adds no new pytest cases — pure Tkinter
wiring, per Global Constraints)

- [ ] **Step 5: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: rebuild Dashboard around reorderable, hideable sections"
```

---

## Task 6: Quick Actions content — Add Transaction popup + Transfer reuse

**Files:**
- Modify: `ledger/budget_app.py` (`DashboardTab`, inside `_build()`'s
  Quick Actions block from Task 5, plus two new `DashboardTab` methods)

**Interfaces:**
- Consumes: `submit_new_transaction` (Task 4), `make_scrollable_toplevel`
  (`budget_app.py:271`), `AccountsTab.open_transfer_dialog`
  (`budget_app.py:2738`, unchanged, called via `self.app.pages["accounts"]`).
- Produces: `DashboardTab.open_add_transaction_dialog()`.

- [ ] **Step 1: Pack the two buttons into `self.quick_actions_row`**

In `DashboardTab._build()`, right after the Quick Actions block built in
Task 5 (`self.quick_actions_row = ttk.Frame(qa_card, ...); self.quick_actions_row.pack(fill="x")`),
add:

```python
        ttk.Button(self.quick_actions_row, text="+ Add Transaction", style="Good.TButton",
                   command=self.open_add_transaction_dialog).pack(side="left")
        ttk.Button(self.quick_actions_row, text="Transfer Between Accounts…", style="Accent.TButton",
                   command=lambda: self.app.pages["accounts"].open_transfer_dialog()).pack(
            side="left", padx=(8, 0))
```

- [ ] **Step 2: Add `open_add_transaction_dialog()`**

Add as a new `DashboardTab` method (anywhere after `_build`/`_apply_layout`/
`_on_reorder`, e.g. right after `_on_reorder`):

```python
    def open_add_transaction_dialog(self):
        win, content = make_scrollable_toplevel(self, "Add Transaction", "420x460")
        cats = [c["name"] for c in self.app.db.list_categories()]
        accounts = [a["name"] for a in self.app.db.list_accounts()]

        ttk.Label(content, text="Date (YYYY-MM-DD)", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        date_var = tk.StringVar(value=self.app.today.isoformat())
        ttk.Entry(content, textvariable=date_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Payee", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        payee_var = tk.StringVar()
        ttk.Entry(content, textvariable=payee_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Category", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        category_var = tk.StringVar()
        ttk.Combobox(content, textvariable=category_var, values=cats, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="Amount (negative for expenses)", style="TLabel").pack(
            anchor="w", padx=14, pady=(10, 2))
        amount_var = tk.StringVar()
        ttk.Entry(content, textvariable=amount_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Currency", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        currency_var = tk.StringVar(value=self.app.reporting_currency())
        ttk.Entry(content, textvariable=currency_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Account", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        account_var = tk.StringVar()
        ttk.Combobox(content, textvariable=account_var, values=accounts, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="Note", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        note_var = tk.StringVar()
        ttk.Entry(content, textvariable=note_var).pack(fill="x", padx=14)

        def submit():
            ok, error = submit_new_transaction(
                self.app, date_var.get(), payee_var.get(), category_var.get(),
                amount_var.get(), currency_var.get(), note_var.get(), account_var.get())
            if not ok:
                if error:
                    messagebox.showerror("Invalid entry", error)
                return
            self.app.refresh_all()
            win.destroy()

        ttk.Button(content, text="Add Transaction", style="Accent.TButton", command=submit).pack(
            anchor="w", padx=14, pady=14)
```

- [ ] **Step 3: Verify with a headless smoke script**

```python
import sys, tempfile, datetime
sys.path.insert(0, r"ledger")
sys.path.insert(0, r"ledger/src")
import profiles
profiles.APP_DIR = tempfile.mkdtemp()
import budget_app

app = budget_app.App(profiles.create_profile("smoketest"))
db = app.db
db.add_account("Checking", kind="asset", subtype="checking", currency="GBP", balance=100)
db.add_account("Savings", kind="asset", subtype="savings", currency="GBP", balance=50)
db.add_category("GroceriesXYZ", kind="need")
app.refresh_all()

dash = app.pages["dashboard"]
dash.open_add_transaction_dialog()
# find the just-opened Toplevel and drive it directly via its child StringVars
# is awkward without a handle, so instead call submit_new_transaction the
# same way the dialog's submit() closure does, confirming the wiring:
ok, error = budget_app.submit_new_transaction(
    app, datetime.date.today().isoformat(), "Tesco", "GroceriesXYZ", "-9.99", "GBP", "", "Checking")
assert ok, error
assert len(db.list_transactions()) == 1

# Transfer reuse: confirm the Accounts tab's real dialog opens without error
# when invoked the same way the Dashboard button's command calls it
app.pages["accounts"].open_transfer_dialog()

print("SMOKE TEST PASSED")
app.destroy()
```

Run it, confirm `SMOKE TEST PASSED`, delete the script.

- [ ] **Step 4: Run the full suite**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: add Dashboard Quick Actions (Add Transaction, Transfer)"
```

---

## Task 7: Needs Attention content — bills, reimbursements, subscriptions

**Files:**
- Modify: `ledger/budget_app.py` (`DashboardTab`, the `needs_attention`
  block from Task 5, plus `refresh()`)

**Interfaces:**
- Consumes: `upcoming_bills` (already imported at module level,
  `budget_app.py:53`), `db.list_outstanding_reimbursements`,
  `db.settle_reimbursement`, `detect_recurring_candidates` (already
  imported, `budget_app.py:58`), `db.add_ignored_subscription`,
  `db.post_recurring_item` (Task 1), `App.show_page`,
  `RecurringTab._prefill_from_candidate` (`budget_app.py:2256`, unchanged).
- Produces: `DashboardTab._refresh_needs_attention()`, called from
  `refresh()`.

- [ ] **Step 1: Add the render method and wire it into `refresh()`**

Add a new `DashboardTab` method (after `open_add_transaction_dialog`):

```python
    def _refresh_needs_attention(self):
        for w in self.needs_attention_rows_frame.winfo_children():
            w.destroy()
        db = self.app.db
        cur = self.app.reporting_currency()

        bills = upcoming_bills(db, within_days=14, today=self.app.today)[:4]
        reimbursements = db.list_outstanding_reimbursements()[:4]
        candidates = detect_recurring_candidates(db)[:4]

        if not bills and not reimbursements and not candidates:
            ttk.Label(self.needs_attention_rows_frame, text="You're all caught up.",
                      style="CardDim.TLabel").pack(anchor="w")
            return

        if bills:
            ttk.Label(self.needs_attention_rows_frame, text="Bills due soon",
                      style="CardDim.TLabel").pack(anchor="w", pady=(0, 2))
            for b in bills:
                row = ttk.Frame(self.needs_attention_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=f"📅 {b['name']} ({fmt_money(b['amount'], cur)}) — "
                                     f"{b['next_date']}", style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Post Now",
                           command=lambda rid=b["id"]: self._post_bill_now(rid)).pack(side="right")

        if reimbursements:
            ttk.Label(self.needs_attention_rows_frame, text="Outstanding reimbursements",
                      style="CardDim.TLabel").pack(anchor="w", pady=(8, 2))
            for r in reimbursements:
                row = ttk.Frame(self.needs_attention_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=f"{r['owed_by']} owes {fmt_money(r['amount'], cur)} — "
                                     f"{r['payee'] or '(no payee)'}",
                          style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Mark Settled",
                           command=lambda rid=r["id"]: self._settle_reimbursement_now(rid)).pack(
                    side="right")

        if candidates:
            ttk.Label(self.needs_attention_rows_frame, text="Detected subscriptions",
                      style="CardDim.TLabel").pack(anchor="w", pady=(8, 2))
            for cand in candidates:
                row = ttk.Frame(self.needs_attention_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=f"{cand['payee']} — "
                                     f"{fmt_money(cand['last_amount'], cand['last_currency'])} "
                                     f"every ~{cand['avg_interval_days']:.0f} days",
                          style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Ignore",
                           command=lambda c=cand: self._ignore_candidate_now(c)).pack(
                    side="right", padx=(6, 0))
                ttk.Button(row, text="Add to Recurring",
                           command=lambda c=cand: self._add_candidate_to_recurring(c)).pack(
                    side="right")

    def _post_bill_now(self, recurring_id):
        self.app.db.post_recurring_item(recurring_id)
        self.app.refresh_all()

    def _settle_reimbursement_now(self, reimbursement_id):
        self.app.db.settle_reimbursement(reimbursement_id)
        self.app.refresh_all()

    def _ignore_candidate_now(self, candidate):
        self.app.db.add_ignored_subscription(candidate["payee"])
        self.app.refresh_all()

    def _add_candidate_to_recurring(self, candidate):
        self.app.show_page("recurring")
        self.app.pages["recurring"]._prefill_from_candidate(candidate)
```

Then add one call at the end of `DashboardTab.refresh()` (after the
existing Flags & Nudges block finishes inserting `lines` into
`self.flags_text` — the very end of the method):

```python
        self._refresh_needs_attention()
```

- [ ] **Step 2: Verify with a headless smoke script**

```python
import sys, tempfile, datetime
sys.path.insert(0, r"ledger")
sys.path.insert(0, r"ledger/src")
import profiles
profiles.APP_DIR = tempfile.mkdtemp()
import budget_app

app = budget_app.App(profiles.create_profile("smoketest"))
db = app.db
db.add_account("Checking", kind="asset", subtype="checking", currency="GBP", balance=500)
today = datetime.date.today()
db.add_recurring("Netflix", "Netflix", None, -15.0, "GBP", "monthly",
                  (today + datetime.timedelta(days=3)).isoformat(), account_id=1)
app.refresh_all()

dash = app.pages["dashboard"]
children_before = len(dash.needs_attention_rows_frame.winfo_children())
assert children_before > 0, "Needs Attention must render the upcoming bill"

recurring_id = db.list_recurring()[0]["id"]
dash._post_bill_now(recurring_id)
tx_count = len(db.list_transactions())
assert tx_count == 1, "Post Now must actually post a transaction"

print("SMOKE TEST PASSED")
app.destroy()
```

Run it, confirm `SMOKE TEST PASSED`, delete the script.

- [ ] **Step 3: Run the full suite**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: add Dashboard Needs Attention card"
```

---

## Task 8: "Customize Dashboard" visibility card in Settings

**Files:**
- Modify: `ledger/budget_app.py` (`SettingsTab._build`, right after the
  existing "Customize Navigation" card, `budget_app.py:3941-3956`; and
  `SettingsTab.refresh`, `budget_app.py:4108-4120`)

**Interfaces:**
- Consumes: `DASHBOARD_SECTIONS`, `resolve_dashboard_layout` (Task 3),
  `db.set_dashboard_layout` (Task 2).
- Produces: `SettingsTab.dashboard_visibility_vars`,
  `SettingsTab.save_dashboard_visibility()`.

- [ ] **Step 1: Add the card in `_build()`**

Right after the existing "Customize Navigation" card block
(`budget_app.py:3941-3956`, ending at
`ttk.Button(nav_card, text="Save Navigation", ...).pack(...)`), add:

```python
        dashboard_card = Card(self.advanced_container, title="Customize Dashboard")
        dashboard_card.pack(fill="x", pady=(0, 10))
        ttk.Label(dashboard_card, text="Show/hide Dashboard sections — drag their grip "
                                        "handle (⠿) on the Dashboard itself to reorder them.",
                  style="CardDim.TLabel").pack(anchor="w")
        dashboard_checks_frame = ttk.Frame(dashboard_card, style="Card.TFrame")
        dashboard_checks_frame.pack(fill="x", pady=(6, 0))
        self.dashboard_visibility_vars = {}
        for i, (key, label) in enumerate(DASHBOARD_SECTIONS):
            var = tk.BooleanVar(value=True)
            self.dashboard_visibility_vars[key] = var
            ttk.Checkbutton(dashboard_checks_frame, text=label, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)
        ttk.Button(dashboard_card, text="Save Dashboard Layout", style="Accent.TButton",
                   command=self.save_dashboard_visibility).pack(anchor="w", pady=(8, 0))
```

- [ ] **Step 2: Add `save_dashboard_visibility()`**

Right after `save_nav_visibility` (`budget_app.py:4087-4090`):

```python
    def save_dashboard_visibility(self):
        db = self.app.db
        layout = resolve_dashboard_layout(db)
        visibility = {key: var.get() for key, var in self.dashboard_visibility_vars.items()}
        new_layout = [{"key": e["key"], "visible": visibility[e["key"]]} for e in layout]
        db.set_dashboard_layout(new_layout)
        self.app.refresh_all()
```

- [ ] **Step 3: Sync the checkboxes in `refresh()`**

Right after the existing nav-visibility sync block
(`budget_app.py:4117-4119`):

```python
        hidden_now = get_hidden_nav_tabs(db)
        for key, var in self.nav_visibility_vars.items():
            var.set(key not in hidden_now)

        dashboard_layout_now = resolve_dashboard_layout(db)
        for entry in dashboard_layout_now:
            if entry["key"] in self.dashboard_visibility_vars:
                self.dashboard_visibility_vars[entry["key"]].set(entry["visible"])
```

- [ ] **Step 4: Verify with a headless smoke script**

```python
import sys, tempfile
sys.path.insert(0, r"ledger")
sys.path.insert(0, r"ledger/src")
import profiles
profiles.APP_DIR = tempfile.mkdtemp()
import budget_app

app = budget_app.App(profiles.create_profile("smoketest"))
settings = app.pages["settings"]
dash = app.pages["dashboard"]

assert set(settings.dashboard_visibility_vars.keys()) == set(budget_app.DASHBOARD_SECTION_KEYS)

settings.dashboard_visibility_vars["flags"].set(False)
settings.save_dashboard_visibility()

layout = budget_app.resolve_dashboard_layout(app.db)
assert any(e["key"] == "flags" and not e["visible"] for e in layout)
assert not dash.section_frames["flags"].winfo_ismapped(), \
    "save_dashboard_visibility must call refresh_all(), which must hide the section live"

print("SMOKE TEST PASSED")
app.destroy()
```

Run it, confirm `SMOKE TEST PASSED`, delete the script.

- [ ] **Step 5: Run the full suite**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add ledger/budget_app.py
git commit -m "feat: add Customize Dashboard visibility card to Settings"
```

---

## Task 9: Documentation and final verification

**Files:**
- Modify: `CLAUDE.md` (repo root)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — documentation only.

- [ ] **Step 1: Add a CLAUDE.md section**

Add a new bullet-grouped subsection to CLAUDE.md's "Feature rounds" area
(alongside "Default colors & Dashboard colorization"), covering: the
`post_recurring_item`/`_post_recurring_once_nocommit` split and why it
exists; the Needs Attention card and what it reuses vs. what's genuinely
new; the Quick Actions row and the `submit_new_transaction` extraction;
and the `dashboard_layout` setting / `resolve_dashboard_layout` /
`enable_drag_reorder` reuse for the customizable section layout — mirroring
the level of detail the existing "Drag-and-drop reordering" and "Default
colors & Dashboard colorization" sections use.

- [ ] **Step 2: Run the full test suite one more time**

Run: `cd ledger && .venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass

- [ ] **Step 3: One end-to-end headless smoke test covering the whole feature**

```python
import sys, tempfile, datetime
sys.path.insert(0, r"ledger")
sys.path.insert(0, r"ledger/src")
import profiles
profiles.APP_DIR = tempfile.mkdtemp()
import budget_app

app = budget_app.App(profiles.create_profile("smoketest"))
db = app.db
db.add_account("Checking", kind="asset", subtype="checking", currency="GBP", balance=500)
db.add_category("GroceriesXYZ", kind="need")
today = datetime.date.today()
db.add_recurring("Netflix", "Netflix", None, -15.0, "GBP", "monthly",
                  (today + datetime.timedelta(days=3)).isoformat(), account_id=1)
app.refresh_all()

dash = app.pages["dashboard"]
assert set(dash.section_frames.keys()) == set(budget_app.DASHBOARD_SECTION_KEYS)
assert len(dash.needs_attention_rows_frame.winfo_children()) > 0

ok, error = budget_app.submit_new_transaction(
    app, today.isoformat(), "Tesco", "GroceriesXYZ", "-9.99", "GBP", "", "Checking")
assert ok, error

recurring_id = db.list_recurring()[0]["id"]
dash._post_bill_now(recurring_id)

app.pages["settings"].dashboard_visibility_vars["charts"].set(False)
app.pages["settings"].save_dashboard_visibility()
assert not dash.section_frames["charts"].winfo_ismapped()

assert len(db.list_transactions()) == 2
print("SMOKE TEST PASSED")
app.destroy()
```

Run it, confirm `SMOKE TEST PASSED`, delete the script.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the ultimate Dashboard feature round"
```
