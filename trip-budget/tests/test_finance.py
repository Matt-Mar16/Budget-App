import pandas as pd
import pytest

from finance import (
    parse_label,
    load_transactions_log,
    budget_vs_actual,
    account_running_balance,
    effective_exchange_rate,
    sankey_flows,
    is_below_threshold,
)


def test_parse_label_splits_category_and_currency():
    assert parse_label("Groceries (CAD)") == ("Groceries", "CAD")


def test_parse_label_handles_label_with_no_currency_suffix():
    assert parse_label("Currency Exchange") == ("Currency Exchange", None)


def test_load_transactions_log_parses_dates_and_derives_category(tmp_path):
    csv_path = tmp_path / "transactions_log.csv"
    csv_path.write_text(
        "Date,Account,Category,Description,Amount,Currency,Exchange Rate,synced_at\n"
        "2026-09-03,CAD Chequing,Groceries (CAD),Superstore,-62.40,CAD,,2026-09-10T12:00:00\n"
    )

    df = load_transactions_log(csv_path)

    assert df.loc[0, "category"] == "Groceries"
    assert df.loc[0, "Date"] == pd.Timestamp("2026-09-03")
    assert df.loc[0, "Amount"] == -62.40


def test_load_transactions_log_gives_a_header_only_log_a_usable_datetime_date_column(tmp_path):
    csv_path = tmp_path / "transactions_log.csv"
    csv_path.write_text("Date,Account,Category,Description,Amount,Currency,Exchange Rate,synced_at\n")

    df = load_transactions_log(csv_path)

    assert df.empty
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])


def test_budget_vs_actual_flags_overspend_and_computes_remaining():
    categories_df = pd.DataFrame([
        {"Category": "Groceries", "Currency": "CAD", "Monthly budget": 400},
        {"Category": "Rent", "Currency": "CAD", "Monthly budget": 900},
    ])
    transactions_df = pd.DataFrame([
        {"Date": pd.Timestamp("2026-09-03"), "category": "Groceries", "Currency": "CAD", "Amount": -62.40},
        {"Date": pd.Timestamp("2026-09-10"), "category": "Groceries", "Currency": "CAD", "Amount": -450.00},
        {"Date": pd.Timestamp("2026-09-15"), "category": "Rent", "Currency": "CAD", "Amount": -900.00},
    ])

    result = budget_vs_actual(transactions_df, categories_df, currency="CAD", month=(2026, 9)).set_index("category")

    assert result.loc["Groceries", "actual"] == pytest.approx(512.40)
    assert result.loc["Groceries", "budget"] == 400
    assert result.loc["Groceries", "remaining"] == pytest.approx(-112.40)
    assert result.loc["Groceries", "over_budget"] == True
    assert result.loc["Rent", "over_budget"] == False
    assert result.loc["Rent", "remaining"] == pytest.approx(0)


def test_budget_vs_actual_excludes_categories_with_no_spend_yet():
    categories_df = pd.DataFrame([
        {"Category": "Groceries", "Currency": "CAD", "Monthly budget": 400},
    ])
    transactions_df = pd.DataFrame(columns=["category", "Currency", "Amount", "Date"])
    transactions_df["Date"] = pd.to_datetime(transactions_df["Date"])

    result = budget_vs_actual(transactions_df, categories_df, currency="CAD", month=(2026, 9)).set_index("category")

    assert result.loc["Groceries", "actual"] == 0
    assert result.loc["Groceries", "over_budget"] == False


def test_budget_vs_actual_only_counts_spend_within_the_given_month():
    categories_df = pd.DataFrame([
        {"Category": "Groceries", "Currency": "CAD", "Monthly budget": 400},
    ])
    transactions_df = pd.DataFrame([
        {"Date": pd.Timestamp("2026-08-28"), "category": "Groceries", "Currency": "CAD", "Amount": -80.00},
        {"Date": pd.Timestamp("2026-09-03"), "category": "Groceries", "Currency": "CAD", "Amount": -62.40},
        {"Date": pd.Timestamp("2026-10-01"), "category": "Groceries", "Currency": "CAD", "Amount": -30.00},
    ])

    result = budget_vs_actual(transactions_df, categories_df, currency="CAD", month=(2026, 9)).set_index("category")

    assert result.loc["Groceries", "actual"] == pytest.approx(62.40)


def test_account_running_balance_adds_starting_balance_and_transactions():
    accounts_df = pd.DataFrame([
        {"Account": "UK Bank", "Currency": "GBP", "Starting balance": 1200.0,
         "Starting date": pd.Timestamp("2026-09-01")},
    ])
    transactions_df = pd.DataFrame([
        {"Account": "UK Bank", "Date": pd.Timestamp("2026-09-02"), "Amount": 1500.0},
        {"Account": "UK Bank", "Date": pd.Timestamp("2026-09-05"), "Amount": -500.0},
        {"Account": "CAD Chequing", "Date": pd.Timestamp("2026-09-05"), "Amount": 860.0},
    ])

    balance = account_running_balance(transactions_df, accounts_df, "UK Bank")

    assert balance == pytest.approx(1200 + 1500 - 500)


def test_account_running_balance_raises_clear_error_for_unknown_account():
    accounts_df = pd.DataFrame([
        {"Account": "UK Bank", "Currency": "GBP", "Starting balance": 1200.0,
         "Starting date": pd.Timestamp("2026-09-01")},
    ])
    transactions_df = pd.DataFrame(columns=["Account", "Date", "Amount"])

    with pytest.raises(ValueError, match="UK Bnak"):
        account_running_balance(transactions_df, accounts_df, "UK Bnak")


def test_account_running_balance_respects_as_of_date():
    accounts_df = pd.DataFrame([
        {"Account": "UK Bank", "Currency": "GBP", "Starting balance": 1200.0,
         "Starting date": pd.Timestamp("2026-09-01")},
    ])
    transactions_df = pd.DataFrame([
        {"Account": "UK Bank", "Date": pd.Timestamp("2026-09-02"), "Amount": 1500.0},
        {"Account": "UK Bank", "Date": pd.Timestamp("2026-09-10"), "Amount": -500.0},
    ])

    balance = account_running_balance(
        transactions_df, accounts_df, "UK Bank", as_of=pd.Timestamp("2026-09-05")
    )

    assert balance == pytest.approx(1200 + 1500)


def test_load_transactions_log_returns_empty_dataframe_when_file_does_not_exist(tmp_path):
    df = load_transactions_log(tmp_path / "does_not_exist.csv")

    assert df.empty
    assert list(df.columns) == [
        "Date", "Account", "Category", "Description", "Amount",
        "Currency", "Exchange Rate", "synced_at", "category",
    ]


def test_load_transactions_log_gives_an_empty_log_a_usable_datetime_date_column(tmp_path):
    df = load_transactions_log(tmp_path / "does_not_exist.csv")

    assert pd.api.types.is_datetime64_any_dtype(df["Date"])


def test_effective_exchange_rate_returns_none_when_no_exchanges_logged():
    transactions_df = pd.DataFrame([
        {"category": "Groceries", "Currency": "CAD", "Amount": -62.40},
    ])

    assert effective_exchange_rate(transactions_df) is None


def test_effective_exchange_rate_aggregates_across_exchanges_without_pairing_rows():
    transactions_df = pd.DataFrame([
        {"category": "Currency Exchange", "Currency": "GBP", "Amount": -500.0},
        {"category": "Currency Exchange", "Currency": "CAD", "Amount": 860.0},
        {"category": "Currency Exchange", "Currency": "GBP", "Amount": -300.0},
        {"category": "Currency Exchange", "Currency": "CAD", "Amount": 519.0},
        {"category": "Groceries", "Currency": "CAD", "Amount": -62.40},
    ])

    rate = effective_exchange_rate(transactions_df)

    assert rate == pytest.approx(1379 / 800)


def test_sankey_flows_builds_balanced_nodes_and_links():
    transactions_df = pd.DataFrame([
        {"category": "Income", "Currency": "GBP", "Amount": 1500.0},
        {"category": "Subscriptions", "Currency": "GBP", "Amount": -30.0},
        {"category": "Currency Exchange", "Currency": "GBP", "Amount": -500.0},
        {"category": "Currency Exchange", "Currency": "CAD", "Amount": 860.0},
        {"category": "Groceries", "Currency": "CAD", "Amount": -62.40},
    ])

    flows = sankey_flows(transactions_df)
    link_by_pair = {
        (flows["nodes"][link["source"]], flows["nodes"][link["target"]]): link["value"]
        for link in flows["links"]
    }

    assert link_by_pair[("Income (GBP)", "Subscriptions (GBP)")] == pytest.approx(30.0)
    assert link_by_pair[("Income (GBP)", "Currency Exchange")] == pytest.approx(500.0)
    assert link_by_pair[("Income (GBP)", "Unspent GBP")] == pytest.approx(1500 - 30 - 500)
    assert link_by_pair[("Currency Exchange", "CAD Funds")] == pytest.approx(860.0)
    assert link_by_pair[("CAD Funds", "Groceries (CAD)")] == pytest.approx(62.40)
    assert link_by_pair[("CAD Funds", "Unspent CAD")] == pytest.approx(860 - 62.40)


def test_is_below_threshold_flags_negative_or_low_balance():
    assert is_below_threshold(-5.0, threshold=0) is True
    assert is_below_threshold(100.0, threshold=0) is False
    assert is_below_threshold(50.0, threshold=100) is True
