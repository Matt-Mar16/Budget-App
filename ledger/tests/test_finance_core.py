import datetime
import os

import pytest

import csv as csv_mod

from finance_core import (
    Database, budget_run_rate, categories_over_threshold, monthly_history, top_payees,
    daily_spend_totals, detect_recurring_candidates, csv_import_preview, csv_import_commit,
    export_account_statement_csv, category_budget_status, spend_by_kind, income_by_category,
    export_transactions_editable_csv, export_accounts_editable_csv,
    export_categories_editable_csv, export_investments_editable_csv,
    apply_transactions_csv, apply_accounts_csv, apply_categories_csv, apply_investments_csv,
    refresh_profile_csvs, apply_profile_csvs,
)

TX_CSV_FIELDS = ["id", "date", "payee", "category", "amount", "currency", "note", "account",
                  "tags", "status"]


def _read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv_mod.DictReader(f))


def _write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_add_balance_adjustment_raises_an_asset_account_to_match_a_statement(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 100.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]

    tx_id = db.add_balance_adjustment(acc_id, 150.0)

    assert tx_id is not None
    tx = db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    assert tx["amount"] == pytest.approx(50.0)
    assert tx["payee"] == "Balance Adjustment"
    assert db.get_account(acc_id)["balance"] == pytest.approx(150.0)
    db.close()


def test_add_balance_adjustment_lowers_an_asset_account_to_match_a_statement(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 100.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]

    tx_id = db.add_balance_adjustment(acc_id, 60.0)

    tx = db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    assert tx["amount"] == pytest.approx(-40.0)
    assert db.get_account(acc_id)["balance"] == pytest.approx(60.0)
    db.close()


def test_add_balance_adjustment_handles_liability_accounts_correctly(tmp_path):
    db = _db(tmp_path)
    db.add_account("Credit Card", "liability", -200.0, currency="GBP", subtype="credit_card")
    acc_id = db.list_accounts()[0]["id"]

    # Correcting to a real statement balance of -250.0 (owe more than tracked)
    db.add_balance_adjustment(acc_id, -250.0)

    assert db.get_account(acc_id)["balance"] == pytest.approx(-250.0)
    db.close()


def test_add_balance_adjustment_does_nothing_when_balance_already_matches(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 100.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]

    tx_id = db.add_balance_adjustment(acc_id, 100.0)

    assert tx_id is None
    assert len(db.list_transactions()) == 0
    db.close()


def test_add_balance_adjustment_does_not_trigger_cashback_or_roundup(tmp_path):
    db = _db(tmp_path)
    db.set_setting("roundup_enabled", "1")
    db.add_account("Credit Card", "liability", -100.0, currency="GBP", subtype="credit_card",
                    cashback_rate=5.0)
    acc_id = db.list_accounts()[0]["id"]

    # Correcting from -100 owed to -50 owed (paying down debt) yields a
    # liability-inverted delta of -50: a NEGATIVE amount, which is exactly
    # the condition add_transaction's cashback/roundup gates key off of —
    # this is the case that actually proves the apply_cashback_roundup=False
    # guard is doing something (a -150 target instead would yield +50,
    # never reaching those gates regardless of the guard).
    tx_id = db.add_balance_adjustment(acc_id, -50.0)

    tx = db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    assert tx["amount"] == pytest.approx(-50.0)
    assert tx["cashback"] == 0.0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM roundups WHERE transaction_id=?", (tx_id,)
    ).fetchone()[0] == 0
    db.close()


def test_add_balance_adjustment_is_excluded_from_monthly_income_expense_totals(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 100.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]

    db.add_balance_adjustment(acc_id, 175.0, date="2026-08-15")

    # A reconciliation correction isn't a real cash-flow event -- it must be
    # excluded from monthly aggregates the same way internal transfers are,
    # or it would distort savings-rate/income-vs-expense reporting for
    # whatever month it happens to land in.
    assert db.transactions_in_month(2026, 8) == []
    # ...but it must still be visible in the account's own ledger/statement.
    assert len(db.account_ledger(acc_id)) == 1
    db.close()


def test_add_balance_adjustment_raises_a_clear_error_for_an_unknown_account(tmp_path):
    db = _db(tmp_path)

    with pytest.raises(ValueError, match="[Aa]ccount"):
        db.add_balance_adjustment(999, 100.0)
    db.close()


def test_transfer_between_accounts_uses_explicit_to_amount_when_given(tmp_path):
    db = _db(tmp_path)
    db.add_account("UK Bank", "asset", 1200.0, currency="GBP")
    db.add_account("CAD Chequing", "asset", 0.0, currency="CAD")
    accounts = {a["name"]: a["id"] for a in db.list_accounts()}
    db.set_fx_rate("CAD", 0.5)  # a stale/wrong rate the real exchange should NOT be forced through

    db.transfer_between_accounts(
        accounts["UK Bank"], accounts["CAD Chequing"], 500.0, to_amount=860.0, date="2026-09-05"
    )

    cad_balance = db.get_account(accounts["CAD Chequing"])["balance"]
    assert cad_balance == pytest.approx(860.0)

    db.close()


def test_transfer_between_accounts_computes_historical_rate_from_to_amount(tmp_path):
    db = _db(tmp_path)
    db.add_account("UK Bank", "asset", 1200.0, currency="GBP")
    db.add_account("CAD Chequing", "asset", 0.0, currency="CAD")
    accounts = {a["name"]: a["id"] for a in db.list_accounts()}

    group_id = db.transfer_between_accounts(
        accounts["UK Bank"], accounts["CAD Chequing"], 500.0, to_amount=860.0, date="2026-09-05"
    )

    row = db.conn.execute(
        "SELECT historical_rate FROM transactions WHERE transfer_group_id=? AND account_id=?",
        (group_id, accounts["CAD Chequing"]),
    ).fetchone()
    assert row["historical_rate"] == pytest.approx(860.0 / 500.0)

    db.close()


def test_transfer_between_accounts_still_converts_via_fx_rates_when_to_amount_omitted(tmp_path):
    db = _db(tmp_path)
    db.add_account("UK Bank", "asset", 1200.0, currency="GBP")
    db.add_account("CAD Chequing", "asset", 0.0, currency="CAD")
    accounts = {a["name"]: a["id"] for a in db.list_accounts()}
    db.set_fx_rate("CAD", 0.5)  # 1 GBP (rate 1.0) -> 2 CAD

    db.transfer_between_accounts(accounts["UK Bank"], accounts["CAD Chequing"], 500.0, date="2026-09-05")

    cad_balance = db.get_account(accounts["CAD Chequing"])["balance"]
    assert cad_balance == pytest.approx(1000.0)

    db.close()


def test_add_transaction_auto_invests_cashback_when_card_has_an_auto_invest_target(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    index_fund_id = db.list_accounts()[0]["id"]
    db.add_account("Rewards Card", "liability", 0.0, currency="GBP", subtype="credit_card",
                    cashback_rate=1.5)
    card_id = next(a["id"] for a in db.list_accounts() if a["name"] == "Rewards Card")
    db.update_account_details(card_id, cashback_auto_invest_account_id=index_fund_id)

    tx_id = db.add_transaction(
        date="2026-09-03", payee="Tesco", category_id=None, amount=-100.0, currency="GBP",
        account_id=card_id,
    )

    fund = db.get_account(index_fund_id)
    assert fund["balance"] == pytest.approx(1.5)
    assert fund["contributions"] == pytest.approx(1.5)

    contributions = db.get_investment_contributions(index_fund_id)
    assert len(contributions) == 1
    assert contributions[0]["amount"] == pytest.approx(1.5)

    tx = db.conn.execute("SELECT cashback_redeemed FROM transactions WHERE id=?", (tx_id,)).fetchone()
    assert tx["cashback_redeemed"] == 1

    db.close()


def test_update_account_details_clears_cashback_auto_invest_target_when_passed_zero(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    index_fund_id = db.list_accounts()[0]["id"]
    db.add_account("Rewards Card", "liability", 0.0, currency="GBP", subtype="credit_card",
                    cashback_rate=1.5)
    card_id = next(a["id"] for a in db.list_accounts() if a["name"] == "Rewards Card")
    db.update_account_details(card_id, cashback_auto_invest_account_id=index_fund_id)

    db.update_account_details(card_id, cashback_auto_invest_account_id=0)

    assert db.get_account(card_id)["cashback_auto_invest_account_id"] is None

    db.close()


def test_add_transaction_leaves_cashback_unredeemed_without_an_auto_invest_target(tmp_path):
    db = _db(tmp_path)
    db.add_account("Rewards Card", "liability", 0.0, currency="GBP", subtype="credit_card",
                    cashback_rate=1.5)
    card_id = db.list_accounts()[0]["id"]

    db.add_transaction(
        date="2026-09-03", payee="Tesco", category_id=None, amount=-100.0, currency="GBP",
        account_id=card_id,
    )

    assert db.get_unredeemed_cashback() == pytest.approx(1.5)

    db.close()


def test_add_security_transaction_computes_realized_gain_using_section_104_pooling(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    account_id = db.list_accounts()[0]["id"]

    db.add_security_transaction(account_id, "VWRL", "2026-01-01", "buy", 100, 10.0)
    db.add_security_transaction(account_id, "VWRL", "2026-02-01", "buy", 100, 12.0)
    sell_id = db.add_security_transaction(account_id, "VWRL", "2026-03-01", "sell", 50, 15.0, fees=5.0)

    row = db.conn.execute("SELECT realized_gain FROM security_lots WHERE id=?", (sell_id,)).fetchone()
    # pool after both buys: 200 units, cost 2200 -> avg cost 11/unit
    # proceeds = 50*15 - 5 = 745; cost of units sold = 50*11 = 550; gain = 195
    assert row["realized_gain"] == pytest.approx(195.0)

    db.close()


def test_add_security_transaction_retroactively_recomputes_gains_for_a_backdated_buy(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    account_id = db.list_accounts()[0]["id"]

    db.add_security_transaction(account_id, "VWRL", "2026-01-01", "buy", 100, 10.0)
    sell_id = db.add_security_transaction(account_id, "VWRL", "2026-02-01", "sell", 50, 15.0)
    before = db.conn.execute("SELECT realized_gain FROM security_lots WHERE id=?", (sell_id,)).fetchone()
    assert before["realized_gain"] == pytest.approx(250.0)  # avg cost 10, gain = 50*15 - 50*10

    # a backdated buy inserted between the existing buy and sell changes the
    # pool's average cost at the time of the sell, so the sell's stored
    # realized_gain must update too, not just future transactions.
    db.add_security_transaction(account_id, "VWRL", "2026-01-15", "buy", 100, 12.0)

    after = db.conn.execute("SELECT realized_gain FROM security_lots WHERE id=?", (sell_id,)).fetchone()
    # pool at time of sell: 200 units, cost 2200 -> avg 11; gain = 50*15 - 50*11 = 200
    assert after["realized_gain"] == pytest.approx(200.0)

    db.close()


def test_security_pool_state_returns_current_holdings_and_average_cost(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    account_id = db.list_accounts()[0]["id"]

    db.add_security_transaction(account_id, "VWRL", "2026-01-01", "buy", 100, 10.0)
    db.add_security_transaction(account_id, "VWRL", "2026-02-01", "buy", 100, 12.0)
    db.add_security_transaction(account_id, "VWRL", "2026-03-01", "sell", 50, 15.0)

    quantity, cost, avg_cost = db.security_pool_state(account_id, "VWRL")

    assert quantity == pytest.approx(150.0)
    assert avg_cost == pytest.approx(11.0)
    assert cost == pytest.approx(1650.0)

    db.close()


def test_realized_gains_for_uk_tax_year_sums_sells_within_6_apr_to_5_apr(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    account_id = db.list_accounts()[0]["id"]

    db.add_security_transaction(account_id, "VWRL", "2026-01-01", "buy", 300, 10.0)
    # inside tax year 2025/26 (2025-04-06 to 2026-04-05)
    db.add_security_transaction(account_id, "VWRL", "2026-03-01", "sell", 50, 15.0)
    # inside tax year 2026/27 (2026-04-06 to 2027-04-05)
    db.add_security_transaction(account_id, "VWRL", "2026-05-01", "sell", 50, 20.0)

    result = db.realized_gains_for_uk_tax_year(2025)

    assert result["total_gain"] == pytest.approx(250.0)  # 50 * (15 - 10)
    assert len(result["sells"]) == 1

    db.close()


def test_budget_run_rate_projects_month_end_spend_from_pace_so_far(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Run Rate", "need", 300.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Run Rate")
    db.add_transaction(date="2026-09-01", payee="Tesco", category_id=cat_id, amount=-100.0, currency="GBP")

    # 2026-09 has 30 days; spending stops after day 10 -> 100/10*30 = 300 projected
    result = budget_run_rate(db, 2026, 9, today=datetime.date(2026, 9, 10))

    row = next(r for r in result if r["category"]["name"] == "Groceries Run Rate")
    assert row["projected"] == pytest.approx(300.0)
    assert row["projected_over"] is False  # exactly at budget, not over

    db.close()


def test_budget_run_rate_flags_projected_overspend(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Run Rate", "need", 300.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Run Rate")
    db.add_transaction(date="2026-09-01", payee="Tesco", category_id=cat_id, amount=-150.0, currency="GBP")

    result = budget_run_rate(db, 2026, 9, today=datetime.date(2026, 9, 10))

    row = next(r for r in result if r["category"]["name"] == "Groceries Run Rate")
    assert row["projected"] == pytest.approx(450.0)  # 150/10*30
    assert row["projected_over"] is True

    db.close()


def test_categories_over_threshold_flags_categories_past_the_threshold_pct(tmp_path):
    db = _db(tmp_path)
    db.add_category("Dining Threshold", "want", 100.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Dining Threshold")
    db.add_transaction(date="2026-09-05", payee="Nando's", category_id=cat_id, amount=-85.0, currency="GBP")

    result = categories_over_threshold(db, 2026, 9, threshold_pct=80)

    assert len(result) == 1
    assert result[0]["category"]["name"] == "Dining Threshold"
    assert result[0]["pct"] == pytest.approx(0.85)

    db.close()


def test_categories_over_threshold_excludes_categories_below_the_threshold(tmp_path):
    db = _db(tmp_path)
    db.add_category("Shopping Threshold", "want", 100.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Shopping Threshold")
    db.add_transaction(date="2026-09-05", payee="Amazon", category_id=cat_id, amount=-50.0, currency="GBP")

    result = categories_over_threshold(db, 2026, 9, threshold_pct=80)

    assert result == []

    db.close()


def test_monthly_history_disambiguates_month_labels_when_range_exceeds_a_year(tmp_path):
    db = _db(tmp_path)

    history = monthly_history(db, 2026, 6, n_months=14)

    labels = [label for label, _, _ in history]
    assert len(labels) == len(set(labels)), f"duplicate month labels in a >12-month range: {labels}"

    db.close()


def test_top_payees_ranks_by_total_spend_this_month(tmp_path):
    db = _db(tmp_path)
    db.add_transaction(date="2026-09-01", payee="Tesco", category_id=None, amount=-40.0, currency="GBP")
    db.add_transaction(date="2026-09-05", payee="Tesco", category_id=None, amount=-30.0, currency="GBP")
    db.add_transaction(date="2026-09-03", payee="Netflix", category_id=None, amount=-15.0, currency="GBP")
    db.add_transaction(date="2026-09-10", payee="Salary", category_id=None, amount=2000.0, currency="GBP")

    result = top_payees(db, 2026, 9, limit=10)

    assert result[0] == {"payee": "Tesco", "total": pytest.approx(70.0), "count": 2}
    assert result[1] == {"payee": "Netflix", "total": pytest.approx(15.0), "count": 1}
    assert len(result) == 2  # income (Salary) excluded, only expenses ranked

    db.close()


def test_top_payees_respects_limit(tmp_path):
    db = _db(tmp_path)
    for i, payee in enumerate(["A", "B", "C"]):
        db.add_transaction(date="2026-09-01", payee=payee, category_id=None,
                            amount=-(10.0 + i), currency="GBP")

    result = top_payees(db, 2026, 9, limit=2)

    assert len(result) == 2
    assert result[0]["payee"] == "C"  # highest spend first

    db.close()


def test_daily_spend_totals_sums_expenses_per_day_of_month(tmp_path):
    db = _db(tmp_path)
    db.add_transaction(date="2026-09-01", payee="A", category_id=None, amount=-20.0, currency="GBP")
    db.add_transaction(date="2026-09-01", payee="B", category_id=None, amount=-5.0, currency="GBP")
    db.add_transaction(date="2026-09-15", payee="C", category_id=None, amount=-30.0, currency="GBP")
    db.add_transaction(date="2026-09-15", payee="Salary", category_id=None, amount=1000.0, currency="GBP")

    result = daily_spend_totals(db, 2026, 9)

    assert result[1] == pytest.approx(25.0)
    assert result[15] == pytest.approx(30.0)  # income excluded from the day's total
    assert result[2] == 0.0
    assert len(result) == 30  # September has 30 days, every day present

    db.close()


def test_detect_recurring_candidates_flags_a_regularly_spaced_repeating_payee(tmp_path):
    db = _db(tmp_path)
    for d in ["2026-01-01", "2026-02-01", "2026-03-01"]:
        db.add_transaction(date=d, payee="Netflix", category_id=None, amount=-9.99, currency="GBP")

    candidates = detect_recurring_candidates(db)

    assert len(candidates) == 1
    assert candidates[0]["payee"] == "Netflix"
    assert candidates[0]["occurrences"] == 3
    assert candidates[0]["price_changed"] is False

    db.close()


def test_detect_recurring_candidates_flags_a_price_change_on_the_latest_occurrence(tmp_path):
    db = _db(tmp_path)
    db.add_transaction(date="2026-01-01", payee="Spotify", category_id=None, amount=-9.99, currency="GBP")
    db.add_transaction(date="2026-02-01", payee="Spotify", category_id=None, amount=-9.99, currency="GBP")
    db.add_transaction(date="2026-03-01", payee="Spotify", category_id=None, amount=-11.99, currency="GBP")

    candidates = detect_recurring_candidates(db)

    row = next(c for c in candidates if c["payee"] == "Spotify")
    assert row["price_changed"] is True
    assert row["previous_amount"] == pytest.approx(-9.99)
    assert row["last_amount"] == pytest.approx(-11.99)

    db.close()


def test_detect_recurring_candidates_skips_payees_already_tracked_in_recurring(tmp_path):
    db = _db(tmp_path)
    for d in ["2026-01-01", "2026-02-01", "2026-03-01"]:
        db.add_transaction(date=d, payee="Netflix", category_id=None, amount=-9.99, currency="GBP")
    db.add_recurring("Netflix subscription", "Netflix", None, -9.99, "GBP", "monthly", "2026-04-01")

    candidates = detect_recurring_candidates(db)

    assert not any(c["payee"] == "Netflix" for c in candidates)

    db.close()


def test_detect_recurring_candidates_skips_irregular_one_off_shopping(tmp_path):
    db = _db(tmp_path)
    db.add_transaction(date="2026-01-03", payee="Tesco", category_id=None, amount=-12.40, currency="GBP")
    db.add_transaction(date="2026-01-19", payee="Tesco", category_id=None, amount=-38.10, currency="GBP")
    db.add_transaction(date="2026-02-02", payee="Tesco", category_id=None, amount=-5.60, currency="GBP")
    db.add_transaction(date="2026-02-27", payee="Tesco", category_id=None, amount=-21.90, currency="GBP")

    candidates = detect_recurring_candidates(db)

    assert not any(c["payee"] == "Tesco" for c in candidates)

    db.close()


def test_csv_import_preview_flags_a_row_matching_an_existing_transaction_as_likely_duplicate(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    account_id = db.list_accounts()[0]["id"]
    db.add_transaction(date="2026-09-05", payee="Tesco", category_id=None, amount=-42.50,
                        currency="GBP", account_id=account_id)

    csv_path = tmp_path / "statement.csv"
    csv_path.write_text("Date,Payee,Amount\n2026-09-05,Tesco,-42.50\n", encoding="utf-8")

    batch_id, staged = csv_import_preview(db, str(csv_path), account_id=account_id)

    assert staged[0]["likely_duplicate"] is True

    db.close()


def test_csv_import_preview_does_not_flag_a_genuinely_new_row(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    account_id = db.list_accounts()[0]["id"]
    db.add_transaction(date="2026-09-05", payee="Tesco", category_id=None, amount=-42.50,
                        currency="GBP", account_id=account_id)

    csv_path = tmp_path / "statement.csv"
    csv_path.write_text("Date,Payee,Amount\n2026-09-06,Sainsbury's,-18.20\n", encoding="utf-8")

    batch_id, staged = csv_import_preview(db, str(csv_path), account_id=account_id)

    assert staged[0]["likely_duplicate"] is False

    db.close()


def test_csv_import_commit_does_not_silently_drop_a_flagged_duplicate_row(tmp_path):
    # Same "no automatic dedup" philosophy as sync_transactions.py: a flag
    # is a hint for the user to review, never a silent skip — two genuinely
    # identical same-day transactions are a real, if rare, possibility.
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    account_id = db.list_accounts()[0]["id"]
    db.add_transaction(date="2026-09-05", payee="Tesco", category_id=None, amount=-42.50,
                        currency="GBP", account_id=account_id)

    csv_path = tmp_path / "statement.csv"
    csv_path.write_text("Date,Payee,Amount\n2026-09-05,Tesco,-42.50\n", encoding="utf-8")

    batch_id, staged = csv_import_preview(db, str(csv_path), account_id=account_id)
    assert staged[0]["likely_duplicate"] is True
    committed, skipped = csv_import_commit(db, batch_id)

    assert committed == 1
    all_tx = db.conn.execute(
        "SELECT COUNT(*) n FROM transactions WHERE account_id=? AND date='2026-09-05'", (account_id,)
    ).fetchone()["n"]
    assert all_tx == 2  # the original entry plus the imported one — nothing silently dropped

    db.close()


def test_export_account_statement_csv_writes_running_balance_per_row(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    account_id = db.list_accounts()[0]["id"]
    db.add_transaction(date="2026-09-01", payee="Salary", category_id=None, amount=1000.0,
                        currency="GBP", account_id=account_id)
    db.add_transaction(date="2026-09-05", payee="Rent", category_id=None, amount=-400.0,
                        currency="GBP", account_id=account_id)

    out_path = tmp_path / "statement.csv"
    count = export_account_statement_csv(db, account_id, str(out_path))

    assert count == 2
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "date,payee,category,amount,currency,note,running_balance"
    # newest first (matches account_ledger's order): Rent leaves a running balance of 600.0
    assert "Rent" in lines[1] and "600.0" in lines[1]
    assert "Salary" in lines[2] and "1000.0" in lines[2]

    db.close()


def test_set_transaction_splits_stores_and_retrieves_splits(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split", "need", 0)
    db.add_category("Household Split", "need", 0)
    groceries_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split")
    household_id = next(c["id"] for c in db.list_categories() if c["name"] == "Household Split")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=groceries_id,
                                amount=-60.0, currency="GBP")

    db.set_transaction_splits(tx_id, [
        {"category_id": groceries_id, "amount": -40.0, "note": "food"},
        {"category_id": household_id, "amount": -20.0, "note": "cleaning supplies"},
    ])

    splits = db.get_transaction_splits(tx_id)
    assert len(splits) == 2
    assert {s["category_id"]: s["amount"] for s in splits} == {groceries_id: -40.0, household_id: -20.0}

    db.close()


def test_set_transaction_splits_rejects_amounts_that_dont_sum_to_the_transaction_total(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split2", "need", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split2")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=cat_id,
                                amount=-60.0, currency="GBP")

    with pytest.raises(ValueError):
        db.set_transaction_splits(tx_id, [{"category_id": cat_id, "amount": -40.0, "note": ""}])

    db.close()


def test_set_transaction_splits_with_empty_list_clears_existing_splits(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split3", "need", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split3")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=cat_id,
                                amount=-60.0, currency="GBP")
    db.set_transaction_splits(tx_id, [{"category_id": cat_id, "amount": -60.0, "note": ""}])

    db.set_transaction_splits(tx_id, [])

    assert db.get_transaction_splits(tx_id) == []

    db.close()


def test_deleting_a_split_transaction_also_deletes_its_splits(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split4", "need", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split4")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=cat_id,
                                amount=-60.0, currency="GBP")
    db.set_transaction_splits(tx_id, [{"category_id": cat_id, "amount": -60.0, "note": ""}])

    db.delete_transaction(tx_id)

    assert db.get_transaction_splits(tx_id) == []

    db.close()


def test_category_budget_status_uses_split_amounts_when_a_transaction_is_split(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split5", "need", 100.0)
    db.add_category("Household Split5", "need", 50.0)
    groceries_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split5")
    household_id = next(c["id"] for c in db.list_categories() if c["name"] == "Household Split5")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=groceries_id,
                                amount=-60.0, currency="GBP")
    db.set_transaction_splits(tx_id, [
        {"category_id": groceries_id, "amount": -40.0, "note": ""},
        {"category_id": household_id, "amount": -20.0, "note": ""},
    ])

    status = category_budget_status(db, 2026, 9)

    groceries_row = next(r for r in status if r["category"]["id"] == groceries_id)
    household_row = next(r for r in status if r["category"]["id"] == household_id)
    assert groceries_row["spent"] == pytest.approx(40.0)
    assert household_row["spent"] == pytest.approx(20.0)

    db.close()


def test_spend_by_kind_uses_split_amounts_when_a_transaction_is_split(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split6", "need", 0)
    db.add_category("Fun Split6", "want", 0)
    groceries_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split6")
    fun_id = next(c["id"] for c in db.list_categories() if c["name"] == "Fun Split6")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=groceries_id,
                                amount=-60.0, currency="GBP")
    db.set_transaction_splits(tx_id, [
        {"category_id": groceries_id, "amount": -40.0, "note": ""},
        {"category_id": fun_id, "amount": -20.0, "note": ""},
    ])

    totals = spend_by_kind(db, 2026, 9)

    assert totals["need"] == pytest.approx(40.0)
    assert totals["want"] == pytest.approx(20.0)

    db.close()


def test_set_transaction_tags_stores_and_retrieves_tag_names(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Flight", category_id=None,
                                amount=-200.0, currency="GBP")

    db.set_transaction_tags(tx_id, ["Canada Trip", "reimbursable"])

    tags = db.get_transaction_tags(tx_id)
    assert sorted(tags) == ["Canada Trip", "reimbursable"]

    db.close()


def test_set_transaction_tags_replaces_previous_tags(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Flight", category_id=None,
                                amount=-200.0, currency="GBP")
    db.set_transaction_tags(tx_id, ["Canada Trip"])

    db.set_transaction_tags(tx_id, ["work"])

    assert db.get_transaction_tags(tx_id) == ["work"]

    db.close()


def test_set_transaction_tags_reuses_an_existing_tag_across_transactions(tmp_path):
    db = _db(tmp_path)
    tx1 = db.add_transaction(date="2026-09-01", payee="Flight", category_id=None,
                              amount=-200.0, currency="GBP")
    tx2 = db.add_transaction(date="2026-09-02", payee="Hotel", category_id=None,
                              amount=-100.0, currency="GBP")
    db.set_transaction_tags(tx1, ["Canada Trip"])
    db.set_transaction_tags(tx2, ["Canada Trip"])

    all_tags = db.list_all_tags()

    assert all_tags == ["Canada Trip"]  # one shared tag row, not duplicated

    db.close()


def test_transactions_by_tag_returns_every_transaction_carrying_that_tag(tmp_path):
    db = _db(tmp_path)
    tx1 = db.add_transaction(date="2026-09-01", payee="Flight", category_id=None,
                              amount=-200.0, currency="GBP")
    tx2 = db.add_transaction(date="2026-09-02", payee="Hotel", category_id=None,
                              amount=-100.0, currency="GBP")
    tx3 = db.add_transaction(date="2026-09-03", payee="Coffee", category_id=None,
                              amount=-3.0, currency="GBP")
    db.set_transaction_tags(tx1, ["Canada Trip"])
    db.set_transaction_tags(tx2, ["Canada Trip"])

    tagged = db.transactions_by_tag("Canada Trip")

    assert sorted(t["id"] for t in tagged) == sorted([tx1, tx2])
    assert tx3 not in [t["id"] for t in tagged]

    db.close()


def test_deleting_a_tagged_transaction_also_removes_its_tag_links(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Flight", category_id=None,
                                amount=-200.0, currency="GBP")
    db.set_transaction_tags(tx_id, ["Canada Trip"])

    db.delete_transaction(tx_id)

    assert db.get_transaction_tags(tx_id) == []
    # the tag itself survives (other transactions might still use it) — only the link is removed
    assert db.list_all_tags() == ["Canada Trip"]

    db.close()


def test_add_reimbursement_creates_a_pending_entry(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Dinner", category_id=None,
                                amount=-60.0, currency="GBP")

    reimb_id = db.add_reimbursement(tx_id, "Alex", 20.0, note="split the bill")

    outstanding = db.list_outstanding_reimbursements()
    assert len(outstanding) == 1
    assert outstanding[0]["id"] == reimb_id
    assert outstanding[0]["owed_by"] == "Alex"
    assert outstanding[0]["amount"] == pytest.approx(20.0)
    assert outstanding[0]["status"] == "pending"
    assert outstanding[0]["payee"] == "Dinner"

    db.close()


def test_settle_reimbursement_removes_it_from_outstanding(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Dinner", category_id=None,
                                amount=-60.0, currency="GBP")
    reimb_id = db.add_reimbursement(tx_id, "Alex", 20.0)

    db.settle_reimbursement(reimb_id, settled_date="2026-09-10")

    assert db.list_outstanding_reimbursements() == []
    row = db.conn.execute("SELECT * FROM reimbursements WHERE id=?", (reimb_id,)).fetchone()
    assert row["status"] == "settled"
    assert row["settled_date"] == "2026-09-10"

    db.close()


def test_get_reimbursements_for_transaction_returns_all_entries_for_that_transaction(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Dinner", category_id=None,
                                amount=-60.0, currency="GBP")
    db.add_reimbursement(tx_id, "Alex", 20.0)
    db.add_reimbursement(tx_id, "Sam", 20.0)

    entries = db.get_reimbursements_for_transaction(tx_id)

    assert sorted(e["owed_by"] for e in entries) == ["Alex", "Sam"]

    db.close()


def test_deleting_a_transaction_also_deletes_its_reimbursements(tmp_path):
    db = _db(tmp_path)
    tx_id = db.add_transaction(date="2026-09-01", payee="Dinner", category_id=None,
                                amount=-60.0, currency="GBP")
    db.add_reimbursement(tx_id, "Alex", 20.0)

    db.delete_transaction(tx_id)

    assert db.get_reimbursements_for_transaction(tx_id) == []
    assert db.list_outstanding_reimbursements() == []

    db.close()


def test_update_category_changes_name_kind_and_budget(tmp_path):
    db = _db(tmp_path)
    db.add_category("Old Name", "want", 50.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Old Name")

    db.update_category(cat_id, name="New Name", kind="need", monthly_budget=75.0)

    cat = next(c for c in db.list_categories() if c["id"] == cat_id)
    assert cat["name"] == "New Name"
    assert cat["kind"] == "need"
    assert cat["monthly_budget"] == pytest.approx(75.0)

    db.close()


def test_update_category_leaves_unspecified_fields_unchanged(tmp_path):
    db = _db(tmp_path)
    db.add_category("Keep Name", "want", 50.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Keep Name")

    db.update_category(cat_id, monthly_budget=100.0)

    cat = next(c for c in db.list_categories() if c["id"] == cat_id)
    assert cat["name"] == "Keep Name"
    assert cat["kind"] == "want"
    assert cat["monthly_budget"] == pytest.approx(100.0)

    db.close()


def test_update_account_core_changes_name_currency_and_liquid(tmp_path):
    db = _db(tmp_path)
    db.add_account("Old Name", "asset", 100.0, currency="GBP", liquid=False)
    acc_id = db.list_accounts()[0]["id"]

    db.update_account_core(acc_id, name="New Name", currency="USD", liquid=True)

    acc = db.get_account(acc_id)
    assert acc["name"] == "New Name"
    assert acc["currency"] == "USD"
    assert acc["liquid"] == 1

    db.close()


def test_update_account_core_leaves_unspecified_fields_unchanged(tmp_path):
    db = _db(tmp_path)
    db.add_account("Keep Name", "asset", 100.0, currency="GBP", liquid=True)
    acc_id = db.list_accounts()[0]["id"]

    db.update_account_core(acc_id, currency="EUR")

    acc = db.get_account(acc_id)
    assert acc["name"] == "Keep Name"
    assert acc["currency"] == "EUR"
    assert acc["liquid"] == 1

    db.close()


def test_update_security_transaction_edits_the_lot_and_recomputes_gains(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    account_id = db.list_accounts()[0]["id"]
    db.add_security_transaction(account_id, "VWRL", "2026-01-01", "buy", 100, 10.0)
    sell_id = db.add_security_transaction(account_id, "VWRL", "2026-02-01", "sell", 50, 15.0)
    before = db.conn.execute("SELECT realized_gain FROM security_lots WHERE id=?", (sell_id,)).fetchone()
    assert before["realized_gain"] == pytest.approx(250.0)  # avg cost 10, gain = 50*15 - 50*10

    db.update_security_transaction(sell_id, price=20.0)  # sell at 20 instead of 15

    after = db.conn.execute("SELECT realized_gain, price FROM security_lots WHERE id=?", (sell_id,)).fetchone()
    assert after["price"] == pytest.approx(20.0)
    assert after["realized_gain"] == pytest.approx(500.0)  # 50*20 - 50*10

    db.close()


def test_delete_security_transaction_removes_the_lot_and_recomputes_gains(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    account_id = db.list_accounts()[0]["id"]
    db.add_security_transaction(account_id, "VWRL", "2026-01-01", "buy", 100, 10.0)
    sell_id = db.add_security_transaction(account_id, "VWRL", "2026-02-01", "sell", 50, 15.0)

    db.delete_security_transaction(sell_id)

    remaining = db.conn.execute("SELECT * FROM security_lots WHERE id=?", (sell_id,)).fetchone()
    assert remaining is None
    quantity, cost, avg_cost = db.security_pool_state(account_id, "VWRL")
    assert quantity == pytest.approx(100.0)  # the sell is gone, full buy remains in the pool

    db.close()


def test_export_transactions_editable_csv_includes_category_account_and_tags(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_category("Groceries Export", "need", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Export")
    tx_id = db.add_transaction(date="2026-09-01", payee="Tesco", category_id=cat_id, amount=-40.0,
                                currency="GBP", account_id=acc_id)
    db.set_transaction_tags(tx_id, ["food", "weekly"])

    out_path = tmp_path / "transactions.csv"
    count = export_transactions_editable_csv(db, str(out_path))

    assert count == 1
    rows = _read_csv(out_path)
    row = rows[0]
    assert row["id"] == str(tx_id)
    assert row["payee"] == "Tesco"
    assert row["category"] == "Groceries Export"
    assert row["amount"] == "-40.0"
    assert row["account"] == "Current Account"
    assert set(row["tags"].split(",")) == {"food", "weekly"}
    assert row["status"] == ""


def test_export_transactions_editable_csv_flags_reconciled_and_transfer_rows(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    db.add_account("Savings", "asset", 0.0, currency="GBP")
    acc = {a["name"]: a["id"] for a in db.list_accounts()}
    tx_id = db.add_transaction(date="2026-09-02", payee="Payday", category_id=None, amount=1000.0,
                                currency="GBP", account_id=acc["Current Account"])
    db.reconcile_transaction(tx_id)
    db.transfer_between_accounts(acc["Current Account"], acc["Savings"], 100.0, date="2026-09-03")

    out_path = tmp_path / "transactions.csv"
    export_transactions_editable_csv(db, str(out_path))

    rows = _read_csv(out_path)
    reconciled_row = next(r for r in rows if r["id"] == str(tx_id))
    assert reconciled_row["status"] == "reconciled"
    transfer_rows = [r for r in rows if r["status"] == "transfer"]
    assert len(transfer_rows) == 2


def test_export_transactions_editable_csv_flags_split_transactions(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Split Export", "need", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Split Export")
    tx_id = db.add_transaction(date="2026-09-01", payee="Target", category_id=cat_id,
                                amount=-60.0, currency="GBP")
    db.set_transaction_splits(tx_id, [{"category_id": cat_id, "amount": -60.0, "note": ""}])

    out_path = tmp_path / "transactions.csv"
    export_transactions_editable_csv(db, str(out_path))

    row = _read_csv(out_path)[0]
    assert row["status"] == "split"


def test_export_accounts_editable_csv_writes_expected_columns(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 250.0, currency="GBP", liquid=True,
                    subtype="cash")
    acc_id = db.list_accounts()[0]["id"]

    out_path = tmp_path / "accounts.csv"
    count = export_accounts_editable_csv(db, str(out_path))

    assert count == 1
    row = _read_csv(out_path)[0]
    assert row["id"] == str(acc_id)
    assert row["name"] == "Current Account"
    assert row["kind"] == "asset"
    assert row["subtype"] == "cash"
    assert row["balance"] == "250.0"
    assert row["currency"] == "GBP"
    assert row["liquid"] == "1"


def test_export_categories_editable_csv_writes_expected_columns(tmp_path):
    db = _db(tmp_path)
    db.add_category("Groceries Cat Export", "need", 200.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Cat Export")

    out_path = tmp_path / "categories.csv"
    export_categories_editable_csv(db, str(out_path))

    rows = _read_csv(out_path)
    row = next(r for r in rows if r["id"] == str(cat_id))
    assert row["name"] == "Groceries Cat Export"
    assert row["kind"] == "need"
    assert row["monthly_budget"] == "200.0"


def test_export_investments_editable_csv_writes_expected_columns(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    acc_id = db.list_accounts()[0]["id"]
    lot_id = db.add_security_transaction(acc_id, "VWRL", "2026-01-01", "buy", 100, 10.0)

    out_path = tmp_path / "investments.csv"
    count = export_investments_editable_csv(db, str(out_path))

    assert count == 1
    row = _read_csv(out_path)[0]
    assert row["id"] == str(lot_id)
    assert row["account"] == "Index Fund"
    assert row["security"] == "VWRL"
    assert row["action"] == "buy"
    assert row["quantity"] == "100.0" or row["quantity"] == "100"
    assert row["price"] == "10.0"


def test_apply_transactions_csv_adds_a_new_row_with_blank_id(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    db.add_category("Groceries Apply", "need", 0)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [{
        "id": "", "date": "2026-09-01", "payee": "Tesco", "category": "Groceries Apply",
        "amount": "-40", "currency": "GBP", "note": "", "account": "Current Account",
        "tags": "", "status": "",
    }])

    report = apply_transactions_csv(db, str(csv_path))

    assert report["added"] == 1
    assert report["edited"] == 0
    assert report["deleted"] == 0
    txs = db.list_transactions()
    assert len(txs) == 1
    assert txs[0]["payee"] == "Tesco"
    assert txs[0]["amount"] == pytest.approx(-40.0)

    db.close()


def test_apply_transactions_csv_edits_an_existing_row(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_category("Groceries Apply Edit", "need", 0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Groceries Apply Edit")
    tx_id = db.add_transaction(date="2026-09-01", payee="Tesco", category_id=cat_id,
                                amount=-40.0, currency="GBP", account_id=acc_id)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [{
        "id": str(tx_id), "date": "2026-09-01", "payee": "Tesco Extra", "category": "Groceries Apply Edit",
        "amount": "-45.50", "currency": "GBP", "note": "corrected", "account": "Current Account",
        "tags": "corrected", "status": "",
    }])

    report = apply_transactions_csv(db, str(csv_path))

    assert report["edited"] == 1
    assert report["added"] == 0
    tx = db.list_transactions()[0]
    assert tx["payee"] == "Tesco Extra"
    assert tx["amount"] == pytest.approx(-45.50)
    assert tx["note"] == "corrected"
    assert db.get_transaction_tags(tx_id) == ["corrected"]

    db.close()


def test_apply_transactions_csv_leaves_unchanged_rows_alone(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    tx_id = db.add_transaction(date="2026-09-01", payee="Tesco", category_id=None,
                                amount=-40.0, currency="GBP", account_id=acc_id)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [{
        "id": str(tx_id), "date": "2026-09-01", "payee": "Tesco", "category": "",
        "amount": "-40.0", "currency": "GBP", "note": "", "account": "Current Account",
        "tags": "", "status": "",
    }])

    report = apply_transactions_csv(db, str(csv_path))

    assert report["edited"] == 0
    assert report["added"] == 0
    assert report["deleted"] == 0

    db.close()


def test_apply_transactions_csv_deletes_a_row_removed_from_the_file(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    tx_id = db.add_transaction(date="2026-09-01", payee="Tesco", category_id=None,
                                amount=-40.0, currency="GBP", account_id=acc_id)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [])  # the row is simply gone

    report = apply_transactions_csv(db, str(csv_path))

    assert report["deleted"] == 1
    assert db.list_transactions() == []

    db.close()


def test_apply_transactions_csv_skips_edits_to_a_reconciled_row(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    tx_id = db.add_transaction(date="2026-09-01", payee="Payday", category_id=None,
                                amount=1000.0, currency="GBP", account_id=acc_id)
    db.reconcile_transaction(tx_id)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [{
        "id": str(tx_id), "date": "2026-09-01", "payee": "TAMPERED", "category": "",
        "amount": "9999", "currency": "GBP", "note": "", "account": "Current Account",
        "tags": "", "status": "reconciled",
    }])

    report = apply_transactions_csv(db, str(csv_path))

    assert report["edited"] == 0
    assert len(report["skipped"]) == 1
    tx = db.list_transactions()[0]
    assert tx["payee"] == "Payday"  # unchanged
    assert tx["amount"] == pytest.approx(1000.0)

    db.close()


def test_apply_transactions_csv_does_not_delete_a_reconciled_row_omitted_from_the_file(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    tx_id = db.add_transaction(date="2026-09-01", payee="Payday", category_id=None,
                                amount=1000.0, currency="GBP", account_id=acc_id)
    db.reconcile_transaction(tx_id)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [])  # protected row omitted entirely

    report = apply_transactions_csv(db, str(csv_path))

    assert report["deleted"] == 0
    assert len(report["skipped"]) == 1
    assert len(db.list_transactions()) == 1  # still there

    db.close()


def test_apply_transactions_csv_skips_a_transfer_leg_entirely(tmp_path):
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    db.add_account("Savings", "asset", 0.0, currency="GBP")
    acc = {a["name"]: a["id"] for a in db.list_accounts()}
    db.transfer_between_accounts(acc["Current Account"], acc["Savings"], 100.0, date="2026-09-03")

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [])  # both legs omitted

    report = apply_transactions_csv(db, str(csv_path))

    assert report["deleted"] == 0
    assert len(report["skipped"]) == 2  # both legs flagged
    assert len(db.list_transactions()) == 2  # both still there

    db.close()


def test_apply_transactions_csv_does_not_delete_an_existing_row_whose_edit_has_a_typo(tmp_path):
    # A validation error on an EDIT (e.g. a mistyped account name) must only
    # skip that edit -- it must never fall through to the "missing from the
    # file -> delete" path, since the row is clearly still present, just
    # invalid. Losing a transaction over a typo would be a serious bug.
    db = _db(tmp_path)
    db.add_account("Current Account", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    tx_id = db.add_transaction(date="2026-09-01", payee="Tesco", category_id=None,
                                amount=-40.0, currency="GBP", account_id=acc_id)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [{
        "id": str(tx_id), "date": "2026-09-01", "payee": "Tesco", "category": "",
        "amount": "-40.0", "currency": "GBP", "note": "", "account": "Curent Acount",  # typo
        "tags": "", "status": "",
    }])

    report = apply_transactions_csv(db, str(csv_path))

    assert report["deleted"] == 0
    assert len(report["skipped"]) == 1
    assert len(db.list_transactions()) == 1  # still there, not deleted

    db.close()


def test_apply_transactions_csv_reports_an_unknown_account_name_without_crashing(tmp_path):
    db = _db(tmp_path)

    csv_path = tmp_path / "transactions.csv"
    _write_csv(csv_path, TX_CSV_FIELDS, [{
        "id": "", "date": "2026-09-01", "payee": "Tesco", "category": "",
        "amount": "-40", "currency": "GBP", "note": "", "account": "Nonexistent Account",
        "tags": "", "status": "",
    }])

    report = apply_transactions_csv(db, str(csv_path))

    assert report["added"] == 0
    assert len(report["skipped"]) == 1
    assert "Nonexistent Account" in report["skipped"][0]["reason"]
    assert db.list_transactions() == []

    db.close()


def test_apply_accounts_csv_adds_and_edits(tmp_path):
    db = _db(tmp_path)
    db.add_account("Old Name", "asset", 100.0, currency="GBP", liquid=False)
    acc_id = db.list_accounts()[0]["id"]

    csv_path = tmp_path / "accounts.csv"
    _write_csv(csv_path, ["id", "name", "kind", "subtype", "balance", "currency", "liquid"], [
        {"id": str(acc_id), "name": "New Name", "kind": "asset", "subtype": "cash",
         "balance": "150.0", "currency": "USD", "liquid": "1"},
        {"id": "", "name": "Brand New Account", "kind": "asset", "subtype": "cash",
         "balance": "0", "currency": "GBP", "liquid": "0"},
    ])

    report = apply_accounts_csv(db, str(csv_path))

    assert report["added"] == 1
    assert report["edited"] == 1
    updated = db.get_account(acc_id)
    assert updated["name"] == "New Name"
    assert updated["balance"] == pytest.approx(150.0)
    assert updated["currency"] == "USD"
    assert any(a["name"] == "Brand New Account" for a in db.list_accounts())

    db.close()


def test_apply_categories_csv_adds_and_edits(tmp_path):
    db = _db(tmp_path)
    db.add_category("Old Cat Name", "want", 50.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Old Cat Name")

    csv_path = tmp_path / "categories.csv"
    _write_csv(csv_path, ["id", "name", "kind", "monthly_budget"], [
        {"id": str(cat_id), "name": "New Cat Name", "kind": "need", "monthly_budget": "80"},
        {"id": "", "name": "Brand New Category", "kind": "want", "monthly_budget": "0"},
    ])

    report = apply_categories_csv(db, str(csv_path))

    assert report["added"] == 1
    assert report["edited"] == 1
    updated = next(c for c in db.list_categories() if c["id"] == cat_id)
    assert updated["name"] == "New Cat Name"
    assert updated["kind"] == "need"
    assert any(c["name"] == "Brand New Category" for c in db.list_categories())

    db.close()


def test_apply_categories_csv_accepts_income_kind(tmp_path):
    db = _db(tmp_path)
    db.add_category("Old Salary Name", "income", 0.0)
    cat_id = next(c["id"] for c in db.list_categories() if c["name"] == "Old Salary Name")

    csv_path = tmp_path / "categories.csv"
    _write_csv(csv_path, ["id", "name", "kind", "monthly_budget"], [
        {"id": str(cat_id), "name": "Salary", "kind": "income", "monthly_budget": "0"},
        {"id": "", "name": "Freelance Income", "kind": "income", "monthly_budget": "0"},
    ])

    report = apply_categories_csv(db, str(csv_path))

    assert report["skipped"] == []
    assert report["added"] == 1
    assert report["edited"] == 1
    updated = next(c for c in db.list_categories() if c["id"] == cat_id)
    assert updated["name"] == "Salary"
    assert updated["kind"] == "income"
    assert any(c["name"] == "Freelance Income" and c["kind"] == "income" for c in db.list_categories())

    db.close()


def test_apply_investments_csv_adds_and_edits(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    acc_id = db.list_accounts()[0]["id"]
    lot_id = db.add_security_transaction(acc_id, "VWRL", "2026-01-01", "buy", 100, 10.0)

    csv_path = tmp_path / "investments.csv"
    _write_csv(csv_path, ["id", "account", "security", "date", "action", "quantity", "price",
                          "fees", "currency", "note", "realized_gain"], [
        {"id": str(lot_id), "account": "Index Fund", "security": "VWRL", "date": "2026-01-01",
         "action": "buy", "quantity": "100", "price": "12.0", "fees": "0", "currency": "GBP",
         "note": "corrected price", "realized_gain": ""},
        {"id": "", "account": "Index Fund", "security": "VWRL", "date": "2026-02-01",
         "action": "sell", "quantity": "50", "price": "15.0", "fees": "0", "currency": "GBP",
         "note": "", "realized_gain": ""},
    ])

    report = apply_investments_csv(db, str(csv_path))

    assert report["added"] == 1
    assert report["edited"] == 1
    lots = db.list_securities(acc_id)
    assert len(lots) >= 1
    edited_lot = db.conn.execute("SELECT * FROM security_lots WHERE id=?", (lot_id,)).fetchone()
    assert edited_lot["price"] == pytest.approx(12.0)

    db.close()


def test_apply_investments_csv_does_not_delete_an_existing_lot_whose_edit_has_a_typo(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    acc_id = db.list_accounts()[0]["id"]
    lot_id = db.add_security_transaction(acc_id, "VWRL", "2026-01-01", "buy", 100, 10.0)

    csv_path = tmp_path / "investments.csv"
    _write_csv(csv_path, ["id", "account", "security", "date", "action", "quantity", "price",
                          "fees", "currency", "note", "realized_gain"], [
        {"id": str(lot_id), "account": "Indx Fnd", "security": "VWRL", "date": "2026-01-01",  # typo
         "action": "buy", "quantity": "100", "price": "10.0", "fees": "0", "currency": "GBP",
         "note": "", "realized_gain": ""},
    ])

    report = apply_investments_csv(db, str(csv_path))

    assert report["deleted"] == 0
    assert len(report["skipped"]) == 1
    remaining = db.conn.execute("SELECT * FROM security_lots WHERE id=?", (lot_id,)).fetchone()
    assert remaining is not None  # still there, not deleted

    db.close()


def test_apply_investments_csv_deletes_a_lot_removed_from_the_file(tmp_path):
    db = _db(tmp_path)
    db.add_account("Index Fund", "asset", 0.0, currency="GBP", subtype="investment")
    acc_id = db.list_accounts()[0]["id"]
    lot_id = db.add_security_transaction(acc_id, "VWRL", "2026-01-01", "buy", 100, 10.0)

    csv_path = tmp_path / "investments.csv"
    _write_csv(csv_path, ["id", "account", "security", "date", "action", "quantity", "price",
                          "fees", "currency", "note", "realized_gain"], [])  # lot omitted

    report = apply_investments_csv(db, str(csv_path))

    assert report["deleted"] == 1
    remaining = db.conn.execute("SELECT * FROM security_lots WHERE id=?", (lot_id,)).fetchone()
    assert remaining is None

    db.close()


def test_refresh_profile_csvs_writes_all_four_files(tmp_path):
    db = _db(tmp_path)
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()

    refresh_profile_csvs(db, str(profile_dir))

    assert (profile_dir / "transactions.csv").exists()
    assert (profile_dir / "accounts.csv").exists()
    assert (profile_dir / "categories.csv").exists()
    assert (profile_dir / "investments.csv").exists()

    db.close()


def test_apply_profile_csvs_backs_up_the_database_before_applying(tmp_path):
    db_path = tmp_path / "profile" / "profile.db"
    db_path.parent.mkdir()
    db = Database(str(db_path))
    profile_dir = str(db_path.parent)
    refresh_profile_csvs(db, profile_dir)

    result = apply_profile_csvs(db, profile_dir, str(db_path))

    assert os.path.exists(result["backup_path"])
    backups_dir = db_path.parent / "csv_sync_backups"
    assert backups_dir.is_dir()
    assert len(list(backups_dir.iterdir())) == 1

    db.close()


def test_apply_profile_csvs_applies_accounts_before_transactions_so_new_names_resolve(tmp_path):
    # A new account added in accounts.csv and a new transaction in
    # transactions.csv that references it by name, applied in the SAME
    # pass, must both succeed -- meaning accounts.csv has to be processed
    # before transactions.csv, not after.
    db_path = tmp_path / "profile" / "profile.db"
    db_path.parent.mkdir()
    db = Database(str(db_path))
    profile_dir = str(db_path.parent)
    refresh_profile_csvs(db, profile_dir)

    _write_csv(os.path.join(profile_dir, "accounts.csv"),
               ["id", "name", "kind", "subtype", "balance", "currency", "liquid"], [
        {"id": "", "name": "Brand New Account", "kind": "asset", "subtype": "cash",
         "balance": "0", "currency": "GBP", "liquid": "0"},
    ])
    _write_csv(os.path.join(profile_dir, "transactions.csv"), TX_CSV_FIELDS, [
        {"id": "", "date": "2026-09-01", "payee": "First Deposit", "category": "",
         "amount": "500", "currency": "GBP", "note": "", "account": "Brand New Account",
         "tags": "", "status": ""},
    ])
    _write_csv(os.path.join(profile_dir, "categories.csv"), ["id", "name", "kind", "monthly_budget"], [])
    _write_csv(os.path.join(profile_dir, "investments.csv"),
               ["id", "account", "security", "date", "action", "quantity", "price", "fees",
                "currency", "note", "realized_gain"], [])

    result = apply_profile_csvs(db, profile_dir, str(db_path))

    assert not any("Unknown account" in s["reason"] for s in result["skipped"])
    assert result["added"] == 2  # the account + the transaction
    tx = db.list_transactions()[0]
    assert tx["payee"] == "First Deposit"
    assert tx["account_name"] == "Brand New Account"

    db.close()


def test_categories_table_allows_income_kind_after_migration(tmp_path):
    db = _db(tmp_path)
    db.add_category("Salary", "income", 0)
    cats = {c["name"]: c for c in db.list_categories()}
    assert cats["Salary"]["kind"] == "income"
    db.close()


def test_categories_migration_preserves_existing_rows_ids_and_is_idempotent(tmp_path):
    path = str(tmp_path / "reopen.db")
    db = Database(path)
    db.add_category("Groceries Budget", "need", 200)
    before = {c["name"]: (c["id"], c["kind"], c["monthly_budget"]) for c in db.list_categories()}
    db.close()

    # Reopening re-runs _migrate() against an already-migrated file — must no-op cleanly.
    db2 = Database(path)
    after = {c["name"]: (c["id"], c["kind"], c["monthly_budget"]) for c in db2.list_categories()}
    assert after == before
    db2.add_category("Salary", "income", 0)  # still works after a second migration pass
    assert any(c["kind"] == "income" for c in db2.list_categories())
    db2.close()


def test_categories_migration_rebuilds_old_schema_table(tmp_path):
    """Verify the migration actually rebuilds the categories table when needed.

    This test creates a database with the OLD schema (CHECK constraint without 'income'),
    inserts test data, closes it, then opens it via Database() to trigger the migration.
    This exercises the actual migration code path that was added.
    """
    import sqlite3
    path = str(tmp_path / "old_schema.db")

    # Create a database with the OLD schema (no 'income' in CHECK constraint)
    conn_old = sqlite3.connect(path)
    conn_old.row_factory = sqlite3.Row
    conn_old.execute("PRAGMA foreign_keys = ON")

    # Create the categories table with the OLD CHECK constraint
    conn_old.execute("""
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('need','want','saving')),
            monthly_budget REAL DEFAULT 0
        )
    """)

    # Insert some test data
    conn_old.execute("INSERT INTO categories(id, name, kind, monthly_budget) VALUES (1, 'Housing', 'need', 500)")
    conn_old.execute("INSERT INTO categories(id, name, kind, monthly_budget) VALUES (2, 'Entertainment', 'want', 100)")
    conn_old.execute("INSERT INTO categories(id, name, kind, monthly_budget) VALUES (3, 'Emergency Fund', 'saving', 0)")
    conn_old.commit()

    # Capture the pre-migration state
    old_categories = {
        r["id"]: (r["name"], r["kind"], r["monthly_budget"])
        for r in conn_old.execute("SELECT id, name, kind, monthly_budget FROM categories")
    }
    conn_old.close()

    # Now open the database via the real Database class, which will trigger _migrate()
    # This should detect the old schema and rebuild the table
    db = Database(path)

    # Verify that PRAGMA foreign_keys is ON after migration
    foreign_keys_setting = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert foreign_keys_setting == 1, "PRAGMA foreign_keys should be ON (1) after migration"

    # Verify all pre-existing categories are preserved with exact same data
    current_categories = {
        c["id"]: (c["name"], c["kind"], c["monthly_budget"])
        for c in db.list_categories()
    }

    for cat_id, (old_name, old_kind, old_budget) in old_categories.items():
        assert cat_id in current_categories, f"Category id {cat_id} was lost during migration"
        curr_name, curr_kind, curr_budget = current_categories[cat_id]
        assert curr_name == old_name, f"Category {cat_id} name changed from {old_name} to {curr_name}"
        assert curr_kind == old_kind, f"Category {cat_id} kind changed from {old_kind} to {curr_kind}"
        assert curr_budget == old_budget, f"Category {cat_id} budget changed from {old_budget} to {curr_budget}"

    # Verify that we can now add income categories (the whole point of the migration)
    db.add_category("Salary", "income", 0)
    income_cats = [c for c in db.list_categories() if c["kind"] == "income"]
    assert len(income_cats) > 0, "Should be able to add income categories after migration"
    assert income_cats[0]["name"] == "Salary", "Income category name should be 'Salary'"

    db.close()


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


def test_income_by_category_totals_this_months_positive_transactions(tmp_path):
    db = _db(tmp_path)
    db.add_account("Checking", "asset", 0.0, currency="GBP")
    acc_id = db.list_accounts()[0]["id"]
    db.add_category("Salary", "income", 0)
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
    # "Groceries" already exists as a seeded default category — reuse it
    # rather than re-adding (add_category has no OR IGNORE, so a literal
    # re-add collides on the UNIQUE name constraint).
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
    db.add_category("Household", "want", 100)
    # "Groceries" already exists as a seeded default category — reuse it
    # rather than re-adding (add_category has no OR IGNORE, so a literal
    # re-add collides on the UNIQUE name constraint).
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
