import pandas as pd
import pytest

from analyze import build_report, load_reference_data, draw_bar_charts, draw_sankey, print_report
from build_template import build_template


def _sample_data():
    accounts_df = pd.DataFrame([
        {"Account": "UK Bank", "Currency": "GBP", "Starting balance": 1200.0,
         "Starting date": pd.Timestamp("2026-09-01")},
        {"Account": "CAD Chequing", "Currency": "CAD", "Starting balance": 0.0,
         "Starting date": pd.Timestamp("2026-09-01")},
    ])
    categories_df = pd.DataFrame([
        {"Category": "Groceries", "Currency": "CAD", "Monthly budget": 400},
        {"Category": "Subscriptions", "Currency": "GBP", "Monthly budget": 30},
        {"Category": "Income", "Currency": "GBP", "Monthly budget": None},
        {"Category": "Currency Exchange", "Currency": None, "Monthly budget": None},
    ])
    transactions_df = pd.DataFrame([
        {"Date": pd.Timestamp("2026-09-02"), "Account": "UK Bank", "category": "Income",
         "Currency": "GBP", "Amount": 1500.0},
        {"Date": pd.Timestamp("2026-09-03"), "Account": "CAD Chequing", "category": "Groceries",
         "Currency": "CAD", "Amount": -62.40},
        {"Date": pd.Timestamp("2026-09-05"), "Account": "UK Bank", "category": "Currency Exchange",
         "Currency": "GBP", "Amount": -500.0},
        {"Date": pd.Timestamp("2026-09-05"), "Account": "CAD Chequing", "category": "Currency Exchange",
         "Currency": "CAD", "Amount": 860.0},
    ])
    return transactions_df, accounts_df, categories_df


def test_build_report_aggregates_budgets_balances_rate_and_sankey():
    transactions_df, accounts_df, categories_df = _sample_data()

    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    cad_budget = report["budget_vs_actual"]["CAD"].set_index("category")
    assert cad_budget.loc["Groceries", "actual"] == pytest.approx(62.40)

    assert report["account_balances"]["UK Bank"] == pytest.approx(1200 + 1500 - 500)
    assert report["account_balances"]["CAD Chequing"] == pytest.approx(860 - 62.40)

    assert report["exchange_rate"] == pytest.approx(860 / 500)
    assert report["low_balance_flags"] == {}
    assert "nodes" in report["sankey"]


def test_build_report_flags_accounts_below_threshold():
    transactions_df, accounts_df, categories_df = _sample_data()
    transactions_df = pd.concat([transactions_df, pd.DataFrame([
        {"Date": pd.Timestamp("2026-09-06"), "Account": "CAD Chequing", "category": "Groceries",
         "Currency": "CAD", "Amount": -2000.0},
    ])], ignore_index=True)

    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    assert "CAD Chequing" in report["low_balance_flags"]
    assert "UK Bank" not in report["low_balance_flags"]


def test_build_report_defaults_to_the_current_month_when_not_given(monkeypatch):
    import datetime
    import analyze

    class _FixedDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 15)

    monkeypatch.setattr(analyze.datetime, "date", _FixedDate)

    transactions_df, accounts_df, categories_df = _sample_data()

    report = build_report(transactions_df, accounts_df, categories_df)

    assert report["month"] == (2026, 9)


def test_build_report_only_counts_the_given_months_spend():
    transactions_df, accounts_df, categories_df = _sample_data()
    transactions_df = pd.concat([transactions_df, pd.DataFrame([
        {"Date": pd.Timestamp("2026-10-02"), "Account": "CAD Chequing", "category": "Groceries",
         "Currency": "CAD", "Amount": -1000.0},
    ])], ignore_index=True)

    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    cad_budget = report["budget_vs_actual"]["CAD"].set_index("category")
    assert cad_budget.loc["Groceries", "actual"] == pytest.approx(62.40)


def test_load_reference_data_reads_accounts_and_categories_sheets(tmp_path):
    excel_path = tmp_path / "Data.xlsx"
    build_template(excel_path)

    accounts_df, categories_df = load_reference_data(excel_path)

    assert "UK Bank" in list(accounts_df["Account"])
    assert "Groceries" in list(categories_df["Category"])


def test_draw_bar_charts_writes_one_png_per_currency(tmp_path):
    transactions_df, accounts_df, categories_df = _sample_data()
    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    draw_bar_charts(report, tmp_path)

    assert (tmp_path / "budget_vs_actual_CAD.png").exists()
    assert (tmp_path / "budget_vs_actual_GBP.png").exists()


def test_draw_sankey_writes_an_html_file(tmp_path):
    transactions_df, accounts_df, categories_df = _sample_data()
    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    output_path = tmp_path / "money_flow.html"
    draw_sankey(report, output_path)

    assert output_path.exists()


def test_print_report_includes_exchange_rate_and_account_balances(capsys):
    transactions_df, accounts_df, categories_df = _sample_data()
    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    print_report(report)

    captured = capsys.readouterr()
    assert "exchange rate" in captured.out.lower()
    assert "UK Bank" in captured.out


def test_print_report_shows_which_month_it_is_reporting_on(capsys):
    transactions_df, accounts_df, categories_df = _sample_data()
    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    print_report(report)

    captured = capsys.readouterr()
    assert "2026-09" in captured.out


def test_print_report_handles_no_exchanges_logged_yet_without_crashing(capsys):
    transactions_df = pd.DataFrame([
        {"Date": pd.Timestamp("2026-09-03"), "Account": "CAD Chequing", "category": "Groceries",
         "Currency": "CAD", "Amount": -62.40},
    ])
    accounts_df = pd.DataFrame([
        {"Account": "CAD Chequing", "Currency": "CAD", "Starting balance": 0.0,
         "Starting date": pd.Timestamp("2026-09-01")},
    ])
    categories_df = pd.DataFrame([
        {"Category": "Groceries", "Currency": "CAD", "Monthly budget": 400},
    ])
    report = build_report(transactions_df, accounts_df, categories_df, month=(2026, 9))

    print_report(report)

    captured = capsys.readouterr()
    assert "nan" not in captured.out.lower()
    assert "no currency exchanges logged yet" in captured.out.lower()
