import argparse
from pathlib import Path

import analyze
import finance
from sync_transactions import sync


def run_dashboard(excel_path, log_path, charts_dir, backups_dir, now=None, month=None):
    # Sync must run first so the report below reads the log with this
    # session's phone-entered rows already appended (and the sheet cleared).
    sync(excel_path, log_path, backups_dir, now=now)

    accounts_df, categories_df = analyze.load_reference_data(excel_path)
    transactions_df = finance.load_transactions_log(log_path)

    report = analyze.build_report(transactions_df, accounts_df, categories_df, month=month)
    analyze.print_report(report)

    charts_dir = Path(charts_dir)
    analyze.draw_bar_charts(report, charts_dir)
    analyze.draw_sankey(report, charts_dir / "money_flow.html")
    print(f"\nCharts written to {charts_dir}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Load new entries from Data.xlsx, generate the report and charts, then clear the sheet."
    )
    parser.add_argument("--excel", default="Data.xlsx", help="Path to the Excel workbook")
    parser.add_argument("--log", default="data/transactions_log.csv", help="Path to the persistent transactions log")
    parser.add_argument("--charts-dir", default="data/charts", help="Directory to write bar charts and the Sankey diagram")
    parser.add_argument("--backups-dir", default="data/backups", help="Directory to write pre-clear backups")
    parser.add_argument("--month", type=analyze._parse_month, default=None,
                         help="Month to report budget-vs-actual for, as YYYY-MM (default: current month)")
    args = parser.parse_args()

    run_dashboard(args.excel, args.log, args.charts_dir, args.backups_dir, month=args.month)


if __name__ == "__main__":
    main()
