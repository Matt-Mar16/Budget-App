from pathlib import Path

import pandas as pd

LOG_COLUMNS = ["Date", "Account", "Category", "Description", "Amount", "Currency", "Exchange Rate", "synced_at"]


def parse_label(label):
    if label.endswith(")") and " (" in label:
        category, _, currency = label.rpartition(" (")
        return category, currency[:-1]
    return label, None


def load_transactions_log(path):
    if not Path(path).exists():
        df = pd.DataFrame(columns=LOG_COLUMNS)
        df["Date"] = pd.to_datetime(df["Date"])
        df["category"] = df["Category"]
        return df

    df = pd.read_csv(path, parse_dates=["Date"])
    df["Date"] = pd.to_datetime(df["Date"])
    df["category"] = df["Category"].apply(lambda label: parse_label(label)[0])
    return df


def budget_vs_actual(transactions_df, categories_df, currency, month):
    year, month_num = month
    budgeted = categories_df[
        (categories_df["Currency"] == currency) & categories_df["Monthly budget"].notna()
    ]

    in_currency = transactions_df[transactions_df["Currency"] == currency]
    in_month = in_currency[
        (in_currency["Date"].dt.year == year) & (in_currency["Date"].dt.month == month_num)
    ]
    spend_by_category = in_month.groupby("category")["Amount"].sum().mul(-1)

    result = budgeted.rename(columns={"Category": "category", "Monthly budget": "budget"}).copy()
    result["actual"] = result["category"].map(spend_by_category).fillna(0.0)
    result["remaining"] = result["budget"] - result["actual"]
    result["over_budget"] = result["actual"] > result["budget"]

    return result[["category", "budget", "actual", "remaining", "over_budget"]].reset_index(drop=True)


def account_running_balance(transactions_df, accounts_df, account_name, as_of=None):
    matches = accounts_df.loc[accounts_df["Account"] == account_name]
    if matches.empty:
        raise ValueError(f"Unknown account {account_name!r} — not found in the Accounts sheet")
    account_row = matches.iloc[0]

    account_txns = transactions_df[transactions_df["Account"] == account_name]
    if as_of is not None:
        account_txns = account_txns[account_txns["Date"] <= as_of]

    return account_row["Starting balance"] + account_txns["Amount"].sum()


def effective_exchange_rate(transactions_df):
    exchanges = transactions_df[transactions_df["category"] == "Currency Exchange"]
    cad_received = exchanges.loc[exchanges["Currency"] == "CAD", "Amount"].sum()
    gbp_sent = exchanges.loc[exchanges["Currency"] == "GBP", "Amount"].sum()
    if gbp_sent == 0:
        return None
    return cad_received / abs(gbp_sent)


def sankey_flows(transactions_df):
    def spend_by_category(currency):
        subset = transactions_df[
            (transactions_df["Currency"] == currency)
            & ~transactions_df["category"].isin(["Income", "Currency Exchange"])
        ]
        return subset.groupby("category")["Amount"].sum().mul(-1)

    exchanges = transactions_df[transactions_df["category"] == "Currency Exchange"]
    gbp_income = transactions_df.loc[
        (transactions_df["category"] == "Income") & (transactions_df["Currency"] == "GBP"), "Amount"
    ].sum()
    gbp_spend = spend_by_category("GBP")
    gbp_exchanged = abs(exchanges.loc[exchanges["Currency"] == "GBP", "Amount"].sum())
    cad_received = exchanges.loc[exchanges["Currency"] == "CAD", "Amount"].sum()
    cad_spend = spend_by_category("CAD")

    unspent_gbp = gbp_income - gbp_spend.sum() - gbp_exchanged
    unspent_cad = cad_received - cad_spend.sum()

    nodes = ["Income (GBP)"]

    def node_index(label):
        if label not in nodes:
            nodes.append(label)
        return nodes.index(label)

    income_idx = 0
    links = []

    for category, amount in gbp_spend.items():
        if amount == 0:
            continue
        links.append({"source": income_idx, "target": node_index(f"{category} (GBP)"), "value": amount})

    exchange_idx = node_index("Currency Exchange")
    links.append({"source": income_idx, "target": exchange_idx, "value": gbp_exchanged})

    unspent_gbp_idx = node_index("Unspent GBP")
    links.append({"source": income_idx, "target": unspent_gbp_idx, "value": unspent_gbp})

    cad_funds_idx = node_index("CAD Funds")
    links.append({"source": exchange_idx, "target": cad_funds_idx, "value": cad_received})

    for category, amount in cad_spend.items():
        if amount == 0:
            continue
        links.append({"source": cad_funds_idx, "target": node_index(f"{category} (CAD)"), "value": amount})

    unspent_cad_idx = node_index("Unspent CAD")
    links.append({"source": cad_funds_idx, "target": unspent_cad_idx, "value": unspent_cad})

    return {"nodes": nodes, "links": links}


def is_below_threshold(balance, threshold=0):
    return balance < threshold
