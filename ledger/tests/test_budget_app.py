from finance_core import Database
from budget_app import (
    get_hidden_nav_tabs, set_hidden_nav_tabs, visible_nav_groups, NAV_GROUPS, PROTECTED_NAV_KEYS,
    DASHBOARD_SECTION_KEYS, resolve_dashboard_layout, submit_new_transaction,
)


def _db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_get_hidden_nav_tabs_is_empty_by_default(tmp_path):
    db = _db(tmp_path)

    assert get_hidden_nav_tabs(db) == set()

    db.close()


def test_set_and_get_hidden_nav_tabs_round_trips(tmp_path):
    db = _db(tmp_path)

    set_hidden_nav_tabs(db, {"tax", "investments"})

    assert get_hidden_nav_tabs(db) == {"tax", "investments"}

    db.close()


def test_set_hidden_nav_tabs_never_hides_protected_keys(tmp_path):
    db = _db(tmp_path)

    set_hidden_nav_tabs(db, {"dashboard", "settings", "tax"})

    assert get_hidden_nav_tabs(db) == {"tax"}
    assert PROTECTED_NAV_KEYS.isdisjoint(get_hidden_nav_tabs(db))

    db.close()


def test_get_hidden_nav_tabs_defensively_strips_protected_keys_from_stale_settings(tmp_path):
    # simulates a settings row saved before PROTECTED_NAV_KEYS existed, or edited by hand
    db = _db(tmp_path)
    db.set_setting("hidden_nav_tabs", "dashboard,tax,settings")

    assert get_hidden_nav_tabs(db) == {"tax"}

    db.close()


def test_visible_nav_groups_filters_hidden_items_out_of_each_group():
    result = visible_nav_groups(NAV_GROUPS, {"tax", "investments"})

    planning = dict(result)["Planning"]
    keys = [key for key, _, _ in planning]
    assert "tax" not in keys
    assert "investments" not in keys
    assert "recurring" in keys  # untouched items stay


def test_visible_nav_groups_drops_a_group_that_becomes_fully_hidden():
    all_planning_keys = {key for key, _, _ in dict(NAV_GROUPS)["Planning"]}

    result = visible_nav_groups(NAV_GROUPS, all_planning_keys)

    assert "Planning" not in dict(result)
    assert "Daily" in dict(result)  # untouched group survives


def test_visible_nav_groups_with_no_hidden_keys_returns_everything():
    result = visible_nav_groups(NAV_GROUPS, set())

    assert result == NAV_GROUPS


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


class _FakeApp:
    """Minimal stand-in for App -- submit_new_transaction only touches
    .db and .reporting_currency(), never any Tkinter widget."""
    def __init__(self, db):
        self.db = db

    def reporting_currency(self):
        return "GBP"


def test_submit_new_transaction_writes_a_valid_transaction(tmp_path):
    db = _db(tmp_path)
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


def test_submit_new_transaction_accepts_date_with_whitespace(tmp_path):
    db = _db(tmp_path)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(app, "  2026-09-01  ", "Tesco", "", "-10", "GBP", "", "")

    assert ok is True
    assert error is None
    tx = db.list_transactions()[0]
    assert tx["date"] == "2026-09-01"
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
    tags = db.get_transaction_tags(tx["id"])
    assert set(tags) == {"food", "weekly"}
    db.close()


def test_submit_new_transaction_asks_before_exceeding_budget_and_respects_decline(tmp_path):
    db = _db(tmp_path)
    cats = {c["name"]: c["id"] for c in db.list_categories()}
    cat_id = cats["Dining Out"]
    db.set_category_budget(cat_id, 20.0)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Restaurant", "Dining Out", "-50", "GBP", "", "",
        confirm_over_budget=lambda *a: False)

    assert ok is False
    assert db.list_transactions() == []
    db.close()


def test_submit_new_transaction_proceeds_when_over_budget_confirmed(tmp_path):
    db = _db(tmp_path)
    cats = {c["name"]: c["id"] for c in db.list_categories()}
    cat_id = cats["Dining Out"]
    db.set_category_budget(cat_id, 20.0)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Restaurant", "Dining Out", "-50", "GBP", "", "",
        confirm_over_budget=lambda *a: True)

    assert ok is True
    assert len(db.list_transactions()) == 1
    db.close()


def test_submit_new_transaction_rejects_a_negative_amount_in_an_income_category(tmp_path):
    db = _db(tmp_path)
    db.add_category("Salary", "income")
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Employer", "Salary", "-100", "GBP", "", "")

    assert ok is False
    assert error is not None
    assert db.list_transactions() == []
    db.close()


def test_submit_new_transaction_rejects_a_positive_amount_in_a_spending_category(tmp_path):
    db = _db(tmp_path)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Tesco", "Groceries", "100", "GBP", "", "")

    assert ok is False
    assert error is not None
    assert db.list_transactions() == []
    db.close()


def test_submit_new_transaction_accepts_uncategorized_regardless_of_amount_sign(tmp_path):
    db = _db(tmp_path)
    app = _FakeApp(db)

    ok, error = submit_new_transaction(
        app, "2026-09-01", "Mystery", "", "100", "GBP", "", "")

    assert ok is True
    assert error is None
    assert len(db.list_transactions()) == 1
    db.close()
