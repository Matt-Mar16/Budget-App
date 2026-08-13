import argparse
import datetime
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import plotly.graph_objects as go

import finance


def build_report(transactions_df, accounts_df, categories_df, month=None, as_of=None, low_balance_threshold=0.0):
    if month is None:
        today = datetime.date.today()
        month = (today.year, today.month)

    currencies = sorted(categories_df["Currency"].dropna().unique())
    budget_vs_actual = {
        currency: finance.budget_vs_actual(transactions_df, categories_df, currency, month)
        for currency in currencies
    }

    account_balances = {
        account: finance.account_running_balance(transactions_df, accounts_df, account, as_of=as_of)
        for account in accounts_df["Account"]
    }

    low_balance_flags = {
        account: balance
        for account, balance in account_balances.items()
        if finance.is_below_threshold(balance, threshold=low_balance_threshold)
    }

    return {
        "month": month,
        "budget_vs_actual": budget_vs_actual,
        "account_balances": account_balances,
        "low_balance_flags": low_balance_flags,
        "exchange_rate": finance.effective_exchange_rate(transactions_df),
        "sankey": finance.sankey_flows(transactions_df),
    }


def load_reference_data(excel_path):
    accounts_df = pd.read_excel(excel_path, sheet_name="Accounts")
    categories_df = pd.read_excel(excel_path, sheet_name="Categories")
    return accounts_df, categories_df


def draw_bar_charts(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for currency, df in report["budget_vs_actual"].items():
        fig, ax = plt.subplots()
        # Budget and Actual bars are offset left/right of each category's
        # integer tick position so they sit side by side instead of overlapping.
        positions = range(len(df))
        ax.bar([p - 0.2 for p in positions], df["budget"], width=0.4, label="Budget")
        ax.bar([p + 0.2 for p in positions], df["actual"], width=0.4, label="Actual")
        ax.set_xticks(list(positions))
        ax.set_xticklabels(df["category"], rotation=45, ha="right")
        ax.set_title(f"Budget vs Actual ({currency})")
        ax.legend()
        fig.tight_layout()
        fig.savefig(output_dir / f"budget_vs_actual_{currency}.png")
        plt.close(fig)


def draw_sankey(report, output_path):
    flows = report["sankey"]
    fig = go.Figure(go.Sankey(
        node=dict(label=flows["nodes"]),
        link=dict(
            source=[link["source"] for link in flows["links"]],
            target=[link["target"] for link in flows["links"]],
            value=[link["value"] for link in flows["links"]],
        ),
    ))
    fig.write_html(str(output_path))


def print_report(report):
    if report["exchange_rate"] is None:
        print("Effective exchange rate (GBP -> CAD): no currency exchanges logged yet")
    else:
        print(f"Effective exchange rate (GBP -> CAD): {report['exchange_rate']:.4f}")
    print()

    year, month_num = report["month"]
    for currency, df in report["budget_vs_actual"].items():
        print(f"-- Budget vs Actual ({currency}, {year:04d}-{month_num:02d}) --")
        for _, row in df.iterrows():
            flag = "  OVER BUDGET" if row["over_budget"] else ""
            print(
                f"  {row['category']:<20} budget {row['budget']:>10.2f}  "
                f"actual {row['actual']:>10.2f}  remaining {row['remaining']:>10.2f}{flag}"
            )
        print()

    print("-- Account balances --")
    for account, balance in report["account_balances"].items():
        flag = "  LOW BALANCE" if account in report["low_balance_flags"] else ""
        print(f"  {account:<20} {balance:>10.2f}{flag}")


def _parse_month(value):
    year, month_num = value.split("-")
    return int(year), int(month_num)


def main():
    parser = argparse.ArgumentParser(description="Analyze trip budget spending.")
    parser.add_argument("--excel", default="Data.xlsx",
                         help="Path to the Excel workbook (Accounts/Categories sheets)")
    parser.add_argument("--log", default="data/transactions_log.csv",
                         help="Path to the persistent transactions log")
    parser.add_argument("--charts-dir", default="data/charts",
                         help="Directory to write bar charts and the Sankey diagram")
    parser.add_argument("--month", type=_parse_month, default=None,
                         help="Month to report budget-vs-actual for, as YYYY-MM (default: current month)")
    args = parser.parse_args()

    accounts_df, categories_df = load_reference_data(args.excel)
    transactions_df = finance.load_transactions_log(args.log)

    report = build_report(transactions_df, accounts_df, categories_df, month=args.month)
    print_report(report)

    charts_dir = Path(args.charts_dir)
    draw_bar_charts(report, charts_dir)
    draw_sankey(report, charts_dir / "money_flow.html")
    print(f"\nCharts written to {charts_dir}")


if __name__ == "__main__":
    main()
