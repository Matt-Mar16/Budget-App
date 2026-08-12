import argparse
import datetime
from pathlib import Path

import openpyxl
import pandas as pd

TRANSACTIONS_SHEET = "Transactions"
TRANSACTIONS_TABLE = "TransactionsTable"
COLUMNS = ["Date", "Account", "Category", "Description", "Amount", "Currency", "Exchange Rate"]


def _read_data_rows(ws):
    rows = []
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        if all(value is None for value in row):
            continue
        rows.append(dict(zip(COLUMNS, row)))
    return rows


def _clear_data_rows(ws):
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    if TRANSACTIONS_TABLE in ws.tables:
        last_col = chr(ord("A") + len(COLUMNS) - 1)
        ws.tables[TRANSACTIONS_TABLE].ref = f"A1:{last_col}1"


def sync(excel_path, log_path, backups_dir, now=None):
    now = now or datetime.datetime.now()

    wb = openpyxl.load_workbook(excel_path)
    ws = wb[TRANSACTIONS_SHEET]

    rows = _read_data_rows(ws)
    if not rows:
        return 0

    pushed_df = pd.DataFrame(rows, columns=COLUMNS)

    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backups_dir / f"pushed_{now.strftime('%Y-%m-%d_%H%M%S')}.csv"
    pushed_df.to_csv(backup_path, index=False)

    log_path = Path(log_path)
    log_df = pushed_df.copy()
    log_df["synced_at"] = now.isoformat()
    log_df.to_csv(log_path, mode="a", index=False, header=not log_path.exists())

    _clear_data_rows(ws)
    wb.save(excel_path)

    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Push phone-entered transactions into the persistent log and reset the inbox sheet."
    )
    parser.add_argument("--excel", default="Data.xlsx", help="Path to the Excel workbook")
    parser.add_argument("--log", default="data/transactions_log.csv", help="Path to the persistent transactions log")
    parser.add_argument("--backups-dir", default="data/backups", help="Directory to write pre-clear backups")
    args = parser.parse_args()

    count = sync(args.excel, args.log, args.backups_dir)
    if count:
        print(f"Synced {count} transaction(s) into {args.log}. The Transactions sheet is now back to headers only.")
    else:
        print("No new transactions to sync.")


if __name__ == "__main__":
    main()
