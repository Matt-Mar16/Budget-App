import argparse

import profiles
from finance_core import Database
from inbox_sync import build_inbox_workbook, sync_inbox


def main():
    parser = argparse.ArgumentParser(
        description="Load phone-entered transactions from an inbox workbook into THE LEDGER, then clear it."
    )
    parser.add_argument("--profile", required=True, help="Profile slug to sync into (see Profiles/ folder)")
    parser.add_argument("--excel", default="Inbox.xlsx", help="Path to the inbox workbook")
    parser.add_argument("--backups-dir", default="Profiles/inbox_backups",
                         help="Directory to write pre-clear backups")
    parser.add_argument("--build", action="store_true",
                         help="(Re)generate the inbox workbook from the profile's current accounts/categories")
    args = parser.parse_args()

    db = Database(profiles.db_path_for(args.profile))
    try:
        if args.build:
            build_inbox_workbook(db, args.excel)
            print(f"Wrote {args.excel} with accounts/categories from profile '{args.profile}'.")
        else:
            count = sync_inbox(args.excel, db, args.backups_dir)
            if count:
                print(f"Synced {count} transaction(s) into profile '{args.profile}'. Inbox is back to headers only.")
            else:
                print("No new transactions to sync.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
