"""
finance_core.py
Data layer + financial math for "The Complete Ledger" budgeting app.

Everything here is deliberately simple arithmetic (means, ratios, sums) —
per Part X of the research, no fake ML / GARCH / VaR machinery. Just the
handful of mechanisms that actually repeat across the literature.
"""

import sqlite3
import datetime
import calendar
import uuid
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Optional

DB_PATH = "ledger.db"
SCHEMA_VERSION = 2


class ReconciledTransactionError(Exception):
    """Raised when code tries to edit/delete a reconciled transaction
    without explicitly unlocking it first."""
    pass


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        self._migrate()
        self._seed_defaults()

    def close(self):
        """Closes the underlying SQLite connection. Always call this before
        deleting the database file or the OS (especially Windows) will keep
        the file locked even after the window is destroyed."""
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def _create_schema(self):
        c = self.conn
        c.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS fx_rates (
            currency TEXT PRIMARY KEY,
            rate_to_reporting REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('need','want','saving','income')),
            monthly_budget REAL DEFAULT 0,
            sort_order INTEGER
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('asset','liability')),
            subtype TEXT,
            balance REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'GBP',
            liquid INTEGER NOT NULL DEFAULT 0,
            credit_limit REAL DEFAULT 0,
            cashback_rate REAL DEFAULT 0,
            contributions REAL DEFAULT 0,
            due_day INTEGER,
            expected_return_pct REAL DEFAULT 0,
            return_volatility_pct REAL DEFAULT 0,
            monthly_contribution REAL DEFAULT 0,
            cashback_auto_invest_account_id INTEGER REFERENCES accounts(id),
            cashback_monthly_cap REAL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            payee TEXT,
            category_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'GBP',
            note TEXT,
            account_id INTEGER,
            cashback REAL DEFAULT 0,
            cashback_redeemed INTEGER DEFAULT 0,
            is_transfer INTEGER NOT NULL DEFAULT 0,
            transfer_to_account_id INTEGER,
            transfer_group_id TEXT,
            historical_rate REAL,
            reconciled INTEGER NOT NULL DEFAULT 0,
            reconciled_date TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id),
            FOREIGN KEY(account_id) REFERENCES accounts(id),
            FOREIGN KEY(transfer_to_account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS investment_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS investment_valuations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            value REAL NOT NULL,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS security_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            security TEXT NOT NULL,
            date TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('buy','sell')),
            quantity REAL NOT NULL CHECK(quantity > 0),
            price REAL NOT NULL CHECK(price >= 0),
            fees REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT 'GBP',
            realized_gain REAL,
            note TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            balance REAL NOT NULL,
            apr REAL NOT NULL,
            min_payment REAL NOT NULL CHECK(min_payment >= 0),
            custom_payment REAL DEFAULT 0 CHECK(custom_payment >= 0),
            currency TEXT NOT NULL DEFAULT 'GBP'
        );

        CREATE TABLE IF NOT EXISTS networth_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            net_worth REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            payee TEXT,
            category_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'GBP',
            frequency TEXT NOT NULL DEFAULT 'monthly',
            next_date TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            account_id INTEGER,
            custom_interval_months INTEGER,
            FOREIGN KEY(category_id) REFERENCES categories(id),
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS ignored_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payee TEXT NOT NULL,
            dismissed_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS roundups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER,
            date TEXT NOT NULL,
            base_amount REAL NOT NULL,
            roundup_amount REAL NOT NULL,
            FOREIGN KEY(transaction_id) REFERENCES transactions(id)
        );

        CREATE TABLE IF NOT EXISTS transaction_splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            category_id INTEGER,
            amount REAL NOT NULL,
            note TEXT,
            FOREIGN KEY(transaction_id) REFERENCES transactions(id),
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS reimbursements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER NOT NULL,
            owed_by TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','settled')),
            settled_date TEXT,
            note TEXT,
            FOREIGN KEY(transaction_id) REFERENCES transactions(id)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transaction_tags (
            transaction_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY(transaction_id, tag_id),
            FOREIGN KEY(transaction_id) REFERENCES transactions(id),
            FOREIGN KEY(tag_id) REFERENCES tags(id)
        );

        CREATE TABLE IF NOT EXISTS import_staging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            raw_date TEXT,
            raw_payee TEXT,
            raw_amount TEXT,
            raw_currency TEXT,
            raw_category TEXT,
            parsed_date TEXT,
            parsed_amount REAL,
            parsed_currency TEXT,
            category_id INTEGER,
            account_id INTEGER,
            parsed_ok INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            committed INTEGER NOT NULL DEFAULT 0,
            likely_duplicate INTEGER NOT NULL DEFAULT 0
        );
        """)
        c.commit()

    def _migrate(self):
        """Adds columns/tables introduced after the initial release. Safe to
        run every time the app starts — every step checks before acting, so
        existing profiles (with existing data) upgrade in place without
        losing anything."""
        c = self.conn

        def existing_cols(table):
            return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}

        acc_cols = existing_cols("accounts")
        if "subtype" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN subtype TEXT")
            c.execute("UPDATE accounts SET subtype='cash' WHERE kind='asset' AND subtype IS NULL")
            c.execute("UPDATE accounts SET subtype='loan' WHERE kind='liability' AND subtype IS NULL")
        if "credit_limit" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN credit_limit REAL DEFAULT 0")
        if "cashback_rate" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN cashback_rate REAL DEFAULT 0")
        if "contributions" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN contributions REAL DEFAULT 0")
            # for pre-existing investment-like accounts (none yet exist at this point,
            # since 'investment' subtype didn't exist before this migration) this is
            # simply a fresh 0 starting point going forward.
        if "due_day" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN due_day INTEGER")   # credit cards: 1-28
        if "expected_return_pct" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN expected_return_pct REAL DEFAULT 0")  # investments
        if "monthly_contribution" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN monthly_contribution REAL DEFAULT 0")  # investments

        if "return_volatility_pct" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN return_volatility_pct REAL DEFAULT 0")
        if "cashback_auto_invest_account_id" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN cashback_auto_invest_account_id INTEGER "
                       "REFERENCES accounts(id)")
        if "cashback_monthly_cap" not in acc_cols:
            c.execute("ALTER TABLE accounts ADD COLUMN cashback_monthly_cap REAL DEFAULT 0")  # 0 = no cap

        tx_cols = existing_cols("transactions")
        if "account_id" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN account_id INTEGER")
        if "cashback" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN cashback REAL DEFAULT 0")
        if "cashback_redeemed" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN cashback_redeemed INTEGER DEFAULT 0")
        if "is_transfer" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN is_transfer INTEGER NOT NULL DEFAULT 0")
        if "transfer_to_account_id" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN transfer_to_account_id INTEGER")
        if "transfer_group_id" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN transfer_group_id TEXT")
        if "historical_rate" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN historical_rate REAL")
        if "reconciled" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN reconciled INTEGER NOT NULL DEFAULT 0")
        if "reconciled_date" not in tx_cols:
            c.execute("ALTER TABLE transactions ADD COLUMN reconciled_date TEXT")

        staging_cols = existing_cols("import_staging")
        if "likely_duplicate" not in staging_cols:
            c.execute("ALTER TABLE import_staging ADD COLUMN likely_duplicate INTEGER NOT NULL DEFAULT 0")

        rec_cols = existing_cols("recurring")
        if "account_id" not in rec_cols:
            c.execute("ALTER TABLE recurring ADD COLUMN account_id INTEGER")
        if "custom_interval_months" not in rec_cols:
            c.execute("ALTER TABLE recurring ADD COLUMN custom_interval_months INTEGER")

        debt_cols = existing_cols("debts")
        if "custom_payment" not in debt_cols:
            c.execute("ALTER TABLE debts ADD COLUMN custom_payment REAL DEFAULT 0")

        cat_row = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='categories'"
        ).fetchone()
        if cat_row and "'income'" not in cat_row["sql"]:
            c.execute("PRAGMA foreign_keys=OFF")
            with c:
                c.execute(
                    "CREATE TABLE categories_new ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "name TEXT UNIQUE NOT NULL, "
                    "kind TEXT NOT NULL CHECK(kind IN ('need','want','saving','income')), "
                    "monthly_budget REAL DEFAULT 0)"
                )
                c.execute(
                    "INSERT INTO categories_new(id, name, kind, monthly_budget) "
                    "SELECT id, name, kind, monthly_budget FROM categories"
                )
                c.execute("DROP TABLE categories")
                c.execute("ALTER TABLE categories_new RENAME TO categories")
            c.execute("PRAGMA foreign_keys=ON")

        cat_cols = existing_cols("categories")
        if "sort_order" not in cat_cols:
            c.execute("ALTER TABLE categories ADD COLUMN sort_order INTEGER")
            # Backfill with id so pre-existing categories keep a stable order
            # (previously implicit alphabetical order) rather than all tying at 0.
            c.execute("UPDATE categories SET sort_order = id WHERE sort_order IS NULL")

        had_contributions_col = "contributions" in acc_cols

        c.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS roundups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER,
            date TEXT NOT NULL,
            base_amount REAL NOT NULL,
            roundup_amount REAL NOT NULL,
            FOREIGN KEY(transaction_id) REFERENCES transactions(id)
        );

        CREATE TABLE IF NOT EXISTS investment_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS investment_valuations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            value REAL NOT NULL,
            FOREIGN KEY(account_id) REFERENCES accounts(id)
        );

        CREATE TABLE IF NOT EXISTS import_staging (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            row_index INTEGER NOT NULL,
            raw_date TEXT,
            raw_payee TEXT,
            raw_amount TEXT,
            raw_currency TEXT,
            raw_category TEXT,
            parsed_date TEXT,
            parsed_amount REAL,
            parsed_currency TEXT,
            category_id INTEGER,
            account_id INTEGER,
            parsed_ok INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            committed INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_tx_account_date ON transactions(account_id, date);
        CREATE INDEX IF NOT EXISTS idx_tx_transfer_group ON transactions(transfer_group_id);
        """)

        # One-time backfill: pre-existing 'contributions' balances on
        # investment accounts become an opening entry in the new
        # append-only log, so nothing is lost when reads switch over to it.
        if had_contributions_col:
            seeded = c.execute("SELECT COUNT(*) n FROM investment_contributions").fetchone()["n"]
            if seeded == 0:
                for row in c.execute(
                    "SELECT id, contributions FROM accounts WHERE subtype='investment' AND contributions > 0"
                ):
                    c.execute(
                        "INSERT INTO investment_contributions(account_id, date, amount, note) "
                        "VALUES (?, ?, ?, ?)",
                        (row["id"], datetime.date.today().isoformat(), row["contributions"],
                         "Opening balance (migrated)"),
                    )

        c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                   (str(SCHEMA_VERSION),))
        c.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
        c.commit()

    def _seed_defaults(self):
        c = self.conn
        with c:  # atomic: meta + settings + fx + categories all-or-nothing
            defaults = {
                "reporting_currency": "GBP",
                "hourly_wage": "0",          # for life-energy view; 0 = disabled
                "monthly_income": "0",
                "monthly_savings_target": "0",
                "emergency_fund_months_goal": "6",
                "roundup_enabled": "0",
                "roundup_nearest": "1",      # round expenses up to the nearest £1 by default
                "roundup_multiplier": "1",   # 1x = plain round-up; 2x/3x boosts it like Acorns/Monzo
            }
            for k, v in defaults.items():
                c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
            c.execute("INSERT OR IGNORE INTO fx_rates(currency, rate_to_reporting) VALUES ('GBP', 1.0)")
            default_categories = [
                ("Housing", "need"), ("Groceries", "need"), ("Utilities", "need"),
                ("Transportation", "need"), ("Insurance", "need"), ("Debt Payments", "need"),
                ("Dining Out", "want"), ("Entertainment", "want"), ("Shopping", "want"),
                ("Subscriptions", "want"), ("Travel", "want"),
                ("Emergency Fund", "saving"), ("Retirement", "saving"), ("Investing", "saving"),
            ]
            for i, (name, kind) in enumerate(default_categories):
                c.execute("INSERT OR IGNORE INTO categories(name, kind, monthly_budget, sort_order) "
                          "VALUES (?, ?, 0, ?)", (name, kind, i))

            # meta: profile self-description, used by profiles.py instead of
            # a central profiles.json. Only stamped if not already present
            # (profiles.py fills in name/avatar/color right after creation).
            meta_defaults = {
                "schema_version": str(SCHEMA_VERSION),
                "profile_name": "Profile",
                "avatar": "🦉",
                "color": "#5B8DEF",
                "created": datetime.date.today().isoformat(),
                "last_opened": datetime.date.today().isoformat(),
                "encrypted": "0",   # profile-level encryption flag; see note in set_encrypted()
            }
            for k, v in meta_defaults.items():
                c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", (k, v))

    # ---- meta helpers (profile self-description; replaces profiles.json) ----
    def get_meta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def touch_last_opened(self):
        self.set_meta("last_opened", datetime.date.today().isoformat())

    def set_encrypted(self, flag: bool):
        """Flags the profile as encrypted-at-rest. NOTE: this does not
        itself encrypt the SQLite file — real encryption (e.g. SQLCipher)
        is a separate dependency decision, since this app is otherwise
        stdlib-only. This flag lets the UI show the right lock icon and
        warn appropriately once real encryption is wired in."""
        self.set_meta("encrypted", "1" if flag else "0")

    # ---- settings helpers ----
    def get_setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def get_setting_float(self, key, default=0.0):
        try:
            return float(self.get_setting(key, default))
        except (TypeError, ValueError):
            return default

    def get_setting_int(self, key, default=0):
        try:
            return int(self.get_setting(key, default))
        except (TypeError, ValueError):
            return default

    # ---- FX ----
    def set_fx_rate(self, currency, rate):
        self.conn.execute(
            "INSERT INTO fx_rates(currency, rate_to_reporting) VALUES (?, ?) "
            "ON CONFLICT(currency) DO UPDATE SET rate_to_reporting=excluded.rate_to_reporting",
            (currency.upper(), rate),
        )
        self.conn.commit()

    def get_fx_rates(self):
        return {r["currency"]: r["rate_to_reporting"] for r in self.conn.execute("SELECT * FROM fx_rates")}

    def to_reporting(self, amount, currency):
        rates = self.get_fx_rates()
        rate = rates.get(currency.upper(), 1.0)
        return amount * rate

    def convert(self, amount, from_currency, to_currency):
        """Converts between two arbitrary currencies via their rate_to_reporting,
        e.g. for crediting a transaction in USD against a GBP account balance."""
        if from_currency.upper() == to_currency.upper():
            return amount
        rates = self.get_fx_rates()
        from_rate = rates.get(from_currency.upper(), 1.0)
        to_rate = rates.get(to_currency.upper(), 1.0)
        if to_rate == 0:
            return amount
        return amount * from_rate / to_rate

    # ---- categories ----
    def list_categories(self):
        return self.conn.execute("SELECT * FROM categories ORDER BY kind, sort_order").fetchall()

    def add_category(self, name, kind, monthly_budget=0):
        self.conn.execute(
            "INSERT INTO categories(name, kind, monthly_budget, sort_order) "
            "VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM categories))",
            (name, kind, monthly_budget),
        )
        self.conn.commit()

    def move_category(self, category_id, direction):
        """Swaps this category's sort_order with its same-kind neighbor
        immediately above (direction='up') or below (direction='down') it.
        A no-op at either end of the kind's list."""
        cat = self.conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        if not cat:
            return
        siblings = self.conn.execute(
            "SELECT id, sort_order FROM categories WHERE kind=? ORDER BY sort_order", (cat["kind"],)
        ).fetchall()
        idx = next(i for i, r in enumerate(siblings) if r["id"] == category_id)
        swap_idx = idx - 1 if direction == "up" else idx + 1
        if swap_idx < 0 or swap_idx >= len(siblings):
            return
        other = siblings[swap_idx]
        with self.conn:
            self.conn.execute("UPDATE categories SET sort_order=? WHERE id=?",
                               (other["sort_order"], category_id))
            self.conn.execute("UPDATE categories SET sort_order=? WHERE id=?",
                               (cat["sort_order"], other["id"]))

    def set_category_budget(self, category_id, amount):
        self.conn.execute("UPDATE categories SET monthly_budget=? WHERE id=?", (amount, category_id))
        self.conn.commit()

    def update_category(self, category_id, name=None, kind=None, monthly_budget=None):
        with self.conn:
            if name is not None:
                self.conn.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))
            if kind is not None:
                self.conn.execute("UPDATE categories SET kind=? WHERE id=?", (kind, category_id))
            if monthly_budget is not None:
                self.conn.execute("UPDATE categories SET monthly_budget=? WHERE id=?",
                                   (monthly_budget, category_id))

    def delete_category(self, category_id):
        tx_count = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        split_count = self.conn.execute(
            "SELECT COUNT(*) FROM transaction_splits WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        rec_count = self.conn.execute(
            "SELECT COUNT(*) FROM recurring WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        if tx_count or split_count or rec_count:
            parts = []
            if tx_count:
                parts.append(f"{tx_count} transaction(s)")
            if split_count:
                parts.append(f"{split_count} transaction split(s)")
            if rec_count:
                parts.append(f"{rec_count} recurring item(s)")
            raise ValueError(
                "Cannot delete category — still used by " + ", ".join(parts) +
                ". Recategorize them first."
            )
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE id=?", (category_id,))

    def cashback_earned_this_month(self, account_id, date=None):
        """Sums this account's already-earned cashback for the calendar
        month containing `date` (default today) — the running total a
        cashback_monthly_cap is checked against."""
        date = date or datetime.date.today().isoformat()
        prefix = date[:7]  # "YYYY-MM"
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cashback), 0) as total FROM transactions "
            "WHERE account_id=? AND date LIKE ?", (account_id, prefix + "%"),
        ).fetchone()
        return row["total"]

    # ---- transactions ----
    def add_transaction(self, date, payee, category_id, amount, currency, note="", account_id=None,
                         apply_cashback_roundup=True, is_transfer=False):
        acc = self.get_account(account_id) if account_id else None
        cashback = 0.0
        if (apply_cashback_roundup and acc and amount < 0 and acc["subtype"] == "credit_card"
                and (acc["cashback_rate"] or 0) > 0):
            cashback = round(abs(amount) * acc["cashback_rate"] / 100.0, 2)
            cap = acc["cashback_monthly_cap"] or 0
            if cap > 0:
                earned_so_far = self.cashback_earned_this_month(account_id, date)
                cashback = max(0.0, round(min(cashback, cap - earned_so_far), 2))
        # If this card has an auto-invest target configured, cashback is
        # routed straight into that investment account's cost basis via the
        # same balance+contributions update add_investment_contribution()
        # uses, instead of sitting unredeemed for later manual redemption.
        auto_invest_id = acc["cashback_auto_invest_account_id"] if acc else None
        cashback_redeemed = 1 if (cashback > 0 and auto_invest_id) else 0
        with self.conn:  # atomic: insert + balance effect + roundup + auto-invest together
            cur = self.conn.execute(
                "INSERT INTO transactions(date, payee, category_id, amount, currency, note, account_id, "
                "cashback, cashback_redeemed, is_transfer) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (date, payee, category_id, amount, currency.upper(), note, account_id, cashback,
                 cashback_redeemed, int(is_transfer)),
            )
            tx_id = cur.lastrowid
            if acc:
                self._apply_balance_effect_nocommit(acc, amount, currency)
            if apply_cashback_roundup and amount < 0:
                self._apply_roundup_nocommit(tx_id, date, amount)
            if cashback_redeemed:
                self.conn.execute(
                    "UPDATE accounts SET balance = balance + ?, contributions = contributions + ? WHERE id=?",
                    (cashback, cashback, auto_invest_id))
                self.conn.execute(
                    "INSERT INTO investment_contributions(account_id, date, amount, note) VALUES (?, ?, ?, ?)",
                    (auto_invest_id, date, cashback, f"Auto-invested cashback from {payee}"),
                )
        return tx_id

    def add_balance_adjustment(self, account_id, actual_balance, date=None):
        """Corrects an account's tracked balance to match a real statement by
        inserting a plain adjustment transaction for the difference, so the
        correction is traceable in the ledger like any other transaction
        instead of silently overwriting `balance`. Returns the new
        transaction's id, or None if the balance already matched (no
        adjustment needed). Never triggers cashback/round-ups — a
        correction isn't a purchase. Marked is_transfer=True (with no
        transfer_group_id/paired leg) so it's excluded from monthly
        income/expense aggregates the same way real transfers are — a
        reconciliation correction isn't a cash-flow event any more than
        moving money between your own accounts is — while still showing up
        in the account's own ledger/statement, which always includes
        transfers."""
        acc = self.get_account(account_id)
        if acc is None:
            raise ValueError(f"No account with id {account_id}.")
        raw_diff = round(actual_balance - acc["balance"], 2)
        if raw_diff == 0:
            return None
        delta = -raw_diff if acc["kind"] == "liability" else raw_diff
        date = date or datetime.date.today().isoformat()
        return self.add_transaction(
            date, "Balance Adjustment", None, delta, acc["currency"],
            note="Reconciled to match statement", account_id=account_id,
            apply_cashback_roundup=False, is_transfer=True,
        )

    def _require_unreconciled(self, tx_id):
        row = self.conn.execute("SELECT reconciled FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if row and row["reconciled"]:
            raise ReconciledTransactionError(
                f"Transaction {tx_id} is reconciled/locked — unreconcile it before editing or deleting.")

    def reconcile_transaction(self, tx_id):
        with self.conn:
            self.conn.execute(
                "UPDATE transactions SET reconciled=1, reconciled_date=? WHERE id=?",
                (datetime.date.today().isoformat(), tx_id),
            )

    def unreconcile_transaction(self, tx_id):
        with self.conn:
            self.conn.execute(
                "UPDATE transactions SET reconciled=0, reconciled_date=NULL WHERE id=?", (tx_id,))

    def reconcile_many(self, tx_ids):
        """Bulk-reconcile (e.g. matching a statement import) in one transaction."""
        with self.conn:
            today = datetime.date.today().isoformat()
            self.conn.executemany(
                "UPDATE transactions SET reconciled=1, reconciled_date=? WHERE id=?",
                [(today, tid) for tid in tx_ids],
            )

    def _apply_balance_effect_nocommit(self, acc, amount, currency):
        """Keeps an account's balance in sync with the transaction ledger:
        cash/investment (asset) balances rise with income and fall with
        spending; credit cards/loans (liability) balances — the amount you
        OWE — rise when you spend on them and fall when you pay them down.
        Converts currency if the transaction wasn't logged in the account's
        own currency. No-commit: caller wraps this in `with self.conn:`."""
        native_amount = self.convert(amount, currency, acc["currency"])
        if acc["kind"] == "liability":
            new_balance = acc["balance"] - native_amount
        else:
            new_balance = acc["balance"] + native_amount
        self.conn.execute("UPDATE accounts SET balance=? WHERE id=?", (new_balance, acc["id"]))

    def _apply_balance_effect(self, acc, amount, currency):
        with self.conn:
            self._apply_balance_effect_nocommit(acc, amount, currency)

    def _apply_roundup_nocommit(self, tx_id, date, amount):
        """Rounds an expense up to the nearest configured unit and sweeps the
        difference (times the multiplier) into the Round-Up Jar account —
        an Acorns/Monzo-style spare-change savings mechanic. No-commit:
        caller wraps this in `with self.conn:`."""
        if self.get_setting("roundup_enabled", "0") != "1":
            return 0.0
        nearest = self.get_setting_float("roundup_nearest", 1.0) or 1.0
        multiplier = self.get_setting_float("roundup_multiplier", 1.0) or 1.0
        base = abs(amount)
        remainder = base % nearest
        if remainder < 1e-9:
            return 0.0
        roundup = round((nearest - remainder) * multiplier, 2)
        if roundup <= 0:
            return 0.0
        jar = self.get_or_create_roundup_jar()
        self.conn.execute("UPDATE accounts SET balance=? WHERE id=?", (jar["balance"] + roundup, jar["id"]))
        self.conn.execute(
            "INSERT INTO roundups(transaction_id, date, base_amount, roundup_amount) VALUES (?, ?, ?, ?)",
            (tx_id, date, base, roundup),
        )
        return roundup

    def _apply_roundup(self, tx_id, date, amount):
        with self.conn:
            return self._apply_roundup_nocommit(tx_id, date, amount)

    def list_roundups(self):
        return self.conn.execute("SELECT * FROM roundups ORDER BY date").fetchall()

    def total_roundups(self):
        row = self.conn.execute("SELECT COALESCE(SUM(roundup_amount), 0) as t FROM roundups").fetchone()
        return row["t"]

    # ---- cashback ----
    def get_unredeemed_cashback(self, account_id=None):
        q = "SELECT COALESCE(SUM(cashback), 0) as t FROM transactions WHERE cashback > 0 AND cashback_redeemed = 0"
        params = ()
        if account_id:
            q += " AND account_id = ?"
            params = (account_id,)
        return self.conn.execute(q, params).fetchone()["t"]

    def total_lifetime_cashback(self):
        row = self.conn.execute("SELECT COALESCE(SUM(cashback), 0) as t FROM transactions WHERE cashback > 0").fetchone()
        return row["t"]

    def cashback_by_account(self):
        rows = self.conn.execute(
            "SELECT a.name as account_name, COALESCE(SUM(t.cashback), 0) as total "
            "FROM transactions t JOIN accounts a ON t.account_id = a.id "
            "WHERE t.cashback > 0 GROUP BY a.id ORDER BY total DESC"
        ).fetchall()
        return rows

    def redeem_cashback(self, target_account_id=None):
        """Marks all unredeemed cashback as claimed and posts it as a real
        income transaction (in a 'Cashback Rewards' category), crediting
        the chosen account through the normal transaction/balance-effect
        path (not a raw balance bump) so it: shows up in that account's
        ledger, converts currency correctly if the account isn't in the
        reporting currency, and reverses cleanly if the transaction is
        later edited or deleted."""
        total = round(self.get_unredeemed_cashback(), 2)
        if total <= 0:
            return 0.0
        with self.conn:
            self.conn.execute(
                "UPDATE transactions SET cashback_redeemed = 1 WHERE cashback > 0 AND cashback_redeemed = 0")
            cat = self.conn.execute("SELECT id FROM categories WHERE name='Cashback Rewards'").fetchone()
            if not cat:
                self.conn.execute(
                    "INSERT OR IGNORE INTO categories(name, kind, monthly_budget, sort_order) "
                    "VALUES (?, ?, 0, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM categories))",
                    ("Cashback Rewards", "saving"))
                cat = self.conn.execute("SELECT id FROM categories WHERE name='Cashback Rewards'").fetchone()
            cur = self.get_setting("reporting_currency", "GBP")
            today = datetime.date.today().isoformat()
            target_acc = self.get_account(target_account_id) if target_account_id else None
            self.conn.execute(
                "INSERT INTO transactions(date, payee, category_id, amount, currency, note, account_id) "
                "VALUES (?, 'Cashback redeemed', ?, ?, ?, 'Redeemed cashback rewards', ?)",
                (today, cat["id"], total, cur, target_account_id),
            )
            if target_acc:
                self._apply_balance_effect_nocommit(target_acc, total, cur)
        return total

    def update_transaction(self, tx_id, date=None, payee=None, category_id=None, amount=None,
                            currency=None, note=None, account_id=None, force_unreconciled=False):
        """Edits a transaction in place: reverses whatever balance/round-up
        effect the OLD values had, applies the fields being changed, then
        re-applies the effect for the NEW values — all in one atomic
        transaction, so the account balance never reflects a half-applied
        edit. Any field left as None keeps its current value.

        Refuses to edit a reconciled transaction unless force_unreconciled
        is True (same contract as delete_transaction), and refuses to edit
        a transfer leg directly — transfers are two linked rows and editing
        one side without the other would leave them inconsistent; delete
        the transfer and create a new one instead."""
        tx = self.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not tx:
            raise ValueError(f"No transaction with id {tx_id}.")
        if tx["reconciled"] and not force_unreconciled:
            raise ReconciledTransactionError(
                f"Transaction {tx_id} is reconciled/locked — unreconcile it before editing.")
        if tx["is_transfer"]:
            raise ValueError(
                "This is one leg of a transfer — delete the transfer and create a new one instead "
                "of editing a single leg.")

        new_date = tx["date"] if date is None else date
        new_payee = tx["payee"] if payee is None else payee
        new_category_id = tx["category_id"] if category_id is None else category_id
        new_amount = tx["amount"] if amount is None else amount
        new_currency = (tx["currency"] if currency is None else currency).upper()
        new_note = tx["note"] if note is None else note
        new_account_id = tx["account_id"] if account_id is None else account_id

        with self.conn:
            # Reverse the OLD row's effects (balance + any round-up it swept),
            # exactly like deleting it, but without removing the row itself.
            if tx["account_id"]:
                old_acc = self.get_account(tx["account_id"])
                if old_acc:
                    old_native = self.convert(tx["amount"], tx["currency"], old_acc["currency"])
                    if old_acc["kind"] == "liability":
                        reverted = old_acc["balance"] + old_native
                    else:
                        reverted = old_acc["balance"] - old_native
                    self.conn.execute("UPDATE accounts SET balance=? WHERE id=?",
                                       (reverted, old_acc["id"]))
            old_roundups = self.conn.execute(
                "SELECT * FROM roundups WHERE transaction_id=?", (tx_id,)).fetchall()
            if old_roundups:
                jar = self.get_or_create_roundup_jar()
                reverse_total = sum(r["roundup_amount"] for r in old_roundups)
                self.conn.execute("UPDATE accounts SET balance=? WHERE id=?",
                                   (jar["balance"] - reverse_total, jar["id"]))
                self.conn.execute("DELETE FROM roundups WHERE transaction_id=?", (tx_id,))

            # Recompute cashback against the (possibly new) account/amount.
            new_acc = self.get_account(new_account_id) if new_account_id else None
            cashback = 0.0
            if new_acc and new_amount < 0 and new_acc["subtype"] == "credit_card" \
                    and (new_acc["cashback_rate"] or 0) > 0:
                cashback = round(abs(new_amount) * new_acc["cashback_rate"] / 100.0, 2)
                cap = new_acc["cashback_monthly_cap"] or 0
                if cap > 0:
                    earned_so_far = self.cashback_earned_this_month(new_account_id, new_date)
                    # The OLD row (with its OLD cashback) is still in the table at this
                    # point — exclude its own prior contribution from the baseline if it
                    # would otherwise be double-counted (same account, same month), since
                    # it's about to be replaced by the value we're computing now, not
                    # added on top of it.
                    if tx["account_id"] == new_account_id and tx["date"][:7] == new_date[:7]:
                        earned_so_far -= (tx["cashback"] or 0)
                    cashback = max(0.0, round(min(cashback, cap - earned_so_far), 2))

            self.conn.execute(
                "UPDATE transactions SET date=?, payee=?, category_id=?, amount=?, currency=?, "
                "note=?, account_id=?, cashback=? WHERE id=?",
                (new_date, new_payee, new_category_id, new_amount, new_currency, new_note,
                 new_account_id, cashback, tx_id),
            )

            # Re-apply effects for the NEW values.
            if new_acc:
                self._apply_balance_effect_nocommit(new_acc, new_amount, new_currency)
            if new_amount < 0:
                self._apply_roundup_nocommit(tx_id, new_date, new_amount)

    def delete_transaction(self, tx_id, force_unreconciled=False, delete_transfer_pair=True):
        """Reverses everything add_transaction did: the account balance
        movement and any round-up swept into the jar. Already-redeemed
        cashback is deliberately left alone — that money already became a
        real transaction elsewhere, same as a card issuer wouldn't claw
        back cashback you'd already redeemed just because you later
        returned the purchase.

        Refuses to delete a reconciled transaction unless force_unreconciled
        is True (the UI should prompt before setting that). If this row is
        one leg of a transfer, its paired leg is deleted too (both or
        neither) unless delete_transfer_pair=False, to avoid leaving a
        one-sided phantom transfer."""
        tx = self.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not tx:
            return
        if tx["reconciled"] and not force_unreconciled:
            raise ReconciledTransactionError(
                f"Transaction {tx_id} is reconciled/locked — unreconcile it before deleting.")

        with self.conn:
            self._delete_transaction_row_nocommit(tx)
            if tx["is_transfer"] and tx["transfer_group_id"] and delete_transfer_pair:
                pair = self.conn.execute(
                    "SELECT * FROM transactions WHERE transfer_group_id=? AND id != ?",
                    (tx["transfer_group_id"], tx_id),
                ).fetchall()
                for p in pair:
                    if p["reconciled"] and not force_unreconciled:
                        raise ReconciledTransactionError(
                            f"Paired transfer leg {p['id']} is reconciled/locked.")
                    self._delete_transaction_row_nocommit(p)

    def _delete_transaction_row_nocommit(self, tx):
        if tx["account_id"]:
            acc = self.get_account(tx["account_id"])
            if acc:
                native_amount = self.convert(tx["amount"], tx["currency"], acc["currency"])
                if acc["kind"] == "liability":
                    new_balance = acc["balance"] + native_amount
                else:
                    new_balance = acc["balance"] - native_amount
                self.conn.execute("UPDATE accounts SET balance=? WHERE id=?", (new_balance, acc["id"]))

        roundup_rows = self.conn.execute(
            "SELECT * FROM roundups WHERE transaction_id=?", (tx["id"],)).fetchall()
        if roundup_rows:
            jar = self.get_or_create_roundup_jar()
            reverse_total = sum(r["roundup_amount"] for r in roundup_rows)
            self.conn.execute("UPDATE accounts SET balance=? WHERE id=?",
                               (jar["balance"] - reverse_total, jar["id"]))
            self.conn.execute("DELETE FROM roundups WHERE transaction_id=?", (tx["id"],))

        self.conn.execute("DELETE FROM transaction_splits WHERE transaction_id=?", (tx["id"],))
        self.conn.execute("DELETE FROM transaction_tags WHERE transaction_id=?", (tx["id"],))
        self.conn.execute("DELETE FROM reimbursements WHERE transaction_id=?", (tx["id"],))
        self.conn.execute("DELETE FROM transactions WHERE id=?", (tx["id"],))

    # ---- reimbursements / IOU tracking (e.g. splitting a bill with someone) ----
    def add_reimbursement(self, transaction_id, owed_by, amount, note=""):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO reimbursements(transaction_id, owed_by, amount, status, note) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (transaction_id, owed_by, amount, note),
            )
            return cur.lastrowid

    def settle_reimbursement(self, reimbursement_id, settled_date=None):
        settled_date = settled_date or datetime.date.today().isoformat()
        with self.conn:
            self.conn.execute(
                "UPDATE reimbursements SET status='settled', settled_date=? WHERE id=?",
                (settled_date, reimbursement_id),
            )

    def list_outstanding_reimbursements(self):
        return self.conn.execute(
            "SELECT r.*, t.payee as payee, t.date as transaction_date FROM reimbursements r "
            "JOIN transactions t ON r.transaction_id = t.id "
            "WHERE r.status='pending' ORDER BY t.date DESC"
        ).fetchall()

    def get_reimbursements_for_transaction(self, transaction_id):
        return self.conn.execute(
            "SELECT * FROM reimbursements WHERE transaction_id=? ORDER BY id", (transaction_id,)
        ).fetchall()

    # ---- tags (cross-cutting labels, separate from category) ----
    def set_transaction_tags(self, transaction_id, tag_names):
        """Replaces a transaction's tags with `tag_names` (a list of
        strings). Unknown names are created on the fly and shared across
        transactions — tagging "Canada Trip" on two different transactions
        reuses the same tag row rather than duplicating it."""
        with self.conn:
            self.conn.execute("DELETE FROM transaction_tags WHERE transaction_id=?", (transaction_id,))
            for name in tag_names:
                name = name.strip()
                if not name:
                    continue
                self.conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (name,))
                tag_id = self.conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()["id"]
                self.conn.execute(
                    "INSERT OR IGNORE INTO transaction_tags(transaction_id, tag_id) VALUES (?, ?)",
                    (transaction_id, tag_id),
                )

    def get_transaction_tags(self, transaction_id):
        rows = self.conn.execute(
            "SELECT t.name FROM tags t JOIN transaction_tags tt ON t.id = tt.tag_id "
            "WHERE tt.transaction_id=? ORDER BY t.name", (transaction_id,)
        ).fetchall()
        return [r["name"] for r in rows]

    def list_all_tags(self):
        rows = self.conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    def transactions_by_tag(self, tag_name):
        return self.conn.execute(
            "SELECT tr.*, c.name as category_name, c.kind as category_kind, a.name as account_name "
            "FROM transactions tr "
            "JOIN transaction_tags tt ON tr.id = tt.transaction_id "
            "JOIN tags t ON tt.tag_id = t.id "
            "LEFT JOIN categories c ON tr.category_id = c.id "
            "LEFT JOIN accounts a ON tr.account_id = a.id "
            "WHERE t.name=? ORDER BY tr.date DESC", (tag_name,)
        ).fetchall()

    # ---- category splits (reporting-only: the parent transaction row still
    # carries the full amount for balance/roundup/cashback purposes) ----
    def set_transaction_splits(self, transaction_id, splits):
        """Replaces a transaction's category splits. `splits` is a list of
        {"category_id", "amount", "note"} dicts whose amounts must sum to
        the parent transaction's own amount (same sign convention) — a
        split re-slices where an expense is *attributed* for budgeting, it
        never changes how much money actually moved. Pass an empty list to
        un-split a transaction back to its own single category_id."""
        tx = self.conn.execute("SELECT amount FROM transactions WHERE id=?", (transaction_id,)).fetchone()
        if not tx:
            raise ValueError(f"No transaction with id {transaction_id}.")
        if splits:
            total = sum(s["amount"] for s in splits)
            if abs(total - tx["amount"]) > 0.01:
                raise ValueError(
                    f"Split amounts must sum to the transaction's amount ({tx['amount']}), got {total}.")
        with self.conn:
            self.conn.execute("DELETE FROM transaction_splits WHERE transaction_id=?", (transaction_id,))
            for s in splits:
                self.conn.execute(
                    "INSERT INTO transaction_splits(transaction_id, category_id, amount, note) "
                    "VALUES (?, ?, ?, ?)",
                    (transaction_id, s["category_id"], s["amount"], s.get("note", "")),
                )

    def get_transaction_splits(self, transaction_id):
        return self.conn.execute(
            "SELECT s.*, c.name as category_name, c.kind as category_kind FROM transaction_splits s "
            "LEFT JOIN categories c ON s.category_id = c.id "
            "WHERE s.transaction_id=? ORDER BY s.id", (transaction_id,)
        ).fetchall()

    def list_transactions(self, limit=500):
        return self.conn.execute(
            "SELECT t.*, c.name as category_name, c.kind as category_kind, a.name as account_name "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "LEFT JOIN accounts a ON t.account_id = a.id "
            "ORDER BY date DESC, t.id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def transactions_in_month(self, year, month, include_transfers=False):
        """Transactions for the given reporting month, for financial
        aggregation (monthly totals, savings rate, budgets, anomaly
        detection, etc). The real date range is determined by
        month_bounds() (respects the month_start_day setting; defaults to
        a plain calendar month). Transfers between the user's own accounts
        are excluded by default — moving money from Checking to Savings
        isn't income or an expense, and counting both legs would
        double-count it as both. Pass include_transfers=True for
        ledger-style views that want to see everything that happened."""
        start_date, end_date = month_bounds(self, year, month)
        transfer_clause = "" if include_transfers else "AND t.is_transfer = 0 "
        return self.conn.execute(
            "SELECT t.*, c.name as category_name, c.kind as category_kind, a.name as account_name "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "LEFT JOIN accounts a ON t.account_id = a.id "
            f"WHERE t.date >= ? AND t.date <= ? {transfer_clause}ORDER BY date",
            (start_date, end_date),
        ).fetchall()

    def account_ledger(self, account_id, limit=1000):
        """All transactions (including transfer legs) that touched this
        account, newest first — feeds the account detail view. Includes a
        running `running_balance` column computed oldest-to-newest, then
        reversed, so the ledger reads like a bank statement."""
        rows = self.conn.execute(
            "SELECT t.*, c.name as category_name, c.kind as category_kind, "
            "a.currency as account_currency, a.kind as account_kind, "
            "ta.name as transfer_to_name "
            "FROM transactions t "
            "LEFT JOIN categories c ON t.category_id = c.id "
            "LEFT JOIN accounts a ON t.account_id = a.id "
            "LEFT JOIN accounts ta ON t.transfer_to_account_id = ta.id "
            "WHERE t.account_id = ? ORDER BY t.date ASC, t.id ASC",
            (account_id,),
        ).fetchall()
        running = 0.0
        out = []
        for r in rows:
            native_amount = self.convert(r["amount"], r["currency"], r["account_currency"])
            if r["account_kind"] == "liability":
                running -= native_amount
            else:
                running += native_amount
            d = dict(r)
            d["running_balance"] = round(running, 2)
            out.append(d)
        out.reverse()
        return out[:limit]

    # ---- accounts ----
    def list_accounts(self):
        return self.conn.execute("SELECT * FROM accounts ORDER BY kind, name").fetchall()

    def get_account(self, account_id):
        return self.conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()

    def add_account(self, name, kind, balance, currency="GBP", liquid=False, subtype="cash",
                     credit_limit=0.0, cashback_rate=0.0, due_day=None,
                     expected_return_pct=0.0, monthly_contribution=0.0, cashback_monthly_cap=0.0):
        self.conn.execute(
            "INSERT INTO accounts(name, kind, balance, currency, liquid, subtype, credit_limit, "
            "cashback_rate, contributions, due_day, expected_return_pct, monthly_contribution, "
            "cashback_monthly_cap) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, kind, balance, currency.upper(), int(liquid), subtype, credit_limit,
             cashback_rate, balance if subtype == "investment" else 0.0, due_day,
             expected_return_pct, monthly_contribution, cashback_monthly_cap),
        )
        self.conn.commit()

    def update_account_balance(self, account_id, balance):
        self.conn.execute("UPDATE accounts SET balance=? WHERE id=?", (balance, account_id))
        self.conn.commit()

    def update_account_core(self, account_id, name=None, currency=None, liquid=None):
        """Updates the identity-level fields update_account_details() doesn't
        cover. Deliberately excludes kind/subtype — those drive balance-effect
        sign logic elsewhere (asset vs. liability), so changing them isn't a
        safe blind field update."""
        with self.conn:
            if name is not None:
                self.conn.execute("UPDATE accounts SET name=? WHERE id=?", (name, account_id))
            if currency is not None:
                self.conn.execute("UPDATE accounts SET currency=? WHERE id=?",
                                   (currency.upper(), account_id))
            if liquid is not None:
                self.conn.execute("UPDATE accounts SET liquid=? WHERE id=?",
                                   (int(liquid), account_id))

    def update_account_details(self, account_id, credit_limit=None, cashback_rate=None, due_day=None,
                                expected_return_pct=None, monthly_contribution=None,
                                return_volatility_pct=None, cashback_auto_invest_account_id=None,
                                cashback_monthly_cap=None):
        with self.conn:
            if credit_limit is not None:
                self.conn.execute("UPDATE accounts SET credit_limit=? WHERE id=?", (credit_limit, account_id))
            if cashback_rate is not None:
                self.conn.execute("UPDATE accounts SET cashback_rate=? WHERE id=?", (cashback_rate, account_id))
            if cashback_monthly_cap is not None:
                self.conn.execute("UPDATE accounts SET cashback_monthly_cap=? WHERE id=?",
                                   (cashback_monthly_cap, account_id))
            if due_day is not None:
                self.conn.execute("UPDATE accounts SET due_day=? WHERE id=?", (due_day, account_id))
            if expected_return_pct is not None:
                self.conn.execute("UPDATE accounts SET expected_return_pct=? WHERE id=?",
                                   (expected_return_pct, account_id))
            if monthly_contribution is not None:
                self.conn.execute("UPDATE accounts SET monthly_contribution=? WHERE id=?",
                                   (monthly_contribution, account_id))
            if return_volatility_pct is not None:
                self.conn.execute("UPDATE accounts SET return_volatility_pct=? WHERE id=?",
                                   (return_volatility_pct, account_id))
            if cashback_auto_invest_account_id is not None:
                self.conn.execute("UPDATE accounts SET cashback_auto_invest_account_id=? WHERE id=?",
                                   (cashback_auto_invest_account_id or None, account_id))

    def delete_account(self, account_id):
        self.conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        self.conn.commit()

    def add_investment_contribution(self, account_id, amount, date=None, note=""):
        """Adding new money in: both the balance and the cost-basis
        (contributions) go up, so growth = balance - contributions stays
        accurate. Logged to the append-only investment_contributions table
        (isolated from mark-to-market updates) so contribution history —
        not just the current total — is preserved and auditable."""
        if date is None:
            date = datetime.date.today().isoformat()
        with self.conn:
            self.conn.execute(
                "UPDATE accounts SET balance = balance + ?, contributions = contributions + ? WHERE id=?",
                (amount, amount, account_id))
            self.conn.execute(
                "INSERT INTO investment_contributions(account_id, date, amount, note) VALUES (?, ?, ?, ?)",
                (account_id, date, amount, note),
            )

    def update_investment_value(self, account_id, new_balance, date=None):
        """Mark-to-market update: only the balance changes, so any difference
        from contributions shows up as investment growth (or loss). Logged
        to investment_valuations so a value-over-time chart is possible
        independent of when contributions were made."""
        if date is None:
            date = datetime.date.today().isoformat()
        with self.conn:
            self.conn.execute("UPDATE accounts SET balance=? WHERE id=?", (new_balance, account_id))
            self.conn.execute(
                "INSERT INTO investment_valuations(account_id, date, value) VALUES (?, ?, ?)",
                (account_id, date, new_balance),
            )

    def get_investment_contributions(self, account_id):
        return self.conn.execute(
            "SELECT * FROM investment_contributions WHERE account_id=? ORDER BY date", (account_id,)
        ).fetchall()

    def get_investment_valuations(self, account_id):
        return self.conn.execute(
            "SELECT * FROM investment_valuations WHERE account_id=? ORDER BY date", (account_id,)
        ).fetchall()

    # ---- capital gains (UK Section 104 average-cost pooling) ----
    #
    # IMPORTANT LIMITATION: this implements plain Section 104 pooling only —
    # every buy/sell of a security within one account is pooled into a
    # single running average cost. It does NOT implement HMRC's same-day
    # rule or the 30-day "bed and breakfast" rule, both of which must be
    # applied BEFORE pooling for a fully correct UK CGT computation (they
    # match a disposal against acquisitions on the same day or within the
    # following 30 days at their own cost, ahead of the general pool).
    # Numbers here are a reasonable estimate for someone who isn't
    # rapidly trading the same security, not a substitute for proper tax
    # software or an accountant — verify before relying on this for a
    # real Self Assessment return.

    def add_security_transaction(self, account_id, security, date, action, quantity, price,
                                  fees=0.0, currency=None, note=""):
        if action not in ("buy", "sell"):
            raise ValueError(f"action must be 'buy' or 'sell', got {action!r}")
        currency = (currency or self.get_setting("reporting_currency", "GBP")).upper()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO security_lots(account_id, security, date, action, quantity, price, fees, "
                "currency, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, security, date, action, quantity, price, fees, currency, note),
            )
            lot_id = cur.lastrowid
            self._recompute_realized_gains_nocommit(account_id, security)
        return lot_id

    def update_security_transaction(self, lot_id, date=None, action=None, quantity=None, price=None,
                                     fees=None, currency=None, note=None):
        row = self.conn.execute("SELECT * FROM security_lots WHERE id=?", (lot_id,)).fetchone()
        if not row:
            raise ValueError(f"No security transaction with id {lot_id}.")
        if action is not None and action not in ("buy", "sell"):
            raise ValueError(f"action must be 'buy' or 'sell', got {action!r}")
        new_currency = (row["currency"] if currency is None else currency).upper()
        with self.conn:
            self.conn.execute(
                "UPDATE security_lots SET date=?, action=?, quantity=?, price=?, fees=?, currency=?, "
                "note=? WHERE id=?",
                (row["date"] if date is None else date,
                 row["action"] if action is None else action,
                 row["quantity"] if quantity is None else quantity,
                 row["price"] if price is None else price,
                 row["fees"] if fees is None else fees,
                 new_currency,
                 row["note"] if note is None else note,
                 lot_id),
            )
            self._recompute_realized_gains_nocommit(row["account_id"], row["security"])

    def delete_security_transaction(self, lot_id):
        row = self.conn.execute("SELECT * FROM security_lots WHERE id=?", (lot_id,)).fetchone()
        if not row:
            return
        with self.conn:
            self.conn.execute("DELETE FROM security_lots WHERE id=?", (lot_id,))
            self._recompute_realized_gains_nocommit(row["account_id"], row["security"])

    def _recompute_realized_gains_nocommit(self, account_id, security):
        """Replays every buy/sell for this (account, security) in date order
        and rewrites each sell's stored realized_gain from scratch. Cheap
        and always-correct for the data volumes a personal portfolio has —
        simpler and safer than trying to patch only 'affected' rows when a
        backdated transaction is inserted out of order."""
        rows = self.conn.execute(
            "SELECT id, action, quantity, price, fees FROM security_lots "
            "WHERE account_id=? AND security=? ORDER BY date, id",
            (account_id, security),
        ).fetchall()
        pool_qty, pool_cost = 0.0, 0.0
        for row in rows:
            if row["action"] == "buy":
                pool_qty += row["quantity"]
                pool_cost += row["quantity"] * row["price"] + row["fees"]
            else:
                avg_cost = pool_cost / pool_qty if pool_qty else 0.0
                cost_of_sold = avg_cost * row["quantity"]
                proceeds = row["quantity"] * row["price"] - row["fees"]
                self.conn.execute("UPDATE security_lots SET realized_gain=? WHERE id=?",
                                   (proceeds - cost_of_sold, row["id"]))
                pool_qty -= row["quantity"]
                pool_cost -= cost_of_sold

    def security_pool_state(self, account_id, security):
        """Current holding for this security in this account: (quantity,
        total pool cost, average cost per unit)."""
        rows = self.conn.execute(
            "SELECT action, quantity, price, fees FROM security_lots "
            "WHERE account_id=? AND security=? ORDER BY date, id",
            (account_id, security),
        ).fetchall()
        pool_qty, pool_cost = 0.0, 0.0
        for row in rows:
            if row["action"] == "buy":
                pool_qty += row["quantity"]
                pool_cost += row["quantity"] * row["price"] + row["fees"]
            else:
                avg_cost = pool_cost / pool_qty if pool_qty else 0.0
                cost_of_sold = avg_cost * row["quantity"]
                pool_qty -= row["quantity"]
                pool_cost -= cost_of_sold
        avg_cost = pool_cost / pool_qty if pool_qty else 0.0
        return pool_qty, pool_cost, avg_cost

    def list_securities(self, account_id=None):
        q = "SELECT DISTINCT account_id, security FROM security_lots"
        params = ()
        if account_id:
            q += " WHERE account_id=?"
            params = (account_id,)
        return self.conn.execute(q + " ORDER BY security", params).fetchall()

    def realized_gains_for_uk_tax_year(self, start_year):
        """UK tax year start_year/start_year+1 runs 6 Apr start_year to
        5 Apr start_year+1. Returns every sell in that window plus the
        total gain (losses are negative, so this is already net)."""
        start = f"{start_year:04d}-04-06"
        end = f"{start_year + 1:04d}-04-05"
        sells = self.conn.execute(
            "SELECT sl.*, a.name as account_name FROM security_lots sl "
            "JOIN accounts a ON sl.account_id = a.id "
            "WHERE sl.action='sell' AND sl.date >= ? AND sl.date <= ? ORDER BY sl.date",
            (start, end),
        ).fetchall()
        total_gain = sum(s["realized_gain"] or 0.0 for s in sells)
        return {"tax_year": f"{start_year}/{str(start_year + 1)[2:]}", "start": start, "end": end,
                "sells": sells, "total_gain": total_gain}

    def get_or_create_roundup_jar(self):
        row = self.conn.execute("SELECT * FROM accounts WHERE subtype='roundup_pot' LIMIT 1").fetchone()
        if row:
            return row
        cur = self.get_setting("reporting_currency", "GBP")
        self.conn.execute(
            "INSERT INTO accounts(name, kind, balance, currency, liquid, subtype, credit_limit, "
            "cashback_rate, contributions) VALUES (?, 'asset', 0, ?, 1, 'roundup_pot', 0, 0, 0)",
            ("Round-Up Jar", cur),
        )
        self.conn.commit()
        return self.conn.execute("SELECT * FROM accounts WHERE subtype='roundup_pot' LIMIT 1").fetchone()

    def transfer_between_accounts(self, from_account_id, to_account_id, amount, date=None, note="",
                                   to_amount=None):
        """Moves money between two of the user's own accounts — e.g. sweeping
        the round-up jar into savings, paying off a credit card from cash,
        or moving money into an investment account. Records TWO linked
        transaction rows (one per account, tied by transfer_group_id) rather
        than silently patching balances, so both accounts get a proper
        ledger entry and the transfer shows up in reconciliation/history.

        Cross-currency transfers convert `amount` (given in the source
        account's currency) into the destination account's currency using
        today's fx_rates, and permanently record that conversion as
        `historical_rate` on the destination leg — so if fx_rates change
        later, past transfers still replay at the rate that actually
        applied when the money moved, exactly like a real bank statement.

        Pass `to_amount` when you know the actual amount that arrived (e.g.
        logging a real currency exchange) — it's used directly instead of
        `fx_rates`, and `historical_rate` is computed from the real amounts
        on both legs rather than guessed from a possibly-stale stored rate.

        Both accounts move in the same all-or-nothing transaction: if either
        account can't be found or the amount is invalid, nothing is written.
        """
        frm = self.get_account(from_account_id)
        to = self.get_account(to_account_id)
        if not frm or not to or amount <= 0 or from_account_id == to_account_id:
            return None
        if date is None:
            date = datetime.date.today().isoformat()

        # amount is in the source account's currency; convert to destination,
        # unless the caller already knows the real destination amount.
        if to_amount is not None:
            dest_amount = to_amount
        else:
            dest_amount = self.convert(amount, frm["currency"], to["currency"])
        if frm["currency"] == to["currency"]:
            historical_rate = 1.0
        else:
            historical_rate = dest_amount / amount if amount else 1.0

        group_id = uuid.uuid4().hex
        with self.conn:
            # Source leg: money leaves (liability accounts paid down count
            # as a negative "amount owed" movement handled by balance-effect).
            src_cur = self.conn.execute(
                "INSERT INTO transactions(date, payee, category_id, amount, currency, note, "
                "account_id, is_transfer, transfer_to_account_id, transfer_group_id, historical_rate) "
                "VALUES (?, ?, NULL, ?, ?, ?, ?, 1, ?, ?, ?)",
                (date, f"Transfer to {to['name']}", -abs(amount), frm["currency"],
                 note or f"Transfer to {to['name']}", from_account_id, to_account_id,
                 group_id, historical_rate),
            )
            self._apply_balance_effect_nocommit(frm, -abs(amount), frm["currency"])

            # Destination leg: money arrives, already converted.
            self.conn.execute(
                "INSERT INTO transactions(date, payee, category_id, amount, currency, note, "
                "account_id, is_transfer, transfer_to_account_id, transfer_group_id, historical_rate) "
                "VALUES (?, ?, NULL, ?, ?, ?, ?, 1, ?, ?, ?)",
                (date, f"Transfer from {frm['name']}", abs(dest_amount), to["currency"],
                 note or f"Transfer from {frm['name']}", to_account_id, from_account_id,
                 group_id, historical_rate),
            )
            to_fresh = self.conn.execute("SELECT * FROM accounts WHERE id=?", (to_account_id,)).fetchone()
            self._apply_balance_effect_nocommit(to_fresh, abs(dest_amount), to["currency"])

        return group_id

    def list_transfers(self, limit=500):
        """One row per transfer (both legs joined), newest first — for a
        dedicated Transfers view distinct from the raw transaction list."""
        rows = self.conn.execute(
            "SELECT t.id as leg_id, t.transfer_group_id, t.date, "
            "src.name as from_account, dst.name as to_account, "
            "ABS(t.amount) as from_amount, t.currency as from_currency, "
            "t2.amount as to_amount, t2.currency as to_currency, t.historical_rate "
            "FROM transactions t "
            "JOIN transactions t2 ON t2.transfer_group_id = t.transfer_group_id AND t2.id != t.id "
            "LEFT JOIN accounts src ON t.account_id = src.id "
            "LEFT JOIN accounts dst ON t2.account_id = dst.id "
            "WHERE t.is_transfer = 1 AND t.amount < 0 "
            "ORDER BY t.date DESC, t.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return rows

    # ---- debts ----
    def list_debts(self):
        return self.conn.execute("SELECT * FROM debts ORDER BY balance").fetchall()

    def add_debt(self, name, balance, apr, min_payment, currency="GBP", custom_payment=0.0):
        if min_payment < 0 or custom_payment < 0:
            raise ValueError("Payments cannot be negative.")
        if custom_payment and custom_payment < min_payment:
            raise ValueError(
                f"Planned payment ({custom_payment}) can't be below the minimum payment ({min_payment}).")
        self.conn.execute(
            "INSERT INTO debts(name, balance, apr, min_payment, custom_payment, currency) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, balance, apr, min_payment, custom_payment, currency.upper()),
        )
        self.conn.commit()

    def delete_debt(self, debt_id):
        self.conn.execute("DELETE FROM debts WHERE id=?", (debt_id,))
        self.conn.commit()

    def update_debt_balance(self, debt_id, balance):
        self.conn.execute("UPDATE debts SET balance=? WHERE id=?", (balance, debt_id))
        self.conn.commit()

    def update_debt_payment_plan(self, debt_id, min_payment=None, custom_payment=None):
        """Updates a debt's payment constraints. Enforces min_payment >= 0
        and custom_payment (if set) >= min_payment at the data layer, so the
        payoff planner can never simulate a plan that underpays the
        contractual minimum — the UI validation is a courtesy, this is the
        actual guarantee."""
        row = self.conn.execute("SELECT * FROM debts WHERE id=?", (debt_id,)).fetchone()
        if not row:
            return
        new_min = row["min_payment"] if min_payment is None else min_payment
        new_custom = row["custom_payment"] if custom_payment is None else custom_payment
        if new_min < 0 or new_custom < 0:
            raise ValueError("Payments cannot be negative.")
        if new_custom and new_custom < new_min:
            raise ValueError(
                f"Planned payment ({new_custom}) can't be below the minimum payment ({new_min}).")
        with self.conn:
            self.conn.execute("UPDATE debts SET min_payment=?, custom_payment=? WHERE id=?",
                               (new_min, new_custom, debt_id))

    # ---- recurring transactions (bills / paychecks) ----
    def add_recurring(self, name, payee, category_id, amount, currency, frequency, next_date,
                       account_id=None, custom_interval_months=None):
        self.conn.execute(
            "INSERT INTO recurring(name, payee, category_id, amount, currency, frequency, next_date, "
            "active, account_id, custom_interval_months) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (name, payee, category_id, amount, currency.upper(), frequency, next_date, account_id,
             custom_interval_months),
        )
        self.conn.commit()

    def list_recurring(self, active_only=False):
        q = ("SELECT r.*, c.name as category_name, a.name as account_name FROM recurring r "
             "LEFT JOIN categories c ON r.category_id = c.id "
             "LEFT JOIN accounts a ON r.account_id = a.id")
        if active_only:
            q += " WHERE r.active = 1"
        q += " ORDER BY next_date"
        return self.conn.execute(q).fetchall()

    def set_recurring_active(self, recurring_id, active):
        self.conn.execute("UPDATE recurring SET active=? WHERE id=?", (int(active), recurring_id))
        self.conn.commit()

    def delete_recurring(self, recurring_id):
        self.conn.execute("DELETE FROM recurring WHERE id=?", (recurring_id,))
        self.conn.commit()

    def add_ignored_subscription(self, payee, date=None):
        date = date or datetime.date.today().isoformat()
        existing = self.conn.execute(
            "SELECT id FROM ignored_subscriptions WHERE LOWER(payee)=LOWER(?)", (payee,)
        ).fetchone()
        if existing:
            return
        self.conn.execute(
            "INSERT INTO ignored_subscriptions(payee, dismissed_date) VALUES (?, ?)",
            (payee, date),
        )
        self.conn.commit()

    def remove_ignored_subscription(self, payee):
        self.conn.execute(
            "DELETE FROM ignored_subscriptions WHERE LOWER(payee)=LOWER(?)", (payee,)
        )
        self.conn.commit()

    def list_ignored_subscriptions(self):
        return self.conn.execute(
            "SELECT * FROM ignored_subscriptions ORDER BY dismissed_date DESC"
        ).fetchall()

    def _advance_date(self, date_str, frequency, custom_interval_months=None):
        d = datetime.date.fromisoformat(date_str)
        if frequency == "weekly":
            d += datetime.timedelta(days=7)
        elif frequency == "yearly":
            try:
                d = d.replace(year=d.year + 1)
            except ValueError:  # Feb 29 -> Feb 28
                d = d.replace(year=d.year + 1, day=28)
        else:  # monthly, or custom (every N months — e.g. rent paid 3x/year = every 4 months)
            months_ahead = custom_interval_months if frequency == "custom" and custom_interval_months else 1
            total = d.month - 1 + months_ahead
            y = d.year + total // 12
            m = total % 12 + 1
            last = _last_day_of_month(y, m)
            d = datetime.date(y, m, min(d.day, last.day))
        return d.isoformat()

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
                    acc = self.get_account(r["account_id"]) if r["account_id"] else None
                    cur = self.conn.execute(
                        "INSERT INTO transactions(date, payee, category_id, amount, currency, note, account_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (r["next_date"], r["payee"] or r["name"], r["category_id"], r["amount"],
                         r["currency"], f"Auto: {r['name']}", r["account_id"]),
                    )
                    tx_id = cur.lastrowid
                    if acc:
                        self._apply_balance_effect_nocommit(acc, r["amount"], r["currency"])
                    if r["amount"] < 0:
                        self._apply_roundup_nocommit(tx_id, r["next_date"], r["amount"])
                    posted.append((r["name"], r["next_date"], r["amount"]))
                    new_next = self._advance_date(r["next_date"], r["frequency"],
                                                   custom_interval_months=r["custom_interval_months"])
                    self.conn.execute("UPDATE recurring SET next_date=? WHERE id=?", (new_next, r["id"]))
                    r = dict(r)
                    r["next_date"] = new_next
                    guard += 1
        return posted

    # ---- net worth snapshots ----
    def record_networth_snapshot(self, date, net_worth):
        self.conn.execute(
            "INSERT INTO networth_snapshots(date, net_worth) VALUES (?, ?)", (date, net_worth)
        )
        self.conn.commit()

    def list_networth_snapshots(self):
        return self.conn.execute("SELECT * FROM networth_snapshots ORDER BY date").fetchall()


# --------------------------------------------------------------------------
# Financial math (Part II, III, VIII, X of the research)
# --------------------------------------------------------------------------

def net_worth(db: Database):
    total = 0.0
    for a in db.list_accounts():
        val = db.to_reporting(a["balance"], a["currency"])
        total += val if a["kind"] == "asset" else -val
    return total


def liquid_assets(db: Database):
    total = 0.0
    for a in db.list_accounts():
        if a["kind"] == "asset" and a["liquid"]:
            total += db.to_reporting(a["balance"], a["currency"])
    return total


def net_worth_breakdown(db: Database):
    """Net worth split by account subtype, signed so assets are positive and
    liabilities negative — feeds the 'net worth by type' donut/bar chart."""
    totals = {"cash": 0.0, "credit_card": 0.0, "investment": 0.0, "loan": 0.0, "other": 0.0}
    for a in db.list_accounts():
        val = db.to_reporting(a["balance"], a["currency"])
        signed = val if a["kind"] == "asset" else -val
        subtype = a["subtype"] or ("cash" if a["kind"] == "asset" else "loan")
        if subtype == "roundup_pot":
            subtype = "cash"
        totals[subtype] = totals.get(subtype, 0.0) + signed
    return totals


def credit_utilization(db: Database):
    """Per-card utilization (balance owed / credit limit) for every credit
    card account that has a limit set. Returns list of dicts, worst first."""
    out = []
    for a in db.list_accounts():
        if a["subtype"] == "credit_card" and (a["credit_limit"] or 0) > 0:
            bal = db.to_reporting(a["balance"], a["currency"])
            limit = db.to_reporting(a["credit_limit"], a["currency"])
            out.append({"account": a, "balance": bal, "limit": limit,
                        "utilization": bal / limit if limit > 0 else 0.0})
    out.sort(key=lambda x: -x["utilization"])
    return out


def investment_summary(db: Database):
    """Contributions vs. current value vs. growth for every investment
    account — feeds the Net Worth tab's investment cards."""
    out = []
    for a in db.list_accounts():
        if a["subtype"] == "investment":
            balance = db.to_reporting(a["balance"], a["currency"])
            contributions = db.to_reporting(a["contributions"] or 0.0, a["currency"])
            growth = balance - contributions
            growth_pct = (growth / contributions) if contributions > 0 else 0.0
            out.append({"account": a, "balance": balance, "contributions": contributions,
                        "growth": growth, "growth_pct": growth_pct})
    return out


def upcoming_card_payments(db: Database, within_days=14, today: Optional[datetime.date] = None):
    """Credit cards with a due_day set, whose next payment date falls within
    the window — feeds the Dashboard nudge and the Net Worth tab's due-date
    list. Only considers cards carrying a balance (nothing to pay otherwise)."""
    if today is None:
        today = datetime.date.today()
    out = []
    for a in db.list_accounts():
        if a["subtype"] != "credit_card" or not a["due_day"] or a["balance"] <= 0:
            continue
        day = min(max(int(a["due_day"]), 1), 28)
        candidate = today.replace(day=day)
        if candidate < today:
            m = today.month + 1
            y = today.year + (1 if m > 12 else 0)
            m = 1 if m > 12 else m
            candidate = datetime.date(y, m, day)
        if (candidate - today).days <= within_days:
            out.append({"account": a, "due_date": candidate.isoformat(),
                        "balance": db.to_reporting(a["balance"], a["currency"])})
    out.sort(key=lambda x: x["due_date"])
    return out


def investment_projection(db: Database, years=10):
    """Simple compounding projection for the investment portfolio: for each
    investment account, grows the current balance monthly at its own
    expected_return_pct (annual, converted to a monthly rate) and adds its
    monthly_contribution each month. Purely illustrative — assumes constant
    returns and contributions, which real markets never actually deliver.
    Returns (labels, values) for a 'total portfolio value over time' chart."""
    labels, mid, _, _ = investment_projection_with_bands(db, years=years)
    return labels, mid


def investment_projection_with_bands(db: Database, years=10):
    """Same illustrative compounding projection as investment_projection,
    but also returns a low/high band derived from each account's
    return_volatility_pct (annual stdev of returns). This is still plain
    arithmetic, not a Monte Carlo simulation: the band is the deterministic
    envelope you'd get compounding at (expected - 1 stdev) and
    (expected + 1 stdev) every year, which is a reasonable illustrative
    'how wrong could this be' range without pretending to model real
    market path-dependence. Returns (labels, mid_values, low_values, high_values)."""
    accounts = [a for a in db.list_accounts() if a["subtype"] == "investment"]
    months = years * 12

    def run(rate_offset_pct):
        balances = [db.to_reporting(a["balance"], a["currency"]) for a in accounts]
        rates = [max((a["expected_return_pct"] or 0.0) + rate_offset_pct, -99.0) / 100.0 / 12.0
                 for a in accounts]
        contribs = [db.to_reporting(a["monthly_contribution"] or 0.0, a["currency"]) for a in accounts]
        values = [sum(balances)]
        for _ in range(months):
            balances = [b * (1 + r) + c for b, r, c in zip(balances, rates, contribs)]
            values.append(sum(balances))
        return values[::12]

    if not accounts:
        return [], [], [], []

    # portfolio-level volatility offset: average of each account's own
    # volatility assumption (0 if unset), applied uniformly for simplicity.
    vols = [a["return_volatility_pct"] or 0.0 for a in accounts]
    avg_vol = mean(vols) if vols else 0.0

    mid_values = run(0.0)
    low_values = run(-avg_vol)
    high_values = run(avg_vol)

    labels = []
    start_year = datetime.date.today().year
    for i in range(0, months + 1, 12):
        labels.append(str(start_year + i // 12))
    n = len(mid_values)
    return labels[:n], mid_values, low_values[:n], high_values[:n]


def monthly_essential_expenses(db: Database, year, month):
    """Sum of 'need' category spending for a given month, in reporting currency."""
    total = 0.0
    for t in db.transactions_in_month(year, month):
        if t["amount"] < 0 and t["category_kind"] == "need":
            total += -db.to_reporting(t["amount"], t["currency"])
    return total


def monthly_totals(db: Database, year, month):
    """income, expenses, savings-category spend — all in reporting currency."""
    income = expenses = savings = 0.0
    for t in db.transactions_in_month(year, month):
        val = db.to_reporting(t["amount"], t["currency"])
        if val > 0:
            income += val
        else:
            expenses += -val
            if t["category_kind"] == "saving":
                savings += -val
    return income, expenses, savings


def savings_rate(db: Database, year, month):
    income, expenses, savings = monthly_totals(db, year, month)
    if income <= 0:
        return 0.0
    # Savings rate = amount saved / income. "Saved" = income - expenses if positive,
    # falling back to explicit saving-category spend if that's how the user tracks it.
    implied_saved = max(income - expenses, savings)
    return implied_saved / income


def emergency_fund_ratio(db: Database, year, month):
    essentials = monthly_essential_expenses(db, year, month)
    if essentials <= 0:
        return None
    return liquid_assets(db) / essentials


def debt_to_income(db: Database, year, month):
    income, _, _ = monthly_totals(db, year, month)
    if income <= 0:
        return None
    monthly_debt_payment = sum(d["min_payment"] for d in db.list_debts())
    return monthly_debt_payment / income


def housing_ratio(db: Database, year, month):
    income, _, _ = monthly_totals(db, year, month)
    if income <= 0:
        return None
    housing_spent = 0.0
    for t in db.transactions_in_month(year, month):
        if t["category_name"] == "Housing" and t["amount"] < 0:
            housing_spent += -db.to_reporting(t["amount"], t["currency"])
    return housing_spent / income


def safe_to_spend(db: Database, year, month, today: Optional[datetime.date] = None):
    """
    Money-left / days-left "runway" number — Part XII, feature #1.
    Safe-to-spend = (income so far - essential/committed spend so far - remaining category budgets already earmarked) / days left in month
    Simplified: available discretionary balance / days remaining in the
    reporting period (respects month_start_day via month_bounds() — "today"
    may fall in a different literal calendar month than the period's label
    while still being chronologically inside it).
    """
    if today is None:
        today = datetime.date.today()
    income, expenses, _ = monthly_totals(db, year, month)
    # Remaining budget across "want" categories not yet spent, plus leftover income
    remaining_balance = income - expenses
    start_str, end_str = month_bounds(db, year, month)
    start_date = datetime.date.fromisoformat(start_str)
    end_date = datetime.date.fromisoformat(end_str)
    days_left = max((end_date - today).days + 1, 1) if start_date <= today <= end_date else 1
    return remaining_balance / days_left, remaining_balance, days_left


def _last_day_of_month(year, month):
    if month == 12:
        return datetime.date(year, 12, 31)
    return datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)


def _month_start_day(db):
    """The configured month_start_day setting, clamped to 1..28 (same
    convention this codebase already uses for credit card due_day) —
    chosen specifically so no day-of-month edge case can ever arise, since
    every month has at least 28 days. Shared by month_bounds and
    custom_month_for_date so they can never drift into disagreeing about
    what the current start day actually is — they need to stay exact
    inverses of each other."""
    return min(max(db.get_setting_int("month_start_day", 1), 1), 28)


def _clamped_month_start(db, year, month):
    start_day = _month_start_day(db)
    last_day = _last_day_of_month(year, month).day
    return datetime.date(year, month, min(start_day, last_day))


def month_bounds(db: Database, year, month):
    """The real calendar date range a reporting "month" (year, month)
    spans, given the month_start_day setting (default 1 = plain calendar
    month, byte-for-byte identical to date(year, month, 1)..last day of
    that month). A month is labeled by the calendar month it starts in:
    with month_start_day=25, (year, 8) spans 25 Aug-24 Sep."""
    start_date = _clamped_month_start(db, year, month)
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    next_start = _clamped_month_start(db, next_year, next_month)
    end_date = next_start - datetime.timedelta(days=1)
    return start_date.isoformat(), end_date.isoformat()


def custom_month_for_date(db: Database, a_date):
    """Which reporting-month bucket (year, month) a real date falls into,
    given month_start_day. Used to resolve "today" into the right bucket
    when the app opens or "Today" is clicked."""
    start_day = _month_start_day(db)
    if a_date.day >= start_day:
        return a_date.year, a_date.month
    month = a_date.month - 1
    year = a_date.year
    if month < 1:
        month = 12
        year -= 1
    return year, month


def monthly_history(db: Database, year, month, n_months=6):
    """Last n_months of (label, income, expenses), ending at year/month, oldest first.
    Feeds the dashboard's income-vs-expenses trend chart. Labels include the
    year ("Jan '25") once the range exceeds 12 months, since a plain "%b"
    label would otherwise repeat identically across different years."""
    label_fmt = "%b '%y" if n_months > 12 else "%b"
    out = []
    y, m = year, month
    for _ in range(n_months):
        income, expenses, _ = monthly_totals(db, y, m)
        out.append((datetime.date(y, m, 1).strftime(label_fmt), income, expenses))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(out))


def detect_recurring_candidates(db: Database, min_occurrences=3, interval_tolerance_days=6):
    """Scans real transaction history (not the manually-curated `recurring`
    table) for payees charging at regularly-spaced intervals — a
    subscription you never explicitly added to Recurring. Flags a price
    change between the two most recent occurrences. Skips payees that
    already have an active recurring entry (case-insensitive match), so
    it only surfaces genuinely undetected subscriptions."""
    known_payees = {r["payee"].strip().lower() for r in db.list_recurring(active_only=True) if r["payee"]}
    ignored_payees = {r["payee"].strip().lower() for r in db.list_ignored_subscriptions()}

    by_payee = {}
    for t in db.conn.execute(
        "SELECT * FROM transactions WHERE amount < 0 AND is_transfer = 0 "
        "AND payee IS NOT NULL AND payee != '' ORDER BY date"
    ):
        by_payee.setdefault(t["payee"].strip().lower(), []).append(t)

    candidates = []
    for payee_key, txs in by_payee.items():
        if payee_key in known_payees or payee_key in ignored_payees or len(txs) < min_occurrences:
            continue
        dates = [datetime.date.fromisoformat(t["date"]) for t in txs]
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_interval = mean(intervals)
        if avg_interval < 1 or any(abs(iv - avg_interval) > interval_tolerance_days for iv in intervals):
            continue
        last, prev = txs[-1], txs[-2]
        candidates.append({
            "payee": last["payee"],
            "occurrences": len(txs),
            "avg_interval_days": avg_interval,
            "last_amount": last["amount"],
            "last_currency": last["currency"],
            "last_date": last["date"],
            "price_changed": abs(last["amount"] - prev["amount"]) > 0.01,
            "previous_amount": prev["amount"],
        })
    candidates.sort(key=lambda c: c["last_date"], reverse=True)
    return candidates


def top_payees(db: Database, year, month, limit=10):
    """Ranks this month's expense payees by total spend (reporting currency),
    highest first — "where does the money actually go" beyond category
    totals. Income (positive amounts) is excluded."""
    totals = {}
    for t in db.transactions_in_month(year, month):
        if t["amount"] >= 0:
            continue
        payee = t["payee"] or "(no payee)"
        entry = totals.setdefault(payee, {"payee": payee, "total": 0.0, "count": 0})
        entry["total"] += -db.to_reporting(t["amount"], t["currency"])
        entry["count"] += 1
    ranked = sorted(totals.values(), key=lambda r: -r["total"])
    return ranked[:limit]


def daily_spend_totals(db: Database, year, month):
    """Expense total per day-of-month (1..days_in_month, every day present,
    0.0 where nothing was spent) — feeds a calendar-style spending heatmap
    (charts.draw_calendar_heatmap) that renders a literal weekday-aligned
    grid for one specific real month. Deliberately always a plain calendar
    month, independent of the month_start_day setting — a custom reporting
    period spanning two calendar months has no sensible weekday-grid
    rendering, so this queries transactions directly rather than through
    Database.transactions_in_month (which IS custom-month-aware). Income
    is excluded, same convention as top_payees/category_budget_status."""
    days_in_month = calendar.monthrange(year, month)[1]
    totals = {day: 0.0 for day in range(1, days_in_month + 1)}
    prefix = f"{year:04d}-{month:02d}"
    rows = db.conn.execute(
        "SELECT date, amount, currency FROM transactions "
        "WHERE date LIKE ? AND is_transfer = 0", (prefix + "%",),
    ).fetchall()
    for t in rows:
        if t["amount"] >= 0:
            continue
        day = int(t["date"][8:10])
        totals[day] += -db.to_reporting(t["amount"], t["currency"])
    return totals


def spend_by_kind(db: Database, year, month):
    """This month's expense total per envelope kind (need/want/saving), in
    reporting currency — feeds the dashboard's allocation donut chart."""
    totals = {"need": 0.0, "want": 0.0, "saving": 0.0}
    for _cat_id, kind, amount in _category_spend_entries(db, year, month):
        if kind in totals:
            totals[kind] += amount
    return totals


def income_by_category(db: Database, year, month):
    """This month's income total per income-kind category, in reporting
    currency — feeds the Budgets tab's Income card. Labeling only, no
    budget/target framing: 'over budget' doesn't apply to income."""
    totals = {}
    for t in db.transactions_in_month(year, month):
        if t["amount"] <= 0 or t["category_kind"] != "income":
            continue
        entry = totals.setdefault(t["category_id"], {
            "category_id": t["category_id"], "category_name": t["category_name"], "total": 0.0,
        })
        entry["total"] += db.to_reporting(t["amount"], t["currency"])
    return sorted(totals.values(), key=lambda r: -r["total"])


def upcoming_bills(db: Database, within_days=14, today: Optional[datetime.date] = None):
    """Active recurring items due within the window — for the dashboard nudge
    and the Recurring tab's 'coming up' list."""
    if today is None:
        today = datetime.date.today()
    horizon = (today + datetime.timedelta(days=within_days)).isoformat()
    out = []
    for r in db.list_recurring(active_only=True):
        if today.isoformat() <= r["next_date"] <= horizon:
            out.append(r)
    return out


def export_transactions_csv(db: Database, path, currency_converter=None):
    """Writes all transactions to a CSV file. currency_converter, if given, is
    db.to_reporting — used to add a reporting-currency column."""
    import csv
    rows = db.list_transactions(limit=100000)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["date", "payee", "category", "amount", "currency", "note"]
        if currency_converter:
            header.append("amount_reporting_ccy")
        writer.writerow(header)
        for t in rows:
            row = [t["date"], t["payee"] or "", t["category_name"] or "", t["amount"],
                   t["currency"], t["note"] or ""]
            if currency_converter:
                row.append(round(currency_converter(t["amount"], t["currency"]), 2))
            writer.writerow(row)
    return len(rows)


def fi_number(db: Database, annual_expenses):
    """Financial Independence number = 25x annual expenses (Part VIII, 4% rule)."""
    return annual_expenses * 25


def category_anomalies(db: Database, months_history=6, z_threshold=2.0):
    """
    Simple statistical anomaly flags (Part X): a transaction well outside its
    category's own rolling average — plain arithmetic, no trained model.
    Returns list of (transaction row, category avg, category stdev).
    """
    all_tx = db.conn.execute(
        "SELECT t.*, c.name as category_name FROM transactions t "
        "LEFT JOIN categories c ON t.category_id = c.id WHERE t.amount < 0 AND t.is_transfer = 0"
    ).fetchall()

    by_cat = {}
    for t in all_tx:
        by_cat.setdefault(t["category_name"], []).append(t)

    flags = []
    for cat, txs in by_cat.items():
        amounts = [-db.to_reporting(t["amount"], t["currency"]) for t in txs]
        if len(amounts) < 4:
            continue
        avg = mean(amounts)
        sd = pstdev(amounts) or 1e-9
        for t, amt in zip(txs, amounts):
            z = (amt - avg) / sd
            if z >= z_threshold:
                flags.append({"transaction": t, "amount": amt, "avg": avg, "z": z})
    flags.sort(key=lambda f: -f["z"])
    return flags


def lifestyle_inflation_flags(db: Database, year, month):
    """
    Month-over-month category spend growth vs. income growth (Part XII, feature #7).
    Compares given month to the prior month.
    """
    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    income_now, _, _ = monthly_totals(db, year, month)
    income_prev, _, _ = monthly_totals(db, prev_year, prev_month)
    income_growth = (income_now - income_prev) / income_prev if income_prev > 0 else 0.0

    def cat_spend(y, m):
        spend = {}
        for t in db.transactions_in_month(y, m):
            if t["amount"] < 0:
                spend[t["category_name"]] = spend.get(t["category_name"], 0.0) - db.to_reporting(t["amount"], t["currency"])
        return spend

    now_spend = cat_spend(year, month)
    prev_spend = cat_spend(prev_year, prev_month)

    flags = []
    for cat, now_amt in now_spend.items():
        prev_amt = prev_spend.get(cat, 0.0)
        if prev_amt <= 0:
            continue
        growth = (now_amt - prev_amt) / prev_amt
        if growth > income_growth + 0.10:  # spend outgrew income by >10pp
            flags.append({"category": cat, "growth": growth, "income_growth": income_growth,
                          "prev": prev_amt, "now": now_amt})
    flags.sort(key=lambda f: -f["growth"])
    return flags


def idle_cash_nudge(db: Database, year, month, buffer_months=3):
    """
    If liquid assets exceed buffer_months of essential expenses AND near-term
    bills are covered, nudge that the surplus could be put to work.
    """
    essentials = monthly_essential_expenses(db, year, month)
    if essentials <= 0:
        return None
    liquid = liquid_assets(db)
    buffer_needed = essentials * buffer_months
    idle = liquid - buffer_needed
    if idle > essentials * 0.5:  # meaningfully above buffer
        return idle
    return None


# --------------------------------------------------------------------------
# Debt payoff planner: snowball vs avalanche (Part III)
# --------------------------------------------------------------------------

@dataclass
class PayoffMonth:
    month_index: int
    payments: dict  # debt name -> amount paid this month
    balances: dict  # debt name -> remaining balance after payment
    total_interest_paid: float


def simulate_payoff(debts, extra_payment=0.0, strategy="avalanche", max_months=600):
    """
    debts: list of dicts {name, balance, apr, min_payment}
    strategy: 'avalanche' (highest APR first) or 'snowball' (smallest balance first)
    Returns (schedule: list[PayoffMonth], total_interest, months_to_payoff)
    """
    if extra_payment < 0:
        raise ValueError("Extra payment cannot be negative.")
    working = [dict(d) for d in debts if d["balance"] > 0]
    if not working:
        return [], 0.0, 0
    for d in working:
        if d.get("min_payment", 0) < 0:
            raise ValueError(f"{d['name']}: minimum payment cannot be negative.")
        custom = d.get("custom_payment") or 0
        if custom and custom < d["min_payment"]:
            raise ValueError(
                f"{d['name']}: planned payment ({custom}) is below its minimum payment ({d['min_payment']}).")
        # A debt's "planned payment" (custom_payment), if set, is a
        # guaranteed floor above the contractual minimum — e.g. someone
        # who always pays £200/month on a card with a £25 minimum. This
        # gets paid every month regardless of strategy; the avalanche/
        # snowball priority order only decides where any extra on top of
        # that goes.
        d["_effective_min"] = max(d["min_payment"], custom)

    if strategy == "avalanche":
        order = sorted(range(len(working)), key=lambda i: -working[i]["apr"])
    else:  # snowball
        order = sorted(range(len(working)), key=lambda i: working[i]["balance"])

    schedule = []
    total_interest = 0.0
    month = 0
    freed_up = 0.0  # min payments from paid-off debts roll into the next target (snowball/avalanche both do this)

    while any(d["balance"] > 0.01 for d in working) and month < max_months:
        month += 1
        month_payments = {}
        month_balances = {}
        month_interest = 0.0
        pool_extra = extra_payment + freed_up

        # accrue interest & apply each debt's effective minimum (its own
        # contractual min, or its planned custom_payment if that's higher)
        for d in working:
            if d["balance"] <= 0.01:
                month_balances[d["name"]] = 0.0
                continue
            interest = d["balance"] * (d["apr"] / 100 / 12)
            month_interest += interest
            d["balance"] += interest
            pay = min(d["_effective_min"], d["balance"])
            d["balance"] -= pay
            month_payments[d["name"]] = pay

        # apply extra payment pool to the priority-ordered target debt
        for idx in order:
            d = working[idx]
            if d["balance"] <= 0.01 or pool_extra <= 0:
                continue
            pay = min(pool_extra, d["balance"])
            d["balance"] -= pay
            month_payments[d["name"]] = month_payments.get(d["name"], 0.0) + pay
            pool_extra -= pay

        freed_up = 0.0
        for d in working:
            if d["balance"] <= 0.01:
                freed_up += d["_effective_min"]  # this debt's payment now rolls forward
                d["balance"] = 0.0
            month_balances[d["name"]] = round(d["balance"], 2)

        total_interest += month_interest
        schedule.append(PayoffMonth(month, month_payments, month_balances, month_interest))

    months_to_payoff = len(schedule)
    return schedule, total_interest, months_to_payoff


def life_energy_hours(amount, hourly_wage):
    """Your Money or Your Life-style: express a cost in hours-of-work."""
    if hourly_wage <= 0:
        return None
    return amount / hourly_wage


# --------------------------------------------------------------------------
# CSV import: validate/preview before committing (Part XII feature request)
# --------------------------------------------------------------------------

def csv_import_preview(db: Database, path, has_header=True,
                        col_date=0, col_payee=1, col_amount=2, col_currency=None,
                        col_category=None, default_currency=None, account_id=None):
    """Reads a CSV file and stages every row into import_staging WITHOUT
    touching `transactions`, validating each row as it goes (parseable
    date, parseable amount, category name resolved to an id if given).
    Returns (batch_id, rows) where rows mirrors what's now in the staging
    table, so the UI can render a preview grid with per-row errors before
    the user commits anything."""
    import csv as csv_mod

    default_currency = default_currency or db.get_setting("reporting_currency", "GBP")
    batch_id = uuid.uuid4().hex
    categories_by_name = {c["name"].lower(): c["id"] for c in db.list_categories()}

    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv_mod.reader(f)
        rows = list(reader)
    if has_header and rows:
        rows = rows[1:]

    staged = []
    with db.conn:
        for idx, row in enumerate(rows):
            raw_date = row[col_date].strip() if col_date < len(row) else ""
            raw_payee = row[col_payee].strip() if col_payee is not None and col_payee < len(row) else ""
            raw_amount = row[col_amount].strip() if col_amount < len(row) else ""
            raw_currency = (row[col_currency].strip() if col_currency is not None and col_currency < len(row)
                             else default_currency)
            raw_category = (row[col_category].strip() if col_category is not None and col_category < len(row)
                             else "")

            error = None
            parsed_date = parsed_amount = parsed_currency = None
            category_id = None
            try:
                parsed_date = datetime.date.fromisoformat(raw_date).isoformat()
            except (ValueError, TypeError):
                error = f"Unrecognised date '{raw_date}' (expected YYYY-MM-DD)"
            if error is None:
                try:
                    cleaned = raw_amount.replace(",", "").replace("£", "").replace("$", "").replace("€", "")
                    parsed_amount = float(cleaned)
                except (ValueError, TypeError):
                    error = f"Unrecognised amount '{raw_amount}'"
            if error is None:
                parsed_currency = (raw_currency or default_currency).upper()
                if len(parsed_currency) != 3:
                    error = f"Unrecognised currency code '{raw_currency}'"
            if error is None and raw_category:
                category_id = categories_by_name.get(raw_category.lower())
                if category_id is None:
                    error = f"Unknown category '{raw_category}' (will import uncategorised)"
                    # Non-fatal: still parses ok, just flagged so the user can see it.

            parsed_ok = parsed_date is not None and parsed_amount is not None and parsed_currency is not None

            likely_duplicate = False
            if parsed_ok and account_id is not None:
                dup = db.conn.execute(
                    "SELECT id FROM transactions WHERE account_id=? AND date=? AND amount=? LIMIT 1",
                    (account_id, parsed_date, parsed_amount),
                ).fetchone()
                likely_duplicate = dup is not None

            cur = db.conn.execute(
                "INSERT INTO import_staging(batch_id, row_index, raw_date, raw_payee, raw_amount, "
                "raw_currency, raw_category, parsed_date, parsed_amount, parsed_currency, category_id, "
                "account_id, parsed_ok, error, committed, likely_duplicate) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (batch_id, idx, raw_date, raw_payee, raw_amount, raw_currency, raw_category,
                 parsed_date, parsed_amount, parsed_currency, category_id, account_id,
                 int(parsed_ok), error, int(likely_duplicate)),
            )
            staged.append({"id": cur.lastrowid, "row_index": idx, "raw_date": raw_date,
                            "raw_payee": raw_payee, "raw_amount": raw_amount,
                            "parsed_date": parsed_date, "parsed_amount": parsed_amount,
                            "parsed_currency": parsed_currency, "category_id": category_id,
                            "parsed_ok": parsed_ok, "error": error, "likely_duplicate": likely_duplicate})
    return batch_id, staged


def csv_import_staged_rows(db: Database, batch_id):
    return db.conn.execute(
        "SELECT * FROM import_staging WHERE batch_id=? ORDER BY row_index", (batch_id,)
    ).fetchall()


def csv_import_commit(db: Database, batch_id, only_valid=True, skip_row_ids=None):
    """Commits a previously-staged batch into real transactions, all in one
    atomic transaction: either every eligible row becomes a transaction (with
    correct account-balance/roundup side effects) or, on any failure, none
    do. Rows with parsed_ok=0 are skipped unless only_valid=False. Returns
    (committed_count, skipped_count)."""
    skip_row_ids = set(skip_row_ids or [])
    rows = csv_import_staged_rows(db, batch_id)
    committed = skipped = 0
    with db.conn:
        for r in rows:
            if r["id"] in skip_row_ids or r["committed"]:
                skipped += 1
                continue
            if only_valid and not r["parsed_ok"]:
                skipped += 1
                continue
            if not r["parsed_ok"]:
                skipped += 1
                continue
            acc = db.get_account(r["account_id"]) if r["account_id"] else None
            cur = db.conn.execute(
                "INSERT INTO transactions(date, payee, category_id, amount, currency, note, account_id) "
                "VALUES (?, ?, ?, ?, ?, 'Imported from CSV', ?)",
                (r["parsed_date"], r["raw_payee"], r["category_id"], r["parsed_amount"],
                 r["parsed_currency"], r["account_id"]),
            )
            tx_id = cur.lastrowid
            if acc:
                db._apply_balance_effect_nocommit(acc, r["parsed_amount"], r["parsed_currency"])
            if r["parsed_amount"] < 0:
                db._apply_roundup_nocommit(tx_id, r["parsed_date"], r["parsed_amount"])
            db.conn.execute("UPDATE import_staging SET committed=1 WHERE id=?", (r["id"],))
            committed += 1
    return committed, skipped


def csv_import_discard(db: Database, batch_id):
    """Throws away a staged batch (e.g. the user cancelled the preview)
    without ever having touched `transactions`."""
    with db.conn:
        db.conn.execute("DELETE FROM import_staging WHERE batch_id=?", (batch_id,))


def export_transactions_csv_full(db: Database, path, currency_converter=None):
    """Like export_transactions_csv, but includes account, transfer, and
    reconciliation columns — useful for a full-fidelity backup/round-trip
    export rather than a simple statement-style CSV."""
    import csv
    rows = db.list_transactions(limit=1000000)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["date", "payee", "category", "amount", "currency", "note", "account",
                  "is_transfer", "reconciled"]
        if currency_converter:
            header.append("amount_reporting_ccy")
        writer.writerow(header)
        for t in rows:
            row = [t["date"], t["payee"] or "", t["category_name"] or "", t["amount"], t["currency"],
                   t["note"] or "", t["account_name"] or "", bool(t["is_transfer"]), bool(t["reconciled"])]
            if currency_converter:
                row.append(round(currency_converter(t["amount"], t["currency"]), 2))
            writer.writerow(row)
    return len(rows)


def export_account_statement_csv(db: Database, account_id, path):
    """A single account's transaction history with running balance, newest
    first — the order a real bank statement reads. Wraps account_ledger();
    useful as a lightweight proof-of-funds style document for one account,
    as opposed to export_transactions_csv_full's whole-profile dump."""
    import csv
    rows = db.account_ledger(account_id, limit=1000000)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "payee", "category", "amount", "currency", "note", "running_balance"])
        for r in rows:
            writer.writerow([r["date"], r["payee"] or "", r["category_name"] or "", r["amount"],
                              r["currency"], r["note"] or "", r["running_balance"]])
    return len(rows)


# --------------------------------------------------------------------------
# Editable per-profile CSV exports (transactions/accounts/categories/
# investments) — read by a human (or handed to an AI) for bulk editing or
# historical backfill outside the GUI, then read back in by the matching
# apply_*_csv() function. Each row's `id` column is what apply_*_csv() uses
# to tell an edit from a brand-new row (blank/missing id) from a deletion
# (an id that existed before but is now missing from the file).
# --------------------------------------------------------------------------

def export_transactions_editable_csv(db: Database, path):
    """Every transaction as an editable CSV. Transfer legs, reconciled
    transactions, and split transactions are included for visibility (so
    this is a genuinely complete picture of your history) but flagged via
    `status`, since editing those directly would bypass rules enforced
    elsewhere (a transfer's two linked legs, a locked reconciled row, a
    split's category breakdown) — apply_transactions_csv() skips changes
    to flagged rows rather than silently applying them."""
    import csv
    rows = db.list_transactions(limit=1000000)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "date", "payee", "category", "amount",
                                                "currency", "note", "account", "tags", "status"])
        writer.writeheader()
        for t in rows:
            if t["is_transfer"]:
                status = "transfer"
            elif t["reconciled"]:
                status = "reconciled"
            elif db.get_transaction_splits(t["id"]):
                status = "split"
            else:
                status = ""
            writer.writerow({
                "id": t["id"], "date": t["date"], "payee": t["payee"] or "",
                "category": t["category_name"] or "", "amount": t["amount"],
                "currency": t["currency"], "note": t["note"] or "",
                "account": t["account_name"] or "", "tags": ",".join(db.get_transaction_tags(t["id"])),
                "status": status,
            })
    return len(rows)


def export_accounts_editable_csv(db: Database, path):
    """kind/subtype are included for reference only — apply_accounts_csv()
    ignores edits to them, since they drive balance-effect sign logic
    elsewhere and aren't a safe blind field update."""
    import csv
    rows = db.list_accounts()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "kind", "subtype", "balance",
                                                "currency", "liquid"])
        writer.writeheader()
        for a in rows:
            writer.writerow({
                "id": a["id"], "name": a["name"], "kind": a["kind"], "subtype": a["subtype"] or "",
                "balance": a["balance"], "currency": a["currency"], "liquid": int(a["liquid"]),
            })
    return len(rows)


def export_categories_editable_csv(db: Database, path):
    import csv
    rows = db.list_categories()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "kind", "monthly_budget"])
        writer.writeheader()
        for c in rows:
            writer.writerow({"id": c["id"], "name": c["name"], "kind": c["kind"],
                              "monthly_budget": c["monthly_budget"]})
    return len(rows)


def export_investments_editable_csv(db: Database, path):
    """realized_gain is included for reference only — it's computed from
    the pool replay, not something apply_investments_csv() accepts edits
    to."""
    import csv
    rows = db.conn.execute(
        "SELECT s.*, a.name as account_name FROM security_lots s "
        "LEFT JOIN accounts a ON s.account_id = a.id ORDER BY s.date, s.id"
    ).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "account", "security", "date", "action",
                                                "quantity", "price", "fees", "currency", "note",
                                                "realized_gain"])
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "id": r["id"], "account": r["account_name"] or "", "security": r["security"],
                "date": r["date"], "action": r["action"], "quantity": r["quantity"],
                "price": r["price"], "fees": r["fees"], "currency": r["currency"],
                "note": r["note"] or "",
                "realized_gain": r["realized_gain"] if r["realized_gain"] is not None else "",
            })
    return len(rows)


def _transaction_status(db, t):
    if t["is_transfer"]:
        return "transfer"
    if t["reconciled"]:
        return "reconciled"
    if db.get_transaction_splits(t["id"]):
        return "split"
    return ""


def apply_transactions_csv(db: Database, path):
    """Reads a transactions.csv previously written by
    export_transactions_editable_csv() and applies whatever changed back
    into the database — through add_transaction()/update_transaction()/
    delete_transaction() (never raw SQL), so balances, round-ups, and
    cashback all stay correct. A blank `id` is a new row. An `id` that
    existed before but is now missing from the file is a deletion. Rows
    flagged transfer/reconciled/split (see _transaction_status) are
    protected — any change to one is skipped and reported, never applied,
    and a protected row is never deleted just because it's missing from
    the file. Returns {"added", "edited", "deleted", "skipped": [{"id",
    "reason"}]}."""
    import csv
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        csv_rows = list(csv.DictReader(f))

    categories_by_name = {c["name"].lower(): c["id"] for c in db.list_categories()}
    accounts_by_name = {a["name"].lower(): a["id"] for a in db.list_accounts()}
    existing = {t["id"]: t for t in db.list_transactions(limit=1000000)}

    report = {"added": 0, "edited": 0, "deleted": 0, "skipped": []}
    seen_ids = set()

    for row in csv_rows:
        raw_id = (row.get("id") or "").strip()

        # Resolve the id and mark it "seen" FIRST, before any other
        # validation. This must happen before any `continue` on a bad
        # field, or a mere typo (e.g. an unknown account name) on an
        # existing row would leave its id out of seen_ids — and the
        # cleanup pass below would then delete it, mistaking a validation
        # error for the row being intentionally removed from the file.
        current = None
        if raw_id:
            try:
                tx_id = int(raw_id)
            except ValueError:
                report["skipped"].append({"id": raw_id, "reason": f"Invalid id '{raw_id}'"})
                continue
            current = existing.get(tx_id)
            if current is None:
                report["skipped"].append(
                    {"id": raw_id, "reason": "No transaction with this id — leave id blank for a new row"})
                continue
            seen_ids.add(tx_id)
            status = _transaction_status(db, current)
            if status:
                report["skipped"].append(
                    {"id": raw_id, "reason": f"Protected ({status}) — edit this one from the app instead"})
                continue

        try:
            date = datetime.date.fromisoformat(row["date"].strip()).isoformat()
        except (ValueError, TypeError):
            report["skipped"].append({"id": raw_id, "reason": f"Unrecognised date '{row.get('date')}'"})
            continue
        try:
            amount = float(row["amount"])
        except (ValueError, TypeError):
            report["skipped"].append({"id": raw_id, "reason": f"Unrecognised amount '{row.get('amount')}'"})
            continue
        currency = (row.get("currency") or db.get_setting("reporting_currency", "GBP")).upper()
        payee = (row.get("payee") or "").strip()
        note = (row.get("note") or "").strip()
        account_name = (row.get("account") or "").strip()
        category_name = (row.get("category") or "").strip()
        tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]

        account_id = None
        if account_name:
            account_id = accounts_by_name.get(account_name.lower())
            if account_id is None:
                report["skipped"].append(
                    {"id": raw_id, "reason": f"Unknown account '{account_name}'"})
                continue
        category_id = None
        if category_name:
            category_id = categories_by_name.get(category_name.lower())
            if category_id is None:
                report["skipped"].append(
                    {"id": raw_id, "reason": f"Unknown category '{category_name}'"})
                continue

        if current is None:
            tx_id = db.add_transaction(date, payee, category_id, amount, currency, note,
                                        account_id=account_id)
            if tags:
                db.set_transaction_tags(tx_id, tags)
            report["added"] += 1
            continue

        current_tags = set(db.get_transaction_tags(tx_id))
        changed = (
            current["date"] != date or (current["payee"] or "") != payee or
            abs(current["amount"] - amount) > 0.005 or current["currency"] != currency or
            (current["note"] or "") != note or current["account_id"] != account_id or
            current["category_id"] != category_id or current_tags != set(tags)
        )
        if not changed:
            continue

        db.update_transaction(tx_id, date=date, payee=payee, category_id=category_id,
                               amount=amount, currency=currency, note=note, account_id=account_id)
        db.set_transaction_tags(tx_id, tags)
        report["edited"] += 1

    for tx_id, current in existing.items():
        if tx_id in seen_ids:
            continue
        status = _transaction_status(db, current)
        if status:
            report["skipped"].append(
                {"id": tx_id, "reason": f"Protected ({status}) — not deleted despite being missing "
                                         "from the file; delete it from the app instead"})
            continue
        db.delete_transaction(tx_id)
        report["deleted"] += 1

    return report


def apply_accounts_csv(db: Database, path):
    """Adds/edits accounts from accounts.csv. Never deletes — an account
    missing from the file is left alone, since other tables reference
    accounts by id and a mistaken blank row would have no clean undo.
    kind/subtype edits are ignored (see export_accounts_editable_csv)."""
    import csv
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        csv_rows = list(csv.DictReader(f))

    existing = {a["id"]: a for a in db.list_accounts()}
    report = {"added": 0, "edited": 0, "deleted": 0, "skipped": []}

    for row in csv_rows:
        raw_id = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        if not name:
            report["skipped"].append({"id": raw_id, "reason": "Missing account name"})
            continue
        try:
            balance = float(row["balance"])
        except (ValueError, TypeError):
            report["skipped"].append({"id": raw_id, "reason": f"Unrecognised balance '{row.get('balance')}'"})
            continue
        currency = (row.get("currency") or "GBP").upper()
        liquid = (row.get("liquid") or "0").strip() in ("1", "true", "True", "yes")

        if not raw_id:
            kind = (row.get("kind") or "asset").strip()
            subtype = (row.get("subtype") or "cash").strip()
            db.add_account(name, kind, balance, currency=currency, liquid=liquid, subtype=subtype)
            report["added"] += 1
            continue

        try:
            acc_id = int(raw_id)
        except ValueError:
            report["skipped"].append({"id": raw_id, "reason": f"Invalid id '{raw_id}'"})
            continue
        current = existing.get(acc_id)
        if current is None:
            report["skipped"].append(
                {"id": raw_id, "reason": "No account with this id — leave id blank for a new row"})
            continue

        changed = (current["name"] != name or abs(current["balance"] - balance) > 0.005 or
                   current["currency"] != currency or bool(current["liquid"]) != liquid)
        if not changed:
            continue
        db.update_account_core(acc_id, name=name, currency=currency, liquid=liquid)
        db.update_account_balance(acc_id, balance)
        report["edited"] += 1

    return report


def apply_categories_csv(db: Database, path):
    """Adds/edits categories from categories.csv. Never deletes — a
    missing category row is left alone (categories are referenced by
    transactions)."""
    import csv
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        csv_rows = list(csv.DictReader(f))

    existing = {c["id"]: c for c in db.list_categories()}
    report = {"added": 0, "edited": 0, "deleted": 0, "skipped": []}

    for row in csv_rows:
        raw_id = (row.get("id") or "").strip()
        name = (row.get("name") or "").strip()
        kind = (row.get("kind") or "").strip()
        if not name or kind not in ("need", "want", "saving", "income"):
            report["skipped"].append(
                {"id": raw_id, "reason": f"Missing name or invalid kind '{kind}' (need/want/saving/income)"})
            continue
        try:
            monthly_budget = float(row.get("monthly_budget") or 0)
        except ValueError:
            report["skipped"].append(
                {"id": raw_id, "reason": f"Unrecognised monthly_budget '{row.get('monthly_budget')}'"})
            continue

        if not raw_id:
            try:
                db.add_category(name, kind, monthly_budget)
            except sqlite3.IntegrityError:
                report["skipped"].append({"id": raw_id, "reason": f"Category '{name}' already exists"})
                continue
            report["added"] += 1
            continue

        try:
            cat_id = int(raw_id)
        except ValueError:
            report["skipped"].append({"id": raw_id, "reason": f"Invalid id '{raw_id}'"})
            continue
        current = existing.get(cat_id)
        if current is None:
            report["skipped"].append(
                {"id": raw_id, "reason": "No category with this id — leave id blank for a new row"})
            continue

        changed = (current["name"] != name or current["kind"] != kind or
                   abs((current["monthly_budget"] or 0) - monthly_budget) > 0.005)
        if not changed:
            continue
        db.update_category(cat_id, name=name, kind=kind, monthly_budget=monthly_budget)
        report["edited"] += 1

    return report


def apply_investments_csv(db: Database, path):
    """Adds/edits/deletes security transactions from investments.csv —
    unlike accounts/categories, deletion-by-omission is supported here
    since nothing else references a security_lots row by id, and bulk
    historical backfill/correction is the main reason this file exists.
    realized_gain edits are ignored — it's recomputed, not stored input."""
    import csv
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        csv_rows = list(csv.DictReader(f))

    accounts_by_name = {a["name"].lower(): a["id"] for a in db.list_accounts()}
    existing = {r["id"]: r for r in db.conn.execute("SELECT * FROM security_lots").fetchall()}
    report = {"added": 0, "edited": 0, "deleted": 0, "skipped": []}
    seen_ids = set()

    for row in csv_rows:
        raw_id = (row.get("id") or "").strip()

        # Resolve and register the id BEFORE any other validation — same
        # reasoning as apply_transactions_csv: a typo elsewhere in the row
        # must only skip that edit, never be mistaken for the row being
        # intentionally removed (which would delete it in the cleanup pass).
        current = None
        if raw_id:
            try:
                lot_id = int(raw_id)
            except ValueError:
                report["skipped"].append({"id": raw_id, "reason": f"Invalid id '{raw_id}'"})
                continue
            current = existing.get(lot_id)
            if current is None:
                report["skipped"].append(
                    {"id": raw_id,
                     "reason": "No security transaction with this id — leave id blank for a new row"})
                continue
            seen_ids.add(lot_id)

        account_name = (row.get("account") or "").strip()
        account_id = accounts_by_name.get(account_name.lower())
        if account_id is None:
            report["skipped"].append({"id": raw_id, "reason": f"Unknown account '{account_name}'"})
            continue
        security = (row.get("security") or "").strip()
        action = (row.get("action") or "").strip()
        if not security or action not in ("buy", "sell"):
            report["skipped"].append(
                {"id": raw_id, "reason": f"Missing security or invalid action '{action}' (buy/sell)"})
            continue
        try:
            date = datetime.date.fromisoformat(row["date"].strip()).isoformat()
            quantity = float(row["quantity"])
            price = float(row["price"])
            fees = float(row.get("fees") or 0)
        except (ValueError, TypeError, KeyError):
            report["skipped"].append({"id": raw_id, "reason": "Unrecognised date/quantity/price/fees"})
            continue
        currency = (row.get("currency") or db.get_setting("reporting_currency", "GBP")).upper()
        note = (row.get("note") or "").strip()

        if current is None:
            db.add_security_transaction(account_id, security, date, action, quantity, price,
                                         fees=fees, currency=currency, note=note)
            report["added"] += 1
            continue

        lot_id = current["id"]
        changed = (current["account_id"] != account_id or current["security"] != security or
                   current["date"] != date or current["action"] != action or
                   abs(current["quantity"] - quantity) > 0.0005 or abs(current["price"] - price) > 0.005 or
                   abs(current["fees"] - fees) > 0.005 or current["currency"] != currency or
                   (current["note"] or "") != note)
        if not changed:
            continue
        db.update_security_transaction(lot_id, date=date, action=action, quantity=quantity,
                                        price=price, fees=fees, currency=currency, note=note)
        report["edited"] += 1

    for lot_id in existing:
        if lot_id not in seen_ids:
            db.delete_security_transaction(lot_id)
            report["deleted"] += 1

    return report


PROFILE_CSV_FILENAMES = ("accounts.csv", "categories.csv", "transactions.csv", "investments.csv")


def refresh_profile_csvs(db: Database, profile_dir):
    """Regenerates all 4 editable CSVs from current data, overwriting
    whatever was there before — the "Refresh" half of the two-way sync.
    Never touches the database."""
    import os
    export_accounts_editable_csv(db, os.path.join(profile_dir, "accounts.csv"))
    export_categories_editable_csv(db, os.path.join(profile_dir, "categories.csv"))
    export_transactions_editable_csv(db, os.path.join(profile_dir, "transactions.csv"))
    export_investments_editable_csv(db, os.path.join(profile_dir, "investments.csv"))


def apply_profile_csvs(db: Database, profile_dir, db_path):
    """Backs up db_path, then applies all 4 CSVs and returns one combined
    report. Order matters: accounts.csv and categories.csv are applied
    first, so a brand-new account/category added there is already in the
    database by the time transactions.csv/investments.csv try to resolve
    it by name in the same pass. A CSV file that doesn't exist (e.g. never
    refreshed) is silently skipped rather than treated as an error."""
    import os
    import shutil
    import datetime as _dt

    backups_dir = os.path.join(profile_dir, "csv_sync_backups")
    os.makedirs(backups_dir, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backups_dir, f"profile_{stamp}.db")
    shutil.copy2(db_path, backup_path)

    combined = {"added": 0, "edited": 0, "deleted": 0, "skipped": [], "backup_path": backup_path}
    appliers = [
        ("accounts.csv", apply_accounts_csv),
        ("categories.csv", apply_categories_csv),
        ("transactions.csv", apply_transactions_csv),
        ("investments.csv", apply_investments_csv),
    ]
    for fname, apply_fn in appliers:
        path = os.path.join(profile_dir, fname)
        if not os.path.exists(path):
            continue
        report = apply_fn(db, path)
        combined["added"] += report["added"]
        combined["edited"] += report["edited"]
        combined["deleted"] += report["deleted"]
        for s in report["skipped"]:
            combined["skipped"].append({**s, "file": fname})
    return combined


# --------------------------------------------------------------------------
# Need/Want/Saving budget category enforcement (Part XII feature #6)
# --------------------------------------------------------------------------

def _category_spend_entries(db: Database, year, month):
    """Yields (category_id, category_kind, positive_reporting_ccy_amount)
    for every expense this month, exploding split transactions into their
    per-category pieces instead of attributing the whole amount to the
    transaction's own category_id. Shared by category_budget_status and
    spend_by_kind so both stay split-aware the same way."""
    for t in db.transactions_in_month(year, month):
        if t["amount"] >= 0:
            continue
        splits = db.get_transaction_splits(t["id"])
        if splits:
            for s in splits:
                if s["category_id"]:
                    yield s["category_id"], s["category_kind"], -db.to_reporting(s["amount"], t["currency"])
        elif t["category_id"]:
            yield t["category_id"], t["category_kind"], -db.to_reporting(t["amount"], t["currency"])


def category_budget_status(db: Database, year, month):
    """For every category with a monthly_budget set, how much of it has
    been spent this month and whether it's over. Feeds the Budgets tab's
    envelope bars and can be used to block/warn on new spending."""
    spent_by_cat = {}
    for cat_id, _kind, amount in _category_spend_entries(db, year, month):
        spent_by_cat[cat_id] = spent_by_cat.get(cat_id, 0.0) + amount

    out = []
    for cat in db.list_categories():
        if not cat["monthly_budget"]:
            continue
        spent = spent_by_cat.get(cat["id"], 0.0)
        pct = spent / cat["monthly_budget"] if cat["monthly_budget"] else 0.0
        out.append({"category": cat, "spent": spent, "budget": cat["monthly_budget"],
                     "pct": pct, "over": spent > cat["monthly_budget"]})
    out.sort(key=lambda r: -r["pct"])
    return out


def budget_run_rate(db: Database, year, month, today: Optional[datetime.date] = None):
    """Projects each budgeted category's month-end spend from the pace set
    so far this reporting period (spend-so-far / days-elapsed * days-in-
    period), so an overspend can be caught while there's still time to
    react instead of only after the period closes. Respects the
    month_start_day setting via month_bounds()."""
    today = today or datetime.date.today()
    start_str, end_str = month_bounds(db, year, month)
    start_date = datetime.date.fromisoformat(start_str)
    end_date = datetime.date.fromisoformat(end_str)
    days_in_month = (end_date - start_date).days + 1
    if today < start_date:
        days_elapsed = 0
    elif today > end_date:
        days_elapsed = days_in_month
    else:
        days_elapsed = (today - start_date).days + 1

    out = []
    for row in category_budget_status(db, year, month):
        projected = (row["spent"] / days_elapsed * days_in_month) if days_elapsed > 0 else 0.0
        out.append({**row, "days_elapsed": days_elapsed, "days_in_month": days_in_month,
                     "projected": projected, "projected_over": projected > row["budget"]})
    out.sort(key=lambda r: -(r["projected"] - r["budget"]))
    return out


def categories_over_threshold(db: Database, year, month, threshold_pct=None):
    """Categories whose spend-so-far this month has crossed threshold_pct
    of their monthly_budget (default from the budget_alert_threshold_pct
    setting, itself defaulting to 80). Feeds the Dashboard's alert list so
    a category can be flagged before it's actually over budget."""
    if threshold_pct is None:
        threshold_pct = db.get_setting_float("budget_alert_threshold_pct", 80.0)
    threshold = threshold_pct / 100.0
    return [row for row in category_budget_status(db, year, month) if row["pct"] >= threshold]


def would_exceed_budget(db: Database, category_id, amount, currency=None, year=None, month=None,
                         today: Optional[datetime.date] = None):
    """Would logging this expense (amount, negative, in `currency`) push
    the category over its monthly_budget? Used to enforce Need/Want/Saving
    envelopes at entry time rather than only reporting after the fact.
    Returns (would_exceed: bool, spent_after: float, budget: float) —
    budget of 0 means 'no cap set', which never counts as exceeding.

    `currency` matters: an earlier version of this converted `amount` as
    if it were already in the reporting currency, which silently skipped
    the conversion entirely for any transaction logged in a different
    currency (e.g. a €500 expense would've been compared against a GBP
    budget as if it were £500). Always pass the currency the amount is
    actually denominated in.

    year/month default to the reporting period "today" falls into (via
    custom_month_for_date, which respects month_start_day) rather than
    today's literal calendar year/month — "today" may be in a different
    calendar month than the reporting period it's chronologically part
    of."""
    if amount >= 0 or not category_id:
        return False, 0.0, 0.0
    today = today or datetime.date.today()
    if year is None or month is None:
        default_year, default_month = custom_month_for_date(db, today)
        year = year or default_year
        month = month or default_month
    currency = (currency or db.get_setting("reporting_currency", "GBP")).upper()
    cat = db.conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    if not cat or not cat["monthly_budget"]:
        return False, 0.0, 0.0
    spent = 0.0
    for t in db.transactions_in_month(year, month):
        if t["amount"] < 0 and t["category_id"] == category_id:
            spent += -db.to_reporting(t["amount"], t["currency"])
    spent_after = spent + (-db.to_reporting(amount, currency))
    return spent_after > cat["monthly_budget"], spent_after, cat["monthly_budget"]
