from finance_core import Database
from budget_app import (
    get_hidden_nav_tabs, set_hidden_nav_tabs, visible_nav_groups, NAV_GROUPS, PROTECTED_NAV_KEYS,
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
