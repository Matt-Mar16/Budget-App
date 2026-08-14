#!/usr/bin/env python3
"""
The Ledger — a budgeting app synthesizing personal-finance research into a
single desktop tool.

Run:
    python3 budget_app.py

No third-party dependencies — stdlib only (tkinter + sqlite3). Every
profile's data is stored locally in a "Profiles" folder next to this code —
nothing leaves
the machine.

Core feature set (the app has grown well beyond this original list since —
see CLAUDE.md for the full, current picture, including everything added
across later feature rounds: transfers, reconciliation, cashback rules,
custom recurring schedules, a custom month-start day, the Accounts/Net
Worth split, the Forecast tab, and more):
 1. Real-time "safe to spend" / runway number             -> Dashboard
 2. Monthly savings target as a fixed line item            -> Settings + Dashboard
 3. Multi-currency ledger with editable FX table            -> Transactions + Settings
 4. Net worth tracking over time + FI number                -> Net Worth tab (with trend chart)
 5. Savings rate as a headline metric                       -> Dashboard
 6. Category budgets w/ envelope visual metaphor            -> Budgets tab
 7. Lifestyle-inflation flag                                -> Dashboard
 8. Debt payoff planner: snowball vs avalanche              -> Debt Planner tab
 9. Financial health ratios panel                           -> Dashboard
10. Idle-cash nudge                                         -> Dashboard
11. Simple statistical anomaly flags                        -> Dashboard
12. Life-energy (hours-of-work) view                        -> Transactions + Settings
13. Low-friction "set once, check monthly" mode              -> whole app is check-in based
14. Local-first storage (SQLite file per profile)            -> finance_core.Database
15. Multiple user profiles, each fully isolated              -> profiles.py + launcher screen
16. Recurring bills / paychecks, auto-posted on open         -> Recurring tab
17. CSV export                                               -> Transactions tab
18. Dark / light theme                                       -> Settings tab
19. Trend & allocation charts (net worth, income vs. expense, envelope split)
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, colorchooser
import datetime
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from finance_core import (
    Database, net_worth, monthly_totals, savings_rate,
    emergency_fund_ratio, debt_to_income, housing_ratio, safe_to_spend,
    fi_number, category_anomalies, lifestyle_inflation_flags, idle_cash_nudge,
    simulate_payoff, life_energy_hours,
    monthly_history, spend_by_kind, upcoming_bills, export_transactions_csv,
    export_transactions_csv_full, export_account_statement_csv,
    net_worth_breakdown, credit_utilization,
    upcoming_card_payments,
    budget_run_rate, categories_over_threshold, top_payees, daily_spend_totals,
    detect_recurring_candidates, refresh_profile_csvs, apply_profile_csvs,
    income_by_category, custom_month_for_date, month_bounds,
    whatif_category_adjustment, goal_projection,
)
import profiles
import theme
import charts

APP_TITLE = "The Ledger"

CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "JPY": "¥", "AUD": "A$",
                     "CAD": "C$", "CHF": "CHF", "NZD": "NZ$", "INR": "₹"}

# Cycled through for per-category donut segments, where the theme's small
# set of semantic colors (accent/good/warn/bad) isn't enough for an
# arbitrary number of categories.
CATEGORY_CHART_COLORS = ["#5B8DEF", "#4CC9A0", "#F2994A", "#E4574C", "#9B6BDE",
                          "#4AB8C4", "#E0A93E", "#6E7FE0", "#D46FB0", "#67B356"]


def resolve_category_colors(categories):
    """Every category gets a color: its own custom pick (categories.color)
    if set, else one cycled from CATEGORY_CHART_COLORS by list position --
    so a color swatch/highlight is never blank/grey even before anything's
    been customized. Cycled globally across the list (not restarted per
    kind), matching the order list_categories() already returns."""
    return {
        cat["id"]: cat["color"] or CATEGORY_CHART_COLORS[i % len(CATEGORY_CHART_COLORS)]
        for i, cat in enumerate(categories)
    }


def fmt_money(x, currency="GBP"):
    try:
        symbol = CURRENCY_SYMBOLS.get((currency or "").upper())
        if symbol:
            sign = "-" if x < 0 else ""
            return f"{sign}{symbol}{abs(x):,.2f}"
        return f"{x:,.2f} {currency}"
    except (TypeError, ValueError):
        return str(x)


def fmt_pct(x):
    try:
        return f"{x*100:,.1f}%"
    except (TypeError, ValueError):
        return str(x)


# ==========================================================================
# Small reusable widgets
# ==========================================================================

class Avatar(tk.Canvas):
    """A colored circle with an emoji/initial inside — used for profile chips."""

    def __init__(self, parent, glyph, color, size=40, bg=None):
        super().__init__(parent, width=size, height=size, highlightthickness=0,
                          bg=bg or (parent["bg"] if isinstance(parent, tk.Widget) else None))
        r = size / 2
        self.create_oval(2, 2, size - 2, size - 2, fill=color, outline="")
        self.create_text(r, r, text=glyph, font=(theme.Fonts.family, int(size * 0.42)))


class Card(ttk.LabelFrame):
    """A titled card container using the theme's card styling."""

    def __init__(self, parent, title="", **kw):
        super().__init__(parent, text=title, padding=14, **kw)


def enable_drag_reorder(handles_and_rows, on_reorder):
    """Wires drag-to-reorder onto a vertically pack()'d list of rows that
    share one parent. Rows stay put while dragging -- a thin colored
    insertion line (Notion-style) tracks the gap the pointer is currently
    over, and the actual reorder (a single repack) happens only on
    release, when on_reorder(ids_in_final_order) is called once. Reusable
    by any tab that wants drag reordering instead of Up/Down buttons;
    takes (handle_widget, row_widget, item_id) triples so a small grip
    icon can be the drag target while the rest of the row's own widgets
    (entries, buttons) keep working normally.
    """
    rows = [row for _, row, _ in handles_and_rows]
    item_id_by_row = {row: item_id for _, row, item_id in handles_and_rows}
    if not rows:
        return
    parent = rows[0].master
    indicator = tk.Frame(parent, height=3, bg=theme.Palette.c["accent"])
    dragging = {"row": None, "target_before": None}

    def gap_before(row, pointer_y):
        """Which sibling (excluding `row` itself) the pointer is currently
        above the midpoint of -- insert before that one. None means
        "insert at the end" (pointer is below every other row)."""
        for other in rows:
            if other is row:
                continue
            mid = other.winfo_rooty() + other.winfo_height() // 2
            if pointer_y < mid:
                return other
        return None

    def show_indicator(target_before):
        indicator.pack_forget()
        if target_before is not None:
            indicator.pack(fill="x", pady=2, before=target_before)
        else:
            indicator.pack(fill="x", pady=2)

    def on_press(row, event):
        dragging["row"] = row
        target = gap_before(row, event.y_root)
        dragging["target_before"] = target
        show_indicator(target)

    def on_motion(row, event):
        if dragging["row"] is not row:
            return
        target = gap_before(row, event.y_root)
        if target is not dragging["target_before"]:
            dragging["target_before"] = target
            show_indicator(target)

    def on_release(row):
        if dragging["row"] is not row:
            return
        dragging["row"] = None
        indicator.pack_forget()
        remaining = [r for r in rows if r is not row]
        target = dragging["target_before"]
        insert_at = remaining.index(target) if target is not None else len(remaining)
        new_order = remaining[:insert_at] + [row] + remaining[insert_at:]
        for r in new_order:
            r.pack_forget()
            r.pack(fill="x", pady=5)
        on_reorder([item_id_by_row[r] for r in new_order])

    for handle, row, _ in handles_and_rows:
        handle.configure(cursor="fleur")
        handle.bind("<ButtonPress-1>", lambda e, r=row: on_press(r, e))
        handle.bind("<B1-Motion>", lambda e, r=row: on_motion(r, e))
        handle.bind("<ButtonRelease-1>", lambda e, r=row: on_release(r))


class ScrollableTab(ttk.Frame):
    """Base class for tab pages: gives every tab clean vertical scrolling
    without any subclass needing to change how it builds its content.

    The trick: `self` (the tab) is embedded as a window inside a Canvas,
    instead of being gridded directly into the page container. Every
    existing `_build()` method already uses `self` as the parent for its
    widgets — that still works completely unchanged, since `self` still IS
    the frame those widgets live in. Only `grid()`/`tkraise()` are
    overridden, to act on the canvas+scrollbar wrapper instead of on
    `self` directly, since callers only ever grid/raise a tab as a whole
    page (see App._build_layout / App.show_page) — nothing calls
    self.pack()/self.grid() on a tab from inside its own _build()."""

    def __init__(self, parent, app):
        self.wrapper = ttk.Frame(parent)
        self.wrapper.rowconfigure(0, weight=1)
        self.wrapper.columnconfigure(0, weight=1)

        canvas = tk.Canvas(self.wrapper, highlightthickness=0, bg=app.c["bg"])
        vsb = ttk.Scrollbar(self.wrapper, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self._canvas = canvas
        self._vsb = vsb

        super().__init__(canvas, padding=(0, 0, 12, 12))
        window_id = canvas.create_window((0, 0), window=self, anchor="nw")

        def _update_scrollbar_visibility():
            bbox = canvas.bbox("all")
            content_height = (bbox[3] - bbox[1]) if bbox else 0
            if content_height > canvas.winfo_height():
                vsb.grid(row=0, column=1, sticky="ns")
            else:
                vsb.grid_remove()

        self._update_scrollbar_visibility = _update_scrollbar_visibility

        def _on_self_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            _update_scrollbar_visibility()

        def _on_canvas_configure(e):
            canvas.itemconfig(window_id, width=e.width)
            _update_scrollbar_visibility()

        self.bind("<Configure>", _on_self_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_wheel(event):
            # Widgets that scroll their own content (Treeview/Text) should keep
            # the wheel to themselves rather than also scrolling the page under them.
            if isinstance(event.widget, (ttk.Treeview, tk.Text)):
                return
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def grid(self, **kw):
        self.wrapper.grid(**kw)

    def tkraise(self, *args, **kw):
        self.wrapper.tkraise(*args, **kw)


def make_scrollable_toplevel(parent, title, geometry):
    """Builds a tk.Toplevel whose content scrolls automatically if it's
    taller than the window, using the same canvas-embedding trick as
    ScrollableTab -- so a popup that isn't manually resized never clips
    content off the bottom instead of just growing past the screen.
    Returns (win, content): win for title()/geometry()/protocol()/etc.,
    content as the parent frame for the dialog's own widgets (the role
    'self' plays inside a ScrollableTab subclass)."""
    win = tk.Toplevel(parent)
    win.title(title)
    c = theme.Palette.c
    win.configure(bg=c["bg"])
    win.geometry(geometry)

    canvas = tk.Canvas(win, highlightthickness=0, bg=c["bg"])
    vsb = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    content = ttk.Frame(canvas)
    window_id = canvas.create_window((0, 0), window=content, anchor="nw")

    def _on_content_configure(_e):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(e):
        canvas.itemconfig(window_id, width=e.width)

    content.bind("<Configure>", _on_content_configure)
    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_wheel(event):
        if isinstance(event.widget, (ttk.Treeview, tk.Text)):
            return
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    return win, content


def metric_cell(parent, title, accent_color=None):
    """A titled stat card. accent_color, if given, colors just the title
    label -- purely decorative variety between cards, kept visually
    separate from the value label's own health-based coloring (Good/Warn/
    Bad.TLabel), which callers apply dynamically based on what the number
    actually means."""
    cell = Card(parent, title="")
    title_label = ttk.Label(cell, text=title, style="CardDim.TLabel")
    if accent_color:
        title_label.configure(foreground=accent_color)
    title_label.pack(anchor="w")
    val = ttk.Label(cell, text="—", style="H2.TLabel", font=theme.Fonts.h1)
    val.pack(anchor="w", pady=(2, 0))
    return cell, val


# ==========================================================================
# Profile launcher — the first thing the user sees
# ==========================================================================

class ProfileCard(ttk.Frame):
    def __init__(self, parent, profile, on_open, on_delete):
        super().__init__(parent, style="Card.TFrame", padding=16)
        self.profile = profile
        c = theme.Palette.c

        top = ttk.Frame(self, style="Card.TFrame")
        top.pack(fill="x")
        Avatar(top, profile["avatar"], profile["color"], size=46, bg=c["card"]).pack(side="left")
        info = ttk.Frame(top, style="Card.TFrame")
        info.pack(side="left", padx=10)
        ttk.Label(info, text=profile["name"], style="Card.TLabel", font=theme.Fonts.h2).pack(anchor="w")
        ttk.Label(info, text=f"Last opened {profile['last_opened']}", style="CardDim.TLabel").pack(anchor="w")

        btn_row = ttk.Frame(self, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="Open", style="Accent.TButton",
                   command=lambda: on_open(profile)).pack(side="left")
        ttk.Button(btn_row, text="Delete", command=lambda: on_delete(profile)).pack(side="left", padx=6)

        for w in (self, top, info):
            w.bind("<Button-1>", lambda e: on_open(profile))


class ProfileLauncher(tk.Tk):
    """Startup screen: pick a profile or create a new one. Selecting a
    profile tears this window down and launches the main App on top of
    that profile's own SQLite file — no data ever crosses profiles."""

    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} — Choose a profile")
        self.geometry("640x520")
        self.minsize(480, 420)
        self.style = ttk.Style(self)
        self.c = theme.apply_theme(self, self.style, mode="dark")
        self._build()

    def _build(self):
        wrap = ttk.Frame(self, padding=28)
        wrap.pack(fill="both", expand=True)

        ttk.Label(wrap, text="Welcome to The Ledger", style="H1.TLabel",
                  font=theme.Fonts.display).pack(anchor="w")
        ttk.Label(wrap, text="Everything is stored locally, per profile — nothing leaves this machine.",
                  style="Dim.TLabel").pack(anchor="w", pady=(2, 18))

        self.import_banner = ttk.Frame(wrap)
        self.import_banner.pack(fill="x")

        self.list_frame = ttk.Frame(wrap)
        self.list_frame.pack(fill="both", expand=True)

        new_row = ttk.Frame(wrap)
        new_row.pack(fill="x", pady=(16, 0))
        ttk.Label(new_row, text="New profile name:", style="Dim.TLabel").pack(side="left")
        self.new_name = tk.StringVar()
        entry = ttk.Entry(new_row, textvariable=self.new_name, width=24)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda e: self._create())
        ttk.Button(new_row, text="+ Create Profile", style="Good.TButton",
                   command=self._create).pack(side="left")
        ttk.Button(new_row, text="Import Existing Profile…",
                   command=self._import_dialog).pack(side="left", padx=8)

        self._refresh_list()

    def _refresh_list(self):
        for w in self.import_banner.winfo_children():
            w.destroy()
        unregistered = profiles.find_unregistered_db_files()
        if unregistered:
            banner = Card(self.import_banner, title="")
            banner.pack(fill="x", pady=(0, 12))
            names = ", ".join(os.path.basename(p) for p in unregistered)
            ttk.Label(banner, text=f"Found {len(unregistered)} database file(s) in Profiles/ that "
                                    f"aren't set up as a profile yet: {names}",
                      style="Card.TLabel", wraplength=540, justify="left").pack(anchor="w")
            for path in unregistered:
                ttk.Button(banner, text=f"Add '{os.path.basename(path)}' as a profile",
                           command=lambda p=path: self._import_path(p)).pack(anchor="w", pady=(6, 0))

        for w in self.list_frame.winfo_children():
            w.destroy()
        plist = profiles.list_profiles()
        if not plist:
            ttk.Label(self.list_frame, text="No profiles yet — create your first one below.",
                      style="Dim.TLabel").pack(pady=40)
            return
        canvas = tk.Canvas(self.list_frame, bg=self.c["bg"], highlightthickness=0)
        scroll = ttk.Scrollbar(self.list_frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=560)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for p in plist:
            card = ProfileCard(inner, p, self._open, self._delete)
            card.pack(fill="x", pady=6, padx=2)

    def _create(self):
        name = self.new_name.get().strip()
        if not name:
            messagebox.showinfo("Name needed", "Give the new profile a name first.")
            return
        profile = profiles.create_profile(name)
        self.new_name.set("")
        self._open(profile)

    def _delete(self, profile):
        if messagebox.askyesno("Delete profile",
                                f"Delete '{profile['name']}'? This also permanently deletes its ledger "
                                f"data on disk and cannot be undone."):
            ok = profiles.delete_profile(profile["slug"], delete_data=True)
            if not ok:
                messagebox.showwarning(
                    "Profile removed, but…",
                    f"'{profile['name']}' was removed from this list, but its data file is still "
                    f"locked by another process (often a leftover open window) and couldn't be "
                    f"deleted automatically. You can safely delete it yourself later from:\n\n"
                    f"{profiles.db_path_for(profile['slug'])}")
            self._refresh_list()

    def _import_path(self, path):
        default_name = os.path.splitext(os.path.basename(path))[0].replace("_", " ").title()
        name = simpledialog.askstring("Profile Name", "Name to show for this profile:",
                                       initialvalue=default_name, parent=self)
        if name is None:
            return
        profile = profiles.import_existing_db(path, name.strip() or default_name)
        self._refresh_list()
        messagebox.showinfo("Imported", f"'{profile['name']}' is ready — click Open to use it.")

    def _import_dialog(self):
        path = filedialog.askopenfilename(
            title="Choose a Ledger profile database (.db)",
            initialdir=profiles.APP_DIR,
            filetypes=[("Ledger database", "*.db"), ("All files", "*.*")])
        if not path:
            return
        self._import_path(path)

    def _open(self, profile):
        profiles.touch_profile(profile["slug"])
        self.destroy()
        app = App(profile)
        app.mainloop()


# ==========================================================================
# Main application window
# ==========================================================================

NAV_GROUPS = [
    ("Daily", [
        ("dashboard", "🏠", "Dashboard"),
        ("transactions", "💳", "Transactions"),
        ("budgets", "🧾", "Budgets"),
        ("insights", "🔎", "Insights"),
        ("forecast", "🧭", "Forecast"),
    ]),
    ("Planning", [
        ("recurring", "🔁", "Recurring"),
        ("debt", "📉", "Debt Planner"),
        ("accounts", "🏦", "Accounts"),
        ("networth", "📈", "Net Worth / FI"),
        ("rewards", "🐷", "Rewards"),
    ]),
]
SETTINGS_NAV_ITEM = ("settings", "⚙", "Settings")
NAV_ITEMS = [item for _, items in NAV_GROUPS for item in items] + [SETTINGS_NAV_ITEM]
PROTECTED_NAV_KEYS = {"dashboard", "settings"}
COLLAPSIBLE_GROUPS = {"Planning"}


def get_hidden_nav_tabs(db):
    """Nav keys the user has chosen to hide from the sidebar, stored as a
    comma-separated `hidden_nav_tabs` setting (same pattern as
    currency_mode/budget_alert_threshold_pct). Defensively strips
    PROTECTED_NAV_KEYS in case the setting was ever hand-edited or saved
    by an older version — Dashboard and Settings can never be hidden."""
    raw = db.get_setting("hidden_nav_tabs", "")
    hidden = {k.strip() for k in raw.split(",") if k.strip()}
    return hidden - PROTECTED_NAV_KEYS


def set_hidden_nav_tabs(db, keys):
    keys = set(keys) - PROTECTED_NAV_KEYS
    db.set_setting("hidden_nav_tabs", ",".join(sorted(keys)))


def visible_nav_groups(nav_groups, hidden_keys):
    """Filters hidden items out of each group, dropping any group that
    ends up empty. Pure data transform, no Tkinter — the sidebar re-render
    and the Settings checklist both build off this."""
    out = []
    for group_name, items in nav_groups:
        visible_items = [item for item in items if item[0] not in hidden_keys]
        if visible_items:
            out.append((group_name, visible_items))
    return out


DASHBOARD_SECTIONS = [
    ("hero", "Safe to Spend"),
    ("metrics", "Key Metrics"),
    ("quick_actions", "Quick Actions"),
    ("charts", "Charts (Spend Split & Trend)"),
    ("needs_attention", "Needs Attention"),
    ("flags", "Flags & Nudges"),
]
DASHBOARD_SECTION_KEYS = [key for key, _ in DASHBOARD_SECTIONS]


def resolve_dashboard_layout(db):
    """Reconciles the saved dashboard_layout setting against the currently
    known section keys: drops any saved key no longer in DASHBOARD_SECTIONS
    (e.g. a section removed in a later version), appends any known key
    missing from the saved list (e.g. a section added later) as visible, at
    the end. Returns a list of {"key", "visible"} covering every key in
    DASHBOARD_SECTION_KEYS, in display order. Pure function so it's
    unit-testable without Tkinter, matching get_hidden_nav_tabs/
    visible_nav_groups above."""
    saved = db.get_dashboard_layout()
    known = set(DASHBOARD_SECTION_KEYS)
    result = [entry for entry in saved if entry["key"] in known]
    present = {entry["key"] for entry in result}
    for key in DASHBOARD_SECTION_KEYS:
        if key not in present:
            result.append({"key": key, "visible": True})
    return result


def submit_new_transaction(app, date, payee, category_name, amount_raw, currency, note,
                            account_name, tag_names_raw="", confirm_over_budget=None):
    """Validates and writes a new transaction -- the exact logic
    TransactionsTab's inline Add form uses, extracted so the Dashboard's
    Add Transaction popup (see DashboardTab.open_add_transaction_dialog)
    can share it instead of re-implementing validation. Returns
    (ok, error_message); error_message is None on success. On success the
    transaction (and any tags) has already been written to app.db -- the
    caller still calls app.refresh_all() afterward, same as before.
    confirm_over_budget defaults to messagebox.askyesno but can be swapped
    for a plain callable in tests, so this function needs no live Tkinter
    event loop to test."""
    if confirm_over_budget is None:
        confirm_over_budget = messagebox.askyesno

    date = date.strip()
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        return False, "Please use YYYY-MM-DD format."
    try:
        amount = float(amount_raw)
    except ValueError:
        return False, "Amount must be a number (negative for expenses)."

    categories = app.db.list_categories()
    categories_by_name = {c["name"]: c["id"] for c in categories}
    category_kind_by_id = {c["id"]: c["kind"] for c in categories}
    accounts_by_name = {a["name"]: a for a in app.db.list_accounts()}
    cat_id = categories_by_name.get(category_name.strip())
    account = accounts_by_name.get(account_name.strip())
    account_id = account["id"] if account else None
    currency = currency.strip().upper() or app.reporting_currency()
    payee = payee.strip()
    note = note.strip()

    if cat_id:
        kind = category_kind_by_id.get(cat_id)
        if kind == "income" and amount < 0:
            return False, "An expense can't be filed under an income category."
        if kind and kind != "income" and amount > 0:
            return False, "Income can't be filed under a spending category."

    if cat_id and amount < 0:
        from finance_core import would_exceed_budget
        exceeds, spent_after, budget = would_exceed_budget(app.db, cat_id, amount, currency)
        if exceeds:
            cur = app.reporting_currency()
            proceed = confirm_over_budget(
                "Over budget",
                f"This would bring '{category_name}' spending to {fmt_money(spent_after, cur)}, "
                f"over its {fmt_money(budget, cur)} monthly budget. Add it anyway?")
            if not proceed:
                return False, None

    tx_id = app.db.add_transaction(date, payee, cat_id, amount, currency, note,
                                    account_id=account_id)
    tag_names = [t.strip() for t in tag_names_raw.split(",") if t.strip()]
    if tag_names:
        app.db.set_transaction_tags(tx_id, tag_names)
    return True, None


class App(tk.Tk):
    def __init__(self, profile):
        super().__init__()
        self.profile = profile
        self.title(f"{APP_TITLE} — {profile['name']}")
        self.geometry("1220x760")
        self.minsize(980, 620)

        self.db = Database(profiles.db_path_for(profile["slug"]))
        self.today = datetime.date.today()
        self.view_year, self.view_month = custom_month_for_date(self.db, self.today)

        self.style = ttk.Style(self)
        mode = self.db.get_setting("theme_mode", "dark")
        self.c = theme.apply_theme(self, self.style, mode=mode)

        # quietly post any bills/paychecks that came due since last opened
        posted = self.db.generate_due_recurring(self.today)

        self._build_menu_bar()
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        if posted:
            names = ", ".join(p[0] for p in posted[:5])
            more = f" (+{len(posted) - 5} more)" if len(posted) > 5 else ""
            messagebox.showinfo("Recurring items posted",
                                 f"Posted {len(posted)} due recurring transaction(s): {names}{more}.")

    # ---- shell ----
    def _build_menu_bar(self):
        bar = tk.Menu(self)
        filemenu = tk.Menu(bar, tearoff=0)
        filemenu.add_command(label="Refresh", command=self.refresh_all)
        filemenu.add_command(label="Export Transactions to CSV…", command=self.export_csv)
        filemenu.add_separator()
        filemenu.add_command(label="Switch Profile…", command=self.switch_profile)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.on_close)
        bar.add_cascade(label="File", menu=filemenu)

        viewmenu = tk.Menu(bar, tearoff=0)
        viewmenu.add_command(label="Toggle Dark / Light Theme", command=self.toggle_theme)
        bar.add_cascade(label="View", menu=viewmenu)
        self.config(menu=bar)

    def _build_layout(self):
        c = self.c
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(root, style="Sidebar.TFrame", width=210)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        profile_chip = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(16, 20, 16, 14))
        profile_chip.pack(fill="x")
        Avatar(profile_chip, self.profile["avatar"], self.profile["color"], size=40,
               bg=c["sidebar"]).pack(side="left")
        info = ttk.Frame(profile_chip, style="Sidebar.TFrame")
        info.pack(side="left", padx=8)
        self.profile_name_label = tk.Label(info, text=self.profile["name"], bg=c["sidebar"],
                                            fg=c["text"], font=theme.Fonts.body_bold)
        self.profile_name_label.pack(anchor="w")
        tk.Label(info, text=APP_TITLE, bg=c["sidebar"], fg=c["text_faint"],
                 font=theme.Fonts.small).pack(anchor="w")

        ttk.Separator(sidebar).pack(fill="x", padx=12, pady=(0, 6))

        self.nav_wrap = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self.nav_wrap.pack(fill="x", pady=4)
        self._nav_group_expanded = {}

        bottom = ttk.Frame(sidebar, style="Sidebar.TFrame")
        bottom.pack(side="bottom", fill="x", padx=12, pady=14)
        settings_key, settings_icon, settings_label = SETTINGS_NAV_ITEM
        self.settings_nav_button = ttk.Button(
            bottom, text=f"  {settings_icon}   {settings_label}", style="Nav.TButton",
            command=lambda: self.show_page(settings_key))
        self.settings_nav_button.pack(fill="x", pady=(0, 8))
        ttk.Separator(bottom).pack(fill="x", pady=(0, 8))
        ttk.Button(bottom, text="Switch Profile", command=self.switch_profile).pack(fill="x", pady=2)

        self._build_nav_buttons()

        # content area
        content_outer = ttk.Frame(root)
        content_outer.grid(row=0, column=1, sticky="nsew")
        content_outer.rowconfigure(1, weight=1)
        content_outer.columnconfigure(0, weight=1)

        topbar = ttk.Frame(content_outer, padding=(20, 16, 20, 6))
        topbar.grid(row=0, column=0, sticky="ew")
        self.page_title = ttk.Label(topbar, text="Dashboard", style="H1.TLabel")
        self.page_title.pack(side="left")

        nav_month = ttk.Frame(topbar)
        nav_month.pack(side="right")
        self.month_label = ttk.Label(nav_month, style="Dim.TLabel")
        self.month_label.pack(side="left", padx=(0, 10))
        ttk.Button(nav_month, text="←", width=3, command=self.prev_month).pack(side="left")
        ttk.Button(nav_month, text="Today", command=self.goto_today).pack(side="left", padx=4)
        ttk.Button(nav_month, text="→", width=3, command=self.next_month).pack(side="left")

        self.container = ttk.Frame(content_outer, padding=(20, 4, 20, 16))
        self.container.grid(row=1, column=0, sticky="nsew")
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        self.pages = {
            "dashboard": DashboardTab(self.container, self),
            "transactions": TransactionsTab(self.container, self),
            "budgets": BudgetsTab(self.container, self),
            "recurring": RecurringTab(self.container, self),
            "debt": DebtPlannerTab(self.container, self),
            "accounts": AccountsTab(self.container, self),
            "networth": NetWorthTab(self.container, self),
            "insights": InsightsTab(self.container, self),
            "forecast": ForecastTab(self.container, self),
            "rewards": RewardsTab(self.container, self),
            "settings": SettingsTab(self.container, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.show_page("dashboard")

    def _build_nav_buttons(self):
        """(Re)builds the grouped sidebar nav from NAV_GROUPS, filtered by
        the user's hidden_nav_tabs setting. Called at startup and again
        whenever a collapsible group is toggled or the hidden-tabs setting
        changes, so it always reflects current state."""
        for w in self.nav_wrap.winfo_children():
            w.destroy()
        self.nav_buttons = {"settings": self.settings_nav_button}

        c = self.c
        hidden = get_hidden_nav_tabs(self.db)
        for group_name, items in visible_nav_groups(NAV_GROUPS, hidden):
            collapsible = group_name in COLLAPSIBLE_GROUPS
            expanded = self._nav_group_expanded.get(group_name, False)
            if collapsible:
                arrow = "▾" if expanded else "▸"
                header = tk.Label(self.nav_wrap, text=f"{group_name.upper()}   {arrow} {len(items)}",
                                   bg=c["sidebar"], fg=c["text_faint"], font=theme.Fonts.small,
                                   cursor="hand2")
                header.pack(anchor="w", padx=20, pady=(10, 4))
                header.bind("<Button-1>", lambda e, g=group_name: self._toggle_nav_group(g))
                if not expanded:
                    continue
            else:
                tk.Label(self.nav_wrap, text=group_name.upper(), bg=c["sidebar"], fg=c["text_faint"],
                         font=theme.Fonts.small).pack(anchor="w", padx=20, pady=(10, 4))
            for key, icon, label in items:
                btn = ttk.Button(self.nav_wrap, text=f"  {icon}   {label}", style="Nav.TButton",
                                  command=lambda k=key: self.show_page(k))
                btn.pack(fill="x", padx=10, pady=2)
                self.nav_buttons[key] = btn

        current = getattr(self, "current_page", "dashboard")
        for k, btn in self.nav_buttons.items():
            btn.configure(style="NavActive.TButton" if k == current else "Nav.TButton")

    def _toggle_nav_group(self, group_name):
        self._nav_group_expanded[group_name] = not self._nav_group_expanded.get(group_name, False)
        self._build_nav_buttons()

    def show_page(self, key):
        # Every tab is built once, up front, in _build_layout() -- switching
        # pages never recreates widgets, it just raises the target tab above
        # the others (tkraise()) and refreshes that one tab's data. Contrast
        # with refresh_all() below, which refreshes every tab regardless of
        # which is currently visible, so none of them show stale data the
        # next time the user switches to it after an edit elsewhere.
        if key in get_hidden_nav_tabs(self.db):
            key = "dashboard"
        self.current_page = key
        for k, btn in self.nav_buttons.items():
            btn.configure(style="NavActive.TButton" if k == key else "Nav.TButton")
        label_map = {k: label for k, _, label in NAV_ITEMS}
        self.page_title.configure(text=label_map[key])
        self.pages[key].tkraise()
        if hasattr(self.pages[key], "refresh"):
            self.pages[key].refresh()
        self._update_month_label()

    def _update_month_label(self):
        if self.db.get_setting_int("month_start_day", 1) == 1:
            text = datetime.date(self.view_year, self.view_month, 1).strftime("%B %Y")
        else:
            start_str, end_str = month_bounds(self.db, self.view_year, self.view_month)
            start_date = datetime.date.fromisoformat(start_str)
            end_date = datetime.date.fromisoformat(end_str)
            text = f"{start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}"
        self.month_label.configure(text=text)

    # ---- month navigation shared by dashboard / budgets ----
    def prev_month(self):
        y, m = self.view_year, self.view_month
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        self.view_year, self.view_month = y, m
        self.refresh_all()

    def next_month(self):
        y, m = self.view_year, self.view_month
        m += 1
        if m == 13:
            m, y = 1, y + 1
        self.view_year, self.view_month = y, m
        self.refresh_all()

    def goto_today(self):
        self.view_year, self.view_month = custom_month_for_date(self.db, self.today)
        self.refresh_all()

    # ---- misc app-level actions ----
    def reporting_currency(self):
        return self.db.get_setting("reporting_currency", "GBP")

    def currency_mode(self):
        """'home' hides multi-currency UI (FX rates, per-account currency
        picker) for everyday single-currency use; 'holiday' shows it all.
        Purely a UI simplification — every account/transaction still has a
        real currency underneath either way, so switching modes never loses
        or reinterprets data, it just changes what's visible."""
        return self.db.get_setting("currency_mode", "home")

    def refresh_all(self):
        self._update_month_label()
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                page.refresh()

    def toggle_theme(self):
        new_mode = "light" if theme.Palette.mode == "dark" else "dark"
        self.db.set_setting("theme_mode", new_mode)
        messagebox.showinfo("Theme changed",
                             "Restart The Ledger to fully apply the new theme.")

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             filetypes=[("CSV", "*.csv")],
                                             initialfile="transactions.csv")
        if not path:
            return
        n = export_transactions_csv(self.db, path, currency_converter=self.db.to_reporting)
        messagebox.showinfo("Exported", f"Exported {n} transaction(s) to:\n{path}")

    def export_csv_full(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             filetypes=[("CSV", "*.csv")],
                                             initialfile="transactions_full.csv")
        if not path:
            return
        n = export_transactions_csv_full(self.db, path, currency_converter=self.db.to_reporting)
        messagebox.showinfo(
            "Exported", f"Exported {n} transaction(s) (with account/transfer/reconciled detail) to:\n{path}")

    def switch_profile(self):
        self.db.close()
        self.destroy()
        launcher = ProfileLauncher()
        launcher.mainloop()

    def rename_profile(self, new_name):
        new_name = new_name.strip()
        if not new_name:
            return
        profiles.rename_profile(self.profile["slug"], new_name)
        self.profile["name"] = new_name
        self.profile_name_label.config(text=new_name)
        if "settings" in self.pages:
            self.pages["settings"].refresh()

    def on_close(self):
        self.db.close()
        self.destroy()


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

class DashboardTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        c = self.app.c
        self.section_frames = {}
        self.section_handles = {}
        section_labels = dict(DASHBOARD_SECTIONS)

        def start_section(key):
            outer = ttk.Frame(self)
            handle_row = ttk.Frame(outer)
            handle_row.pack(fill="x")
            handle = ttk.Label(handle_row, text="⠿", style="Dim.TLabel", cursor="fleur")
            handle.pack(side="left")
            ttk.Label(handle_row, text=section_labels[key], style="Dim.TLabel").pack(side="left", padx=(4, 0))
            self.section_frames[key] = outer
            self.section_handles[key] = handle
            return outer

        # Safe-to-spend hero
        hero_section = start_section("hero")
        hero = Card(hero_section, title="")
        hero.pack(fill="x", pady=(0, 10))
        ttk.Label(hero, text="SAFE TO SPEND / DAY", style="CardDim.TLabel").pack(anchor="w")
        self.safe_to_spend_label = ttk.Label(hero, text="—", style="Hero.TLabel")
        self.safe_to_spend_label.pack(anchor="w")
        self.safe_to_spend_sub = ttk.Label(hero, text="", style="CardDim.TLabel")
        self.safe_to_spend_sub.pack(anchor="w", pady=(4, 0))

        # Metrics grid
        metrics_section = start_section("metrics")
        grid = ttk.Frame(metrics_section)
        grid.pack(fill="x", pady=(0, 10))
        self.metric_labels = {}
        # Decorative per-card accent colors -- Income/Expenses keep their
        # meaningful good/bad (green/red) coloring instead, since that
        # already means something (see refresh()).
        metrics = [
            ("Savings Rate", "#9B6BDE"), ("Emergency Fund", "#4AB8C4"),
            ("Debt-to-Income", "#E0A93E"), ("Housing Ratio", "#D46FB0"),
            ("Income (mo.)", c["good"]), ("Expenses (mo.)", c["bad"]),
        ]
        for i, (m, accent) in enumerate(metrics):
            cell, val = metric_cell(grid, m, accent_color=accent)
            cell.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            grid.columnconfigure(i % 3, weight=1)
            self.metric_labels[m] = val

        # Quick Actions -- content added in Task 6
        quick_actions_section = start_section("quick_actions")
        qa_card = Card(quick_actions_section, title="Quick Actions")
        qa_card.pack(fill="x", pady=(0, 10))
        self.quick_actions_row = ttk.Frame(qa_card, style="Card.TFrame")
        self.quick_actions_row.pack(fill="x")
        ttk.Button(self.quick_actions_row, text="+ Add Transaction", style="Good.TButton",
                   command=self.open_add_transaction_dialog).pack(side="left")
        ttk.Button(self.quick_actions_row, text="Transfer Between Accounts…", style="Accent.TButton",
                   command=lambda: self.app.pages["accounts"].open_transfer_dialog()).pack(
            side="left", padx=(8, 0))

        # Charts row: allocation donut + 6-month trend bar chart
        charts_section = start_section("charts")
        charts_row = ttk.Frame(charts_section)
        charts_row.pack(fill="x", pady=(0, 10))
        charts_row.columnconfigure(0, weight=1)
        charts_row.columnconfigure(1, weight=2)

        donut_card = Card(charts_row, title="This Month's Spend — Need / Want / Saving")
        donut_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.donut_canvas = tk.Canvas(donut_card, height=200, highlightthickness=0,
                                       bg=c["card"])
        self.donut_canvas.pack(fill="both", expand=True)

        trend_card = Card(charts_row, title="Income vs. Expenses")
        trend_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        range_row = ttk.Frame(trend_card, style="Card.TFrame")
        range_row.pack(fill="x", anchor="e")
        ttk.Label(range_row, text="Range:", style="CardDim.TLabel").pack(side="left")
        self.trend_range_var = tk.StringVar(value="6 months")
        self.trend_range_labels = {
            "6 months": 6, "12 months": 12, "24 months": 24, "36 months": 36,
        }
        trend_range_combo = ttk.Combobox(range_row, textvariable=self.trend_range_var,
                                          values=list(self.trend_range_labels), width=10, state="readonly")
        trend_range_combo.pack(side="left", padx=(4, 0))
        trend_range_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.trend_canvas = tk.Canvas(trend_card, height=200, highlightthickness=0,
                                       bg=c["card"])
        self.trend_canvas.pack(fill="both", expand=True)

        # Needs Attention -- content added in Task 7
        needs_attention_section = start_section("needs_attention")
        na_card = Card(needs_attention_section, title="Needs Attention")
        na_card.pack(fill="x", pady=(0, 10))
        self.needs_attention_rows_frame = ttk.Frame(na_card, style="Card.TFrame")
        self.needs_attention_rows_frame.pack(fill="x")

        # Flags panel
        flags_section = start_section("flags")
        flags_card = Card(flags_section, title="Flags & Nudges")
        flags_card.pack(fill="both", expand=True)
        self.flags_text = tk.Text(flags_card, wrap="word", state="disabled", height=10,
                                   bg=c["card"], fg=c["text"], insertbackground=c["text"],
                                   relief="flat", font=theme.Fonts.body, padx=4, pady=4)
        self.flags_text.pack(fill="both", expand=True)
        self.flags_text.tag_configure("warn", foreground=c["warn"])
        self.flags_text.tag_configure("good", foreground=c["good"])
        self.flags_text.tag_configure("info", foreground=c["accent"])
        # More specific nudge flavors get their own color instead of all
        # non-severity items sharing the one generic "info" blue.
        self.flags_text.tag_configure("bill", foreground="#6E7FE0")
        self.flags_text.tag_configure("reward", foreground="#E0A93E")
        self.flags_text.tag_configure("idle", foreground="#4AB8C4")

        self._apply_layout()

    def _apply_layout(self):
        layout = resolve_dashboard_layout(self.app.db)
        if layout == getattr(self, "_applied_layout", None):
            return
        self._applied_layout = layout
        for entry in layout:
            self.section_frames[entry["key"]].pack_forget()
        for entry in layout:
            if entry["visible"]:
                if entry["key"] == "flags":
                    self.section_frames[entry["key"]].pack(fill="both", expand=True, pady=5)
                else:
                    self.section_frames[entry["key"]].pack(fill="x", pady=5)
        visible_rows = [
            (self.section_handles[e["key"]], self.section_frames[e["key"]], e["key"])
            for e in layout if e["visible"]
        ]
        if visible_rows:
            enable_drag_reorder(visible_rows, self._on_reorder)

    def _on_reorder(self, ordered_keys):
        layout = resolve_dashboard_layout(self.app.db)
        hidden_entries = [e for e in layout if not e["visible"]]
        new_layout = [{"key": k, "visible": True} for k in ordered_keys] + hidden_entries
        self.app.db.set_dashboard_layout(new_layout)
        self._apply_layout()

    def open_add_transaction_dialog(self):
        win, content = make_scrollable_toplevel(self, "Add Transaction", "420x460")
        cats = [c["name"] for c in self.app.db.list_categories()]
        accounts = [a["name"] for a in self.app.db.list_accounts() if a["subtype"] != "roundup_pot"]

        ttk.Label(content, text="Date (YYYY-MM-DD)", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        date_var = tk.StringVar(value=self.app.today.isoformat())
        ttk.Entry(content, textvariable=date_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Payee", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        payee_var = tk.StringVar()
        ttk.Entry(content, textvariable=payee_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Category", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        category_var = tk.StringVar()
        ttk.Combobox(content, textvariable=category_var, values=cats, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="Amount (negative for expenses)", style="TLabel").pack(
            anchor="w", padx=14, pady=(10, 2))
        amount_var = tk.StringVar()
        ttk.Entry(content, textvariable=amount_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Currency", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        currency_var = tk.StringVar(value=self.app.reporting_currency())
        ttk.Entry(content, textvariable=currency_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Account", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        account_var = tk.StringVar()
        ttk.Combobox(content, textvariable=account_var, values=accounts, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="Note", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        note_var = tk.StringVar()
        ttk.Entry(content, textvariable=note_var).pack(fill="x", padx=14)

        def submit():
            ok, error = submit_new_transaction(
                self.app, date_var.get(), payee_var.get(), category_var.get(),
                amount_var.get(), currency_var.get(), note_var.get(), account_var.get())
            if not ok:
                if error:
                    messagebox.showerror("Invalid entry", error)
                return
            self.app.refresh_all()
            win.destroy()

        ttk.Button(content, text="Add Transaction", style="Accent.TButton", command=submit).pack(
            anchor="w", padx=14, pady=14)

    def _refresh_needs_attention(self):
        for w in self.needs_attention_rows_frame.winfo_children():
            w.destroy()
        db = self.app.db
        cur = self.app.reporting_currency()

        bills = upcoming_bills(db, within_days=14, today=self.app.today)[:4]
        reimbursements = db.list_outstanding_reimbursements()[:4]
        candidates = detect_recurring_candidates(db)[:4]

        if not bills and not reimbursements and not candidates:
            ttk.Label(self.needs_attention_rows_frame, text="You're all caught up.",
                      style="CardDim.TLabel").pack(anchor="w")
            return

        if bills:
            ttk.Label(self.needs_attention_rows_frame, text="Bills due soon",
                      style="CardDim.TLabel").pack(anchor="w", pady=(0, 2))
            for b in bills:
                row = ttk.Frame(self.needs_attention_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=f"📅 {b['name']} ({fmt_money(b['amount'], b['currency'])}) — "
                                     f"{b['next_date']}", style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Post Now",
                           command=lambda rid=b["id"]: self._post_bill_now(rid)).pack(side="right")

        if reimbursements:
            ttk.Label(self.needs_attention_rows_frame, text="Outstanding reimbursements",
                      style="CardDim.TLabel").pack(anchor="w", pady=(8, 2))
            for r in reimbursements:
                row = ttk.Frame(self.needs_attention_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=f"{r['owed_by']} owes {fmt_money(r['amount'], cur)} — "
                                     f"{r['payee'] or '(no payee)'}",
                          style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Mark Settled",
                           command=lambda rid=r["id"]: self._settle_reimbursement_now(rid)).pack(
                    side="right")

        if candidates:
            ttk.Label(self.needs_attention_rows_frame, text="Detected subscriptions",
                      style="CardDim.TLabel").pack(anchor="w", pady=(8, 2))
            for cand in candidates:
                row = ttk.Frame(self.needs_attention_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                ttk.Label(row, text=f"{cand['payee']} — "
                                     f"{fmt_money(cand['last_amount'], cand['last_currency'])} "
                                     f"every ~{cand['avg_interval_days']:.0f} days",
                          style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Ignore",
                           command=lambda c=cand: self._ignore_candidate_now(c)).pack(
                    side="right", padx=(6, 0))
                ttk.Button(row, text="Add to Recurring",
                           command=lambda c=cand: self._add_candidate_to_recurring(c)).pack(
                    side="right")

    def _post_bill_now(self, recurring_id):
        self.app.db.post_recurring_item(recurring_id)
        self.app.refresh_all()

    def _settle_reimbursement_now(self, reimbursement_id):
        self.app.db.settle_reimbursement(reimbursement_id)
        self.app.refresh_all()

    def _ignore_candidate_now(self, candidate):
        self.app.db.add_ignored_subscription(candidate["payee"])
        self.app.refresh_all()

    def _add_candidate_to_recurring(self, candidate):
        self.app.show_page("recurring")
        self.app.pages["recurring"]._prefill_from_candidate(candidate)

    def refresh(self):
        self._apply_layout()
        db = self.app.db
        c = self.app.c
        y, m = self.app.view_year, self.app.view_month
        cur = self.app.reporting_currency()

        rate_per_day, remaining, days_left = safe_to_spend(db, y, m, self.app.today)
        self.safe_to_spend_label.config(text=fmt_money(rate_per_day, cur))
        self.safe_to_spend_sub.config(
            text=f"{fmt_money(remaining, cur)} left over {days_left} day(s) remaining in the month")

        income, expenses, savings = monthly_totals(db, y, m)
        sr = savings_rate(db, y, m)
        ef = emergency_fund_ratio(db, y, m)
        dti = debt_to_income(db, y, m)
        hr = housing_ratio(db, y, m)

        # Value text is colored by health (distinct from the title's purely
        # decorative accent color set in _build()) -- green/orange/red
        # against the same thresholds the Flags & Nudges panel already
        # uses, or the faint/dim color for an "n/a" reading.
        def health_color(value, good_if, warn_if):
            if value is None:
                return c["text_faint"]
            if good_if(value):
                return c["good"]
            if warn_if(value):
                return c["warn"]
            return c["bad"]

        self.metric_labels["Savings Rate"].config(
            text=fmt_pct(sr), foreground=health_color(sr, lambda v: v >= 0.15, lambda v: v >= 0.10))
        self.metric_labels["Emergency Fund"].config(
            text=(f"{ef:,.1f} mo" if ef is not None else "n/a"),
            foreground=health_color(ef, lambda v: v >= 3, lambda v: v >= 1))
        self.metric_labels["Debt-to-Income"].config(
            text=(fmt_pct(dti) if dti is not None else "n/a"),
            foreground=health_color(dti, lambda v: v <= 0.36, lambda v: v <= 0.43))
        self.metric_labels["Housing Ratio"].config(
            text=(fmt_pct(hr) if hr is not None else "n/a"),
            foreground=health_color(hr, lambda v: v <= 0.30, lambda v: v <= 0.40))
        self.metric_labels["Income (mo.)"].config(text=fmt_money(income, cur))
        self.metric_labels["Expenses (mo.)"].config(text=fmt_money(expenses, cur))

        # donut: need/want/saving split
        kind_spend = spend_by_kind(db, y, m)
        # Purely decorative segment colors, deliberately distinct from
        # c["accent"]/c["warn"]/c["good"] -- those carry pass/fail meaning
        # elsewhere (Flags & Nudges tags, metric-card health coloring) and
        # reusing them here would make this donut look like a status readout.
        segments = [
            ("Needs", kind_spend["need"], CATEGORY_CHART_COLORS[4]),
            ("Wants", kind_spend["want"], CATEGORY_CHART_COLORS[5]),
            ("Saving", kind_spend["saving"], CATEGORY_CHART_COLORS[8]),
        ]
        charts.draw_donut_chart(self.donut_canvas, segments, c,
                                 center_label=fmt_money(expenses, cur), center_sub="total spend")

        # trend: income vs expenses, over the selected range
        n_months = self.trend_range_labels.get(self.trend_range_var.get(), 6)
        history = monthly_history(db, y, m, n_months=n_months)
        cats = [label for label, _, _ in history]
        income_series = [i for _, i, _ in history]
        expense_series = [e for _, _, e in history]
        charts.draw_bar_chart(self.trend_canvas, cats,
                               [("Income", "good", income_series), ("Expenses", "bad", expense_series)],
                               c, unit_fmt=lambda v: f"{v:,.0f}")

        target = db.get_setting_float("monthly_savings_target", 0.0)
        lines = []
        if sr < 0.10:
            lines.append(("warn", f"⚠ You saved {fmt_pct(sr)} of your income this month — "
                                   f"below the 10% baseline."))
        elif sr < 0.15:
            lines.append(("info", f"ℹ You saved {fmt_pct(sr)} this month — solid, but aim for "
                                   f"15–20%+ if you can."))
        else:
            lines.append(("good", f"✓ You saved {fmt_pct(sr)} this month — right in the healthy "
                                   f"range. Nice."))

        if target > 0 and savings < target:
            lines.append(("warn", f"⚠ You're {fmt_money(target - savings, cur)} short of your "
                                   f"{fmt_money(target, cur)} savings target this month "
                                   f"({fmt_money(savings, cur)} saved so far)."))

        if ef is not None:
            if ef < 3:
                lines.append(("warn", f"⚠ Your emergency fund covers {ef:,.1f} months of expenses "
                                       f"— aim for 3–6."))
            else:
                lines.append(("good", f"✓ Your emergency fund covers {ef:,.1f} months of "
                                       f"essentials — you're covered."))

        if dti is not None and dti > 0.36:
            lines.append(("warn", f"⚠ Debt-to-income is {fmt_pct(dti)} — above the 36% healthy threshold."))

        threshold_pct = db.get_setting_float("budget_alert_threshold_pct", 80.0)
        for row in categories_over_threshold(db, y, m, threshold_pct=threshold_pct):
            if row["over"]:
                lines.append(("warn", f"⚠ You've gone over on {row['category']['name']} — "
                                       f"{fmt_money(row['spent'], cur)} spent against a "
                                       f"{fmt_money(row['budget'], cur)} budget."))
            else:
                lines.append(("info", f"ℹ {row['category']['name']} is at {fmt_pct(row['pct'])} of "
                                       f"its {fmt_money(row['budget'], cur)} budget — worth a glance "
                                       f"before month-end."))

        idle = idle_cash_nudge(db, y, m)
        if idle:
            lines.append(("idle", f"💡 You've got about {fmt_money(idle, cur)} sitting idle above "
                                   f"your safety buffer — could be working harder for you."))

        for card in credit_utilization(db):
            util = card["utilization"]
            if util >= 0.70:
                lines.append(("warn", f"⚠ {card['account']['name']} is at {util*100:,.0f}% "
                                       f"utilization ({fmt_money(card['balance'], cur)} of "
                                       f"{fmt_money(card['limit'], cur)}) — that can ding your "
                                       f"credit score; try to get it under 30%."))

        for due in upcoming_card_payments(db, within_days=7, today=self.app.today):
            lines.append(("warn", f"💳 {due['account']['name']} payment of "
                                   f"{fmt_money(due['balance'], cur)} is due {due['due_date']} — "
                                   f"don't forget."))

        unredeemed = db.get_unredeemed_cashback()
        if unredeemed >= 5:
            lines.append(("reward", f"💳 You've got {fmt_money(unredeemed, cur)} in unredeemed "
                                   f"cashback sitting there — grab it on the Rewards tab whenever."))

        jar = db.get_or_create_roundup_jar()
        if jar["balance"] >= 10:
            lines.append(("reward", f"🐷 Your Round-Up Jar has {fmt_money(jar['balance'], cur)} "
                                   f"saved up — sweep it into savings whenever you're ready."))

        bills = upcoming_bills(db, within_days=14, today=self.app.today)
        for b in bills[:4]:
            lines.append(("bill", f"📅 {b['name']} ({fmt_money(b['amount'], cur)}) is due "
                                   f"{b['next_date']} — coming up."))

        for f in lifestyle_inflation_flags(db, y, m)[:4]:
            lines.append(("warn", f"⚠ Your spending on {f['category']} jumped {fmt_pct(f['growth'])} "
                                   f"this month, while income only grew {fmt_pct(f['income_growth'])} "
                                   f"— creeping lifestyle inflation?"))

        for a in category_anomalies(db)[:4]:
            t = a["transaction"]
            lines.append(("info", f"🔍 {t['payee'] or t['category_name']} on {t['date']} cost "
                                   f"{fmt_money(a['amount'], cur)} — well above what you usually "
                                   f"spend there."))

        if not lines:
            lines.append(("good", "Nothing flagged this month — looking healthy."))

        self.flags_text.config(state="normal")
        self.flags_text.delete("1.0", "end")
        for i, (tag, text) in enumerate(lines):
            if i:
                self.flags_text.insert("end", "\n\n")
            self.flags_text.insert("end", text, tag)
        self.flags_text.config(state="disabled")

        self._refresh_needs_attention()


# --------------------------------------------------------------------------
# Shared transaction edit dialog — used from the Transactions tab list and
# from the account ledger detail view, so an edit made either place goes
# through the same finance_core.update_transaction() call and the same
# reconciled/transfer guards.
# --------------------------------------------------------------------------

def open_transaction_edit_dialog(parent, app, tx_id, on_saved=None):
    from finance_core import ReconciledTransactionError

    db = app.db
    tx = db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not tx:
        return
    if tx["is_transfer"]:
        messagebox.showinfo(
            "Transfer",
            "This is one leg of a transfer and can't be edited directly. Delete the transfer "
            "(from either account's ledger) and create a new one instead.")
        return

    win, content = make_scrollable_toplevel(parent, "Edit Transaction", "440x520")

    cats = db.list_categories()
    cat_names = [c["name"] for c in cats]
    cat_id_by_name = {c["name"]: c["id"] for c in cats}
    cat_name_by_id = {c["id"]: c["name"] for c in cats}

    accounts = [a for a in db.list_accounts() if a["subtype"] != "roundup_pot"]
    acc_names = [a["name"] for a in accounts]
    acc_id_by_name = {a["name"]: a["id"] for a in accounts}
    acc_name_by_id = {a["id"]: a["name"] for a in accounts}

    if tx["reconciled"]:
        ttk.Label(content, text="🔒 This transaction is reconciled/locked.",
                  style="Warn.TLabel", wraplength=340, justify="left").pack(
            anchor="w", padx=14, pady=(14, 0))

    date_var = tk.StringVar(value=tx["date"])
    payee_var = tk.StringVar(value=tx["payee"] or "")
    category_var = tk.StringVar(value=cat_name_by_id.get(tx["category_id"], ""))
    amount_var = tk.StringVar(value=f"{tx['amount']:.2f}")
    currency_var = tk.StringVar(value=tx["currency"])
    note_var = tk.StringVar(value=tx["note"] or "")
    account_var = tk.StringVar(value=acc_name_by_id.get(tx["account_id"], ""))
    tags_var = tk.StringVar(value=", ".join(db.get_transaction_tags(tx_id)))
    original_cashback_str = f"{tx['cashback'] or 0:.2f}"
    cashback_var = tk.StringVar(value=original_cashback_str)

    fields = [
        ("Date (YYYY-MM-DD)", date_var, None),
        ("Payee", payee_var, None),
        ("Category", category_var, [""] + cat_names),
        ("Amount (+income / -expense)", amount_var, None),
        ("Currency", currency_var, None),
        ("Note", note_var, None),
        ("Paid from", account_var, [""] + acc_names),
        ("Tags (comma-separated)", tags_var, None),
        ("Cashback (auto-calculated — edit to override manually)", cashback_var, None),
    ]
    for label, var, options in fields:
        ttk.Label(content, text=label, style="TLabel").pack(anchor="w", padx=14, pady=(8, 2))
        if options is not None:
            ttk.Combobox(content, textvariable=var, values=options, state="readonly").pack(
                fill="x", padx=14)
        else:
            ttk.Entry(content, textvariable=var).pack(fill="x", padx=14)

    def do_save():
        try:
            datetime.date.fromisoformat(date_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid date", "Date must be YYYY-MM-DD.")
            return
        try:
            amount = float(amount_var.get())
        except ValueError:
            messagebox.showerror("Invalid amount", "Amount must be a number.")
            return
        currency = currency_var.get().strip().upper() or app.reporting_currency()
        category_id = cat_id_by_name.get(category_var.get().strip())
        account_id = acc_id_by_name.get(account_var.get().strip())

        # Only treat Cashback as a manual override if the user actually
        # changed it from what was loaded -- otherwise leave it untouched
        # (None) so the normal rate/cap auto-calculation still reacts to
        # amount/account changes, same as before this field existed.
        cashback_override = None
        if cashback_var.get().strip() != original_cashback_str:
            try:
                cashback_override = float(cashback_var.get())
            except ValueError:
                messagebox.showerror("Invalid cashback", "Cashback must be a number.")
                return

        try:
            db.update_transaction(
                tx_id, date=date_var.get().strip(), payee=payee_var.get().strip(),
                category_id=category_id, amount=amount, currency=currency,
                note=note_var.get().strip(), account_id=account_id,
                cashback=cashback_override,
            )
        except ReconciledTransactionError:
            if messagebox.askyesno(
                    "Reconciled transaction",
                    "This transaction is reconciled/locked. Unreconcile and save the edit anyway?"):
                db.update_transaction(
                    tx_id, date=date_var.get().strip(), payee=payee_var.get().strip(),
                    category_id=category_id, amount=amount, currency=currency,
                    note=note_var.get().strip(), account_id=account_id,
                    cashback=cashback_override,
                    force_unreconciled=True,
                )
                db.unreconcile_transaction(tx_id)
            else:
                return
        except ValueError as e:
            messagebox.showerror("Can't save", str(e))
            return

        tag_names = [t.strip() for t in tags_var.get().split(",") if t.strip()]
        db.set_transaction_tags(tx_id, tag_names)

        win.destroy()
        if on_saved:
            on_saved()

    def do_delete():
        try:
            db.delete_transaction(tx_id)
        except ReconciledTransactionError:
            if messagebox.askyesno(
                    "Reconciled transaction",
                    "This transaction is reconciled/locked. Unreconcile and delete it anyway?"):
                db.delete_transaction(tx_id, force_unreconciled=True)
            else:
                return
        win.destroy()
        if on_saved:
            on_saved()

    btn_row = ttk.Frame(content)
    btn_row.pack(fill="x", padx=14, pady=16)
    ttk.Button(btn_row, text="Delete", command=do_delete).pack(side="left")
    ttk.Button(btn_row, text="Save", style="Accent.TButton", command=do_save).pack(side="right")


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

class TransactionsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        form = Card(self, title="Add Transaction")
        form.pack(fill="x", pady=(0, 10))

        ttk.Label(form, text="Date (YYYY-MM-DD)", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        self.date_var = tk.StringVar(value=self.app.today.isoformat())
        ttk.Entry(form, textvariable=self.date_var, width=14).grid(row=1, column=0, padx=4)

        ttk.Label(form, text="Payee", style="CardDim.TLabel").grid(row=0, column=1, sticky="w")
        self.payee_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.payee_var, width=18).grid(row=1, column=1, padx=4)

        ttk.Label(form, text="Category", style="CardDim.TLabel").grid(row=0, column=2, sticky="w")
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(form, textvariable=self.category_var, width=18, state="readonly")
        self.category_combo.grid(row=1, column=2, padx=4)

        ttk.Label(form, text="Amount (+income / -expense)", style="CardDim.TLabel").grid(row=0, column=3, sticky="w")
        self.amount_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.amount_var, width=12).grid(row=1, column=3, padx=4)

        ttk.Label(form, text="Currency", style="CardDim.TLabel").grid(row=0, column=4, sticky="w")
        self.currency_var = tk.StringVar(value=self.app.reporting_currency())
        ttk.Entry(form, textvariable=self.currency_var, width=8).grid(row=1, column=4, padx=4)

        ttk.Label(form, text="Note", style="CardDim.TLabel").grid(row=0, column=5, sticky="w")
        self.note_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.note_var, width=20).grid(row=1, column=5, padx=4)

        ttk.Label(form, text="Paid from", style="CardDim.TLabel").grid(row=0, column=6, sticky="w")
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(form, textvariable=self.account_var, width=16, state="readonly")
        self.account_combo.grid(row=1, column=6, padx=4)

        ttk.Button(form, text="Add", style="Good.TButton", command=self.add_transaction).grid(
            row=1, column=7, padx=8)

        ttk.Label(form, text="Tags (comma-separated)", style="CardDim.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.tags_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.tags_var, width=40).grid(
            row=3, column=0, columnspan=3, sticky="w")

        self.life_energy_label = ttk.Label(form, text="", style="CardDim.TLabel")
        self.life_energy_label.grid(row=4, column=0, columnspan=8, sticky="w", pady=(8, 0))
        self.rewards_preview_label = ttk.Label(form, text="", style="Good.TLabel")
        self.rewards_preview_label.grid(row=5, column=0, columnspan=8, sticky="w")
        self.amount_var.trace_add("write", lambda *a: self._update_previews())
        self.account_var.trace_add("write", lambda *a: self._update_previews())
        self.amount_var.trace_add("write", lambda *a: self._update_category_choices())

        list_card = Card(self, title="History")
        list_card.pack(fill="both", expand=True)

        toolbar = ttk.Frame(list_card, style="Card.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Search", style="CardDim.TLabel").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=24)
        search_entry.pack(side="left", padx=6)
        self.search_var.trace_add("write", lambda *a: self.refresh())
        ttk.Button(toolbar, text="Delete Selected", command=self.delete_selected).pack(side="right")
        ttk.Button(toolbar, text="Split Selected…", command=self.split_selected).pack(side="right", padx=6)
        ttk.Button(toolbar, text="Mark as Owed…", command=self.mark_as_owed).pack(side="right", padx=6)
        ttk.Button(toolbar, text="Edit Selected…", command=self.edit_selected).pack(side="right", padx=6)
        ttk.Button(toolbar, text="Reconcile", command=lambda: self._set_reconciled(True)).pack(
            side="right", padx=6)
        ttk.Button(toolbar, text="Unreconcile", command=lambda: self._set_reconciled(False)).pack(
            side="right")
        ttk.Button(toolbar, text="Import CSV…", command=self.import_csv).pack(side="right", padx=6)
        ttk.Button(toolbar, text="Export CSV…", command=self.app.export_csv).pack(side="right", padx=6)
        ttk.Button(toolbar, text="Export Full CSV…", command=self.app.export_csv_full).pack(
            side="right", padx=6)

        filter_bar = ttk.Frame(list_card, style="Card.TFrame")
        filter_bar.pack(fill="x", pady=(0, 8))

        ttk.Label(filter_bar, text="Account", style="CardDim.TLabel").pack(side="left")
        self.filter_account_var = tk.StringVar()
        self.filter_account_combo = ttk.Combobox(filter_bar, textvariable=self.filter_account_var,
                                                  width=14, state="readonly")
        self.filter_account_combo.pack(side="left", padx=(4, 12))
        self.filter_account_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Category", style="CardDim.TLabel").pack(side="left")
        self.filter_category_var = tk.StringVar()
        self.filter_category_combo = ttk.Combobox(filter_bar, textvariable=self.filter_category_var,
                                                   width=14, state="readonly")
        self.filter_category_combo.pack(side="left", padx=(4, 12))
        self.filter_category_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Currency", style="CardDim.TLabel").pack(side="left")
        self.filter_currency_var = tk.StringVar()
        self.filter_currency_combo = ttk.Combobox(filter_bar, textvariable=self.filter_currency_var,
                                                   width=8, state="readonly")
        self.filter_currency_combo.pack(side="left", padx=(4, 12))
        self.filter_currency_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Date from", style="CardDim.TLabel").pack(side="left")
        self.filter_date_from_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_date_from_var, width=10).pack(
            side="left", padx=(4, 6))
        ttk.Label(filter_bar, text="to", style="CardDim.TLabel").pack(side="left")
        self.filter_date_to_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_date_to_var, width=10).pack(
            side="left", padx=(4, 12))
        self.filter_date_from_var.trace_add("write", lambda *a: self.refresh())
        self.filter_date_to_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(filter_bar, text="Amount min", style="CardDim.TLabel").pack(side="left")
        self.filter_amount_min_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_amount_min_var, width=8).pack(
            side="left", padx=(4, 6))
        ttk.Label(filter_bar, text="max", style="CardDim.TLabel").pack(side="left")
        self.filter_amount_max_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_amount_max_var, width=8).pack(
            side="left", padx=(4, 12))
        self.filter_amount_min_var.trace_add("write", lambda *a: self.refresh())
        self.filter_amount_max_var.trace_add("write", lambda *a: self.refresh())

        ttk.Button(filter_bar, text="Clear Filters", command=self.clear_filters).pack(side="left")

        list_frame = ttk.Frame(list_card, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True)

        cols = ("date", "payee", "category", "amount", "currency", "reporting", "account", "note",
                "tags", "reconciled")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=16)
        headers = {"date": "Date", "payee": "Payee", "category": "Category",
                   "amount": "Amount", "currency": "Ccy", "reporting": "In reporting ccy",
                   "account": "Paid from", "note": "Note", "tags": "Tags", "reconciled": "Reconciled"}
        widths = {"date": 90, "payee": 140, "category": 120, "amount": 90,
                  "currency": 50, "reporting": 130, "account": 110, "note": 140,
                  "tags": 130, "reconciled": 80}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        reimb_card = Card(self, title="Outstanding Reimbursements")
        reimb_card.pack(fill="x", pady=(10, 0))
        self.reimb_rows_frame = ttk.Frame(reimb_card, style="Card.TFrame")
        self.reimb_rows_frame.pack(fill="x")

    def clear_filters(self):
        self.filter_account_var.set("")
        self.filter_category_var.set("")
        self.filter_currency_var.set("")
        self.filter_date_from_var.set("")
        self.filter_date_to_var.set("")
        self.filter_amount_min_var.set("")
        self.filter_amount_max_var.set("")

    def mark_as_owed(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Mark as Owed", "Select a transaction first.")
            return
        if len(sel) > 1:
            messagebox.showinfo("Mark as Owed", "Select just one transaction.")
            return
        tx_id = int(sel[0])
        tx = self.app.db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not tx:
            return

        win, content = make_scrollable_toplevel(self, "Mark as Owed", "380x300")

        ttk.Label(content, text=f"{tx['payee'] or '(no payee)'} — {fmt_money(tx['amount'], tx['currency'])}",
                  style="H2.TLabel", wraplength=280, justify="left").pack(anchor="w", padx=12, pady=(12, 8))

        ttk.Label(content, text="Owed by", style="TLabel").pack(anchor="w", padx=12)
        owed_by_var = tk.StringVar()
        ttk.Entry(content, textvariable=owed_by_var).pack(fill="x", padx=12)

        ttk.Label(content, text="Amount owed", style="TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        amount_var = tk.StringVar(value=f"{abs(tx['amount']):.2f}")
        ttk.Entry(content, textvariable=amount_var).pack(fill="x", padx=12)

        ttk.Label(content, text="Note", style="TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        note_var = tk.StringVar()
        ttk.Entry(content, textvariable=note_var).pack(fill="x", padx=12)

        def do_save():
            owed_by = owed_by_var.get().strip()
            if not owed_by:
                messagebox.showerror("Name needed", "Enter who owes this.")
                return
            try:
                amount = float(amount_var.get())
            except ValueError:
                messagebox.showerror("Invalid amount", "Amount must be a number.")
                return
            self.app.db.add_reimbursement(tx_id, owed_by, amount, note=note_var.get().strip())
            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Save", style="Accent.TButton", command=do_save).pack(pady=14)

    def _refresh_reimbursements(self):
        for w in self.reimb_rows_frame.winfo_children():
            w.destroy()
        outstanding = self.app.db.list_outstanding_reimbursements()
        cur = self.app.reporting_currency()
        if not outstanding:
            ttk.Label(self.reimb_rows_frame, text="Nothing outstanding.",
                      style="CardDim.TLabel").pack(anchor="w")
            return
        for r in outstanding:
            row = ttk.Frame(self.reimb_rows_frame, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            text = (f"{r['owed_by']} owes {fmt_money(r['amount'], cur)} — "
                    f"{r['payee'] or '(no payee)'} on {r['transaction_date']}")
            if r["note"]:
                text += f"  ({r['note']})"
            ttk.Label(row, text=text, style="Card.TLabel").pack(side="left")
            ttk.Button(row, text="Mark Settled",
                       command=lambda rid=r["id"]: self._settle(rid)).pack(side="right")

    def _settle(self, reimbursement_id):
        self.app.db.settle_reimbursement(reimbursement_id)
        self.app.refresh_all()

    def _update_previews(self):
        wage = self.app.db.get_setting_float("hourly_wage", 0.0)
        try:
            raw_amt = float(self.amount_var.get())
        except ValueError:
            self.life_energy_label.config(text="")
            self.rewards_preview_label.config(text="")
            return
        amt = abs(raw_amt)
        hours = life_energy_hours(amt, wage)
        self.life_energy_label.config(
            text="" if hours is None else
            f"≈ {hours:,.1f} hours of work at your set hourly wage of {wage:,.2f}")

        preview_bits = []
        if raw_amt < 0:
            acc = self.accounts_by_name.get(self.account_var.get().strip())
            if acc and acc["subtype"] == "credit_card" and (acc["cashback_rate"] or 0) > 0:
                cashback = amt * acc["cashback_rate"] / 100.0
                preview_bits.append(f"+{fmt_money(cashback, self.app.reporting_currency())} cashback")
            if self.app.db.get_setting("roundup_enabled", "0") == "1":
                nearest = self.app.db.get_setting_float("roundup_nearest", 1.0) or 1.0
                multiplier = self.app.db.get_setting_float("roundup_multiplier", 1.0) or 1.0
                remainder = amt % nearest
                if remainder > 1e-9:
                    roundup = (nearest - remainder) * multiplier
                    preview_bits.append(f"+{fmt_money(roundup, self.app.reporting_currency())} round-up")
        self.rewards_preview_label.config(text="  ·  ".join(preview_bits))

    def _update_category_choices(self, *_):
        """Filters the Add-transaction Category dropdown to income categories
        when the typed amount is positive, and to need/want/saving categories
        otherwise -- so a paycheck can't accidentally get filed as an expense
        category or vice versa. Leaves the full list shown while the amount
        field is blank/unparseable (sign not yet known)."""
        cats = getattr(self, "_categories", None)
        if not cats:
            return
        amount_raw = self.amount_var.get().strip()
        try:
            amount = float(amount_raw)
        except ValueError:
            names = [c["name"] for c in cats]
        else:
            if amount > 0:
                names = [c["name"] for c in cats if c["kind"] == "income"]
            else:
                names = [c["name"] for c in cats if c["kind"] != "income"]
        self.category_combo["values"] = names
        if self.category_var.get() not in names:
            self.category_var.set("")

    def refresh(self):
        cats = self.app.db.list_categories()
        self._categories = cats
        self.categories_by_name = {c["name"]: c["id"] for c in cats}
        self._update_category_choices()

        accs = [a for a in self.app.db.list_accounts() if a["subtype"] != "roundup_pot"]
        self.accounts_by_name = {a["name"]: a for a in accs}
        self.account_combo["values"] = [""] + list(self.accounts_by_name.keys())

        self.filter_account_combo["values"] = [""] + list(self.accounts_by_name.keys())
        self.filter_category_combo["values"] = [""] + list(self.categories_by_name.keys())
        all_txs = self.app.db.list_transactions(limit=100000)
        self.filter_currency_combo["values"] = [""] + sorted({t["currency"] for t in all_txs})

        for row in self.tree.get_children():
            self.tree.delete(row)
        db = self.app.db
        query = self.search_var.get().strip().lower()
        resolved_colors = resolve_category_colors(cats)
        # A subtle blend toward the card background, not the category's
        # full-saturation color -- every row gets a default color now
        # (resolve_category_colors), and a whole list of fully-saturated
        # row backgrounds would be visually overwhelming at 50+ rows.
        cat_color_by_id = {cid: charts.lerp_color(self.app.c["card"], color, 0.18)
                            for cid, color in resolved_colors.items()}
        for t in all_txs:
            # Transfers between the user's own accounts aren't income or
            # spending -- they clutter this list without adding information,
            # and are already visible via the Accounts tab's Transfers list
            # and each account's own ledger.
            if t["is_transfer"]:
                continue
            tags = db.get_transaction_tags(t["id"])
            tags_label = ", ".join(tags)
            haystack = (f"{t['payee'] or ''} {t['category_name'] or ''} {t['note'] or ''} "
                        f"{tags_label}").lower()
            if query and query not in haystack:
                continue
            if self.filter_account_var.get() and t["account_name"] != self.filter_account_var.get():
                continue
            if self.filter_category_var.get() and t["category_name"] != self.filter_category_var.get():
                continue
            if self.filter_currency_var.get() and t["currency"] != self.filter_currency_var.get():
                continue
            date_from = self.filter_date_from_var.get().strip()
            if date_from:
                try:
                    if t["date"] < datetime.date.fromisoformat(date_from).isoformat():
                        continue
                except ValueError:
                    pass
            date_to = self.filter_date_to_var.get().strip()
            if date_to:
                try:
                    if t["date"] > datetime.date.fromisoformat(date_to).isoformat():
                        continue
                except ValueError:
                    pass
            amt_min = self.filter_amount_min_var.get().strip()
            if amt_min:
                try:
                    if t["amount"] < float(amt_min):
                        continue
                except ValueError:
                    pass
            amt_max = self.filter_amount_max_var.get().strip()
            if amt_max:
                try:
                    if t["amount"] > float(amt_max):
                        continue
                except ValueError:
                    pass
            reporting_amt = db.to_reporting(t["amount"], t["currency"])
            splits = db.get_transaction_splits(t["id"])
            category_label = f"⑃ split ({len(splits)})" if splits else (t["category_name"] or "(none)")
            row_tags = ()
            cat_color = cat_color_by_id.get(t["category_id"])
            if cat_color:
                row_tag = f"catcolor_{t['category_id']}"
                self.tree.tag_configure(row_tag, background=cat_color)
                row_tags = (row_tag,)
            self.tree.insert("", "end", iid=str(t["id"]), values=(
                t["date"], t["payee"] or "", category_label,
                f"{t['amount']:,.2f}", t["currency"],
                f"{reporting_amt:,.2f}", t["account_name"] or "", t["note"] or "",
                tags_label, "🔒" if t["reconciled"] else ""
            ), tags=row_tags)

        self._refresh_reimbursements()

    def add_transaction(self):
        ok, error = submit_new_transaction(
            self.app, self.date_var.get(), self.payee_var.get(), self.category_var.get(),
            self.amount_var.get(), self.currency_var.get(), self.note_var.get(),
            self.account_var.get(), self.tags_var.get())
        if not ok:
            if error:
                messagebox.showerror("Invalid entry", error)
            return
        self.payee_var.set("")
        self.amount_var.set("")
        self.note_var.set("")
        self.tags_var.set("")
        self.app.refresh_all()

    def edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        if len(sel) > 1:
            messagebox.showinfo("Edit", "Select just one transaction to edit.")
            return
        open_transaction_edit_dialog(self, self.app, int(sel[0]), on_saved=self.app.refresh_all)

    def split_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        if len(sel) > 1:
            messagebox.showinfo("Split", "Select just one transaction to split.")
            return
        self._open_split_dialog(int(sel[0]))

    def _open_split_dialog(self, tx_id):
        db = self.app.db
        tx = db.conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
        if not tx:
            return
        if tx["is_transfer"]:
            messagebox.showinfo("Split", "Transfer legs can't be split.")
            return

        cat_names = [c["name"] for c in db.list_categories()]
        cats_by_name = {c["name"]: c["id"] for c in db.list_categories()}
        cats_by_id = {c["id"]: c["name"] for c in db.list_categories()}

        win, content = make_scrollable_toplevel(self, f"Split — {tx['payee'] or '(no payee)'}", "560x460")

        ttk.Label(content, text=f"Total: {fmt_money(tx['amount'], tx['currency'])} — splits must add up "
                             "to exactly this (money moved doesn't change, only how it's categorized).",
                  style="H2.TLabel", wraplength=480, justify="left").pack(anchor="w", padx=10, pady=(10, 6))

        rows_frame = ttk.Frame(content)
        rows_frame.pack(fill="both", expand=True, padx=10)
        row_vars = []

        def add_row(category_name="", amount=""):
            row = ttk.Frame(rows_frame)
            row.pack(fill="x", pady=2)
            cat_var = tk.StringVar(value=category_name)
            amt_var = tk.StringVar(value=amount)
            note_var = tk.StringVar()
            ttk.Combobox(row, textvariable=cat_var, values=cat_names, width=18,
                         state="readonly").pack(side="left", padx=2)
            ttk.Entry(row, textvariable=amt_var, width=10).pack(side="left", padx=2)
            ttk.Entry(row, textvariable=note_var, width=14).pack(side="left", padx=2)
            entry = {"frame": row, "cat_var": cat_var, "amt_var": amt_var, "note_var": note_var}

            def remove():
                row.destroy()
                row_vars.remove(entry)
            ttk.Button(row, text="✕", width=3, command=remove).pack(side="left", padx=2)
            row_vars.append(entry)

        existing = db.get_transaction_splits(tx_id)
        if existing:
            for s in existing:
                add_row(cats_by_id.get(s["category_id"], ""), str(s["amount"]))
        else:
            add_row(cats_by_id.get(tx["category_id"], ""), str(tx["amount"]))

        ttk.Button(content, text="+ Add Row", command=lambda: add_row()).pack(anchor="w", padx=10, pady=(6, 0))

        btns = ttk.Frame(content)
        btns.pack(fill="x", padx=10, pady=10)

        def do_save():
            splits = []
            for entry in row_vars:
                cat_id = cats_by_name.get(entry["cat_var"].get().strip())
                try:
                    amt = float(entry["amt_var"].get())
                except ValueError:
                    messagebox.showerror("Invalid amount", "Every split needs a numeric amount.")
                    return
                splits.append({"category_id": cat_id, "amount": amt, "note": entry["note_var"].get().strip()})
            try:
                db.set_transaction_splits(tx_id, splits)
            except ValueError as e:
                messagebox.showerror("Doesn't add up", str(e))
                return
            win.destroy()
            self.app.refresh_all()

        def do_clear():
            db.set_transaction_splits(tx_id, [])
            win.destroy()
            self.app.refresh_all()

        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Save Split", style="Accent.TButton", command=do_save).pack(side="right")
        if existing:
            ttk.Button(btns, text="Clear Split", command=do_clear).pack(side="left")

    def delete_selected(self):
        from finance_core import ReconciledTransactionError
        sel = self.tree.selection()
        if not sel:
            return
        blocked = []
        for iid in sel:
            try:
                self.app.db.delete_transaction(int(iid))
            except ReconciledTransactionError:
                blocked.append(iid)
        if blocked:
            messagebox.showinfo(
                "Reconciled transaction",
                f"{len(blocked)} selected transaction(s) are reconciled/locked and were not deleted. "
                "Unreconcile them first if you need to change or remove them.")
        self.app.refresh_all()

    def _set_reconciled(self, flag: bool):
        sel = self.tree.selection()
        if not sel:
            return
        ids = [int(iid) for iid in sel]
        if flag:
            self.app.db.reconcile_many(ids)
        else:
            for tid in ids:
                self.app.db.unreconcile_transaction(tid)
        self.app.refresh_all()

    def import_csv(self):
        """Stages a CSV file for preview/validation, shows a review dialog,
        then commits only the rows the user confirms — nothing touches
        `transactions` until the user clicks Commit."""
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        from finance_core import csv_import_preview, csv_import_commit, csv_import_discard

        account = self.accounts_by_name.get(self.account_var.get().strip())
        try:
            batch_id, rows = csv_import_preview(
                self.app.db, path, account_id=account["id"] if account else None)
        except Exception as e:
            messagebox.showerror("Import failed", f"Couldn't read that CSV: {e}")
            return

        win, content = make_scrollable_toplevel(self, "Import preview", "800x520")

        n_ok = sum(1 for r in rows if r["parsed_ok"])
        n_bad = len(rows) - n_ok
        n_dup = sum(1 for r in rows if r["likely_duplicate"])
        ttk.Label(content, text=f"{len(rows)} rows found — {n_ok} look valid, {n_bad} have problems, "
                             f"{n_dup} look like duplicates of transactions you already have.",
                  style="H2.TLabel").pack(anchor="w", padx=10, pady=(10, 4))
        if n_dup:
            ttk.Label(content, wraplength=740, justify="left", style="Dim.TLabel",
                      text="Likely-duplicate rows are pre-selected below and will be skipped on Commit. "
                           "Click a row to un-select it if it's a genuine second charge (e.g. two identical "
                           "coffees the same day) rather than an actual duplicate."
                      ).pack(anchor="w", padx=10, pady=(0, 4))

        cols = ("row", "date", "payee", "amount", "status", "dup")
        tree_frame = ttk.Frame(content)
        tree_frame.pack(fill="both", expand=True, padx=10)
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=14, selectmode="extended")
        for col, w, title in zip(cols, (45, 90, 190, 90, 200, 110),
                                  ("Row", "Date", "Payee", "Amount", "Status", "Duplicate?")):
            tree.heading(col, text=title)
            tree.column(col, width=w, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree_scroll.pack(side="right", fill="y")
        tree.configure(yscrollcommand=tree_scroll.set)
        dup_ids = []
        for r in rows:
            status = "OK" if r["parsed_ok"] else f"ERROR: {r['error']}"
            dup_text = "⚠ possible duplicate" if r["likely_duplicate"] else ""
            tree.insert("", "end", iid=str(r["id"]), values=(
                r["row_index"] + 1, r["parsed_date"] or r["raw_date"], r["raw_payee"],
                r["parsed_amount"] if r["parsed_amount"] is not None else r["raw_amount"],
                status, dup_text))
            if r["likely_duplicate"]:
                dup_ids.append(str(r["id"]))
        if dup_ids:
            tree.selection_set(dup_ids)

        btns = ttk.Frame(content)
        btns.pack(fill="x", padx=10, pady=10)

        def do_commit():
            skip_ids = [int(iid) for iid in tree.selection()]
            committed, skipped = csv_import_commit(
                self.app.db, batch_id, only_valid=True, skip_row_ids=skip_ids)
            messagebox.showinfo("Import complete", f"Imported {committed} transaction(s); skipped {skipped}.")
            win.destroy()
            self.app.refresh_all()

        def do_cancel():
            csv_import_discard(self.app.db, batch_id)
            win.destroy()

        ttk.Button(btns, text="Cancel", command=do_cancel).pack(side="right", padx=6)
        ttk.Button(btns, text="Commit (skip selected rows)", style="Accent.TButton",
                   command=do_commit).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", do_cancel)


# --------------------------------------------------------------------------
# Budgets (envelopes)
# --------------------------------------------------------------------------

class BudgetsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        ttk.Label(self, text="Category envelopes — 50/30/20 style Need/Want/Saving grouping",
                  style="H2.TLabel", font=theme.Fonts.body_bold).pack(anchor="w", pady=(0, 8))

        add_frame = Card(self, title="Add Category")
        add_frame.pack(fill="x", pady=(0, 8))
        self.new_name = tk.StringVar()
        self.new_kind = tk.StringVar(value="want")
        self.new_budget = tk.StringVar(value="0")
        ttk.Entry(add_frame, textvariable=self.new_name, width=20).grid(row=0, column=0, padx=4)
        ttk.Combobox(add_frame, textvariable=self.new_kind, values=["need", "want", "saving", "income"],
                     width=10, state="readonly").grid(row=0, column=1, padx=4)
        ttk.Entry(add_frame, textvariable=self.new_budget, width=10).grid(row=0, column=2, padx=4)
        ttk.Button(add_frame, text="Add Category", style="Good.TButton",
                   command=self.add_category).grid(row=0, column=3, padx=8)

        self.canvas_frame = ttk.Frame(self)
        self.canvas_frame.pack(fill="both", expand=True)

    def add_category(self):
        name = self.new_name.get().strip()
        kind = self.new_kind.get()
        try:
            budget = float(self.new_budget.get())
        except ValueError:
            budget = 0.0
        if not name:
            return
        try:
            self.app.db.add_category(name, kind, budget)
        except Exception:
            messagebox.showerror("Error", "Category already exists.")
        self.new_name.set("")
        self.new_budget.set("0")
        self.app.refresh_all()

    def refresh(self):
        for w in self.canvas_frame.winfo_children():
            w.destroy()

        db = self.app.db
        c = self.app.c
        y, m = self.app.view_year, self.app.view_month
        cur = self.app.reporting_currency()

        spend_by_cat = {}
        for t in db.transactions_in_month(y, m):
            if t["amount"] < 0 and t["category_id"] is not None:
                spend_by_cat[t["category_id"]] = spend_by_cat.get(t["category_id"], 0.0) - db.to_reporting(
                    t["amount"], t["currency"])

        run_rate_by_cat = {r["category"]["id"]: r for r in budget_run_rate(db, y, m, today=self.app.today)}

        all_cats = db.list_categories()
        resolved_colors = resolve_category_colors(all_cats)
        groups = {"need": [], "want": [], "saving": [], "income": []}
        for cat in all_cats:
            groups[cat["kind"]].append(cat)
        income_totals = {r["category_id"]: r["total"] for r in income_by_category(db, y, m)}

        titles = {"need": "Needs (50%)", "want": "Wants (30%)", "saving": "Savings/Debt (20%)"}
        col = 0
        for kind in ("need", "want", "saving"):
            frame = Card(self.canvas_frame, title=titles[kind])
            frame.grid(row=0, column=col, sticky="nsew", padx=6)
            self.canvas_frame.columnconfigure(col, weight=1)
            col += 1
            drag_rows = []
            for cat in groups[kind]:
                spent = spend_by_cat.get(cat["id"], 0.0)
                budget = cat["monthly_budget"] or 0.0
                row = ttk.Frame(frame, style="Card.TFrame")
                row.pack(fill="x", pady=5)
                header = ttk.Frame(row, style="Card.TFrame")
                header.pack(fill="x", anchor="w")
                handle = ttk.Label(header, text="⠿", style="CardDim.TLabel")
                handle.pack(side="left", padx=(0, 6))
                drag_rows.append((handle, row, cat["id"]))
                swatch = tk.Label(header, width=2, bg=resolved_colors[cat["id"]], cursor="hand2")
                swatch.pack(side="left", padx=(0, 6))
                swatch.bind("<Button-1>", lambda e, cid=cat["id"], cc=cat["color"]:
                            self._pick_category_color(cid, cc))
                label_text = f"{cat['name']}: {fmt_money(spent, cur)}"
                if budget > 0:
                    label_text += f" / {fmt_money(budget, cur)}"
                ttk.Label(header, text=label_text, style="Card.TLabel").pack(side="left")

                bar_bg = tk.Canvas(row, height=10, width=260, bg=c["grid"], highlightthickness=0)
                bar_bg.pack(anchor="w", pady=(3, 0))
                if budget > 0:
                    pct = min(spent / budget, 1.5)
                    fill_w = min(pct, 1.0) * 260
                    color = c["good"] if pct <= 0.8 else (c["warn"] if pct <= 1.0 else c["bad"])
                    charts.rounded_rect(bar_bg, 0, 0, max(fill_w, 4), 10, r=5, fill=color, outline="")
                else:
                    bar_bg.create_text(130, 5, text="no budget set", fill=c["text_faint"],
                                        font=theme.Fonts.small)

                run_rate = run_rate_by_cat.get(cat["id"])
                if budget > 0 and run_rate and run_rate["days_elapsed"] > 0:
                    projected = run_rate["projected"]
                    if run_rate["projected_over"]:
                        ttk.Label(row, text=f"On pace for {fmt_money(projected, cur)} "
                                             f"(over by {fmt_money(projected - budget, cur)})",
                                  style="Bad.TLabel").pack(anchor="w", pady=(2, 0))
                    else:
                        ttk.Label(row, text=f"On pace for {fmt_money(projected, cur)}",
                                  style="CardDim.TLabel").pack(anchor="w", pady=(2, 0))

                edit_row = ttk.Frame(row, style="Card.TFrame")
                edit_row.pack(anchor="w", pady=(4, 0))
                budget_var = tk.StringVar(value=str(budget))
                ttk.Entry(edit_row, textvariable=budget_var, width=8).pack(side="left")
                ttk.Button(edit_row, text="Set Budget",
                           command=lambda cid=cat["id"], v=budget_var: self._set_budget(cid, v)).pack(
                    side="left", padx=4)
                ttk.Button(edit_row, text="Delete",
                           command=lambda cid=cat["id"], name=cat["name"]:
                               self._delete_category(cid, name)).pack(side="left", padx=4)

            if drag_rows:
                enable_drag_reorder(
                    drag_rows, lambda ids, k=kind: self._reorder_categories(k, ids))

        income_frame = Card(self.canvas_frame, title="Income")
        income_frame.grid(row=0, column=col, sticky="nsew", padx=6)
        self.canvas_frame.columnconfigure(col, weight=1)
        if not groups["income"]:
            ttk.Label(income_frame, text="No income categories yet.",
                      style="CardDim.TLabel").pack(anchor="w")
        income_drag_rows = []
        for cat in groups["income"]:
            total = income_totals.get(cat["id"], 0.0)
            row = ttk.Frame(income_frame, style="Card.TFrame")
            row.pack(fill="x", pady=5)
            ttk.Button(row, text="Delete",
                       command=lambda cid=cat["id"], name=cat["name"]:
                           self._delete_category(cid, name)).pack(side="right", padx=6)
            handle = ttk.Label(row, text="⠿", style="CardDim.TLabel")
            handle.pack(side="left", padx=(0, 6))
            income_drag_rows.append((handle, row, cat["id"]))
            swatch = tk.Label(row, width=2, bg=resolved_colors[cat["id"]], cursor="hand2")
            swatch.pack(side="left", padx=(0, 6))
            swatch.bind("<Button-1>", lambda e, cid=cat["id"], cc=cat["color"]:
                        self._pick_category_color(cid, cc))
            ttk.Label(row, text=f"{cat['name']}: {fmt_money(total, cur)}",
                      style="Card.TLabel").pack(side="left")
        if income_drag_rows:
            enable_drag_reorder(
                income_drag_rows, lambda ids: self._reorder_categories("income", ids))

    def _set_budget(self, cat_id, var):
        try:
            val = float(var.get())
        except ValueError:
            return
        self.app.db.set_category_budget(cat_id, val)
        self.app.refresh_all()

    def _reorder_categories(self, kind, ordered_category_ids):
        self.app.db.set_category_order(kind, ordered_category_ids)
        self.app.refresh_all()

    def _pick_category_color(self, cat_id, current_color):
        _, hex_color = colorchooser.askcolor(color=current_color or None, title="Category Color")
        if hex_color:
            self.app.db.update_category(cat_id, color=hex_color)
            self.app.refresh_all()

    def _delete_category(self, cat_id, name):
        if not messagebox.askyesno("Delete Category", f"Delete '{name}'?"):
            return
        try:
            self.app.db.delete_category(cat_id)
        except ValueError as e:
            messagebox.showerror("Cannot Delete", str(e))
            return
        self.app.refresh_all()


# --------------------------------------------------------------------------
# Recurring (bills / paychecks)
# --------------------------------------------------------------------------

class RecurringTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        self.detected_card = Card(self, title="Detected Subscriptions (not yet tracked)")
        self.detected_card.pack(fill="x", pady=(0, 10))
        self.detected_rows_frame = ttk.Frame(self.detected_card, style="Card.TFrame")
        self.detected_rows_frame.pack(fill="x")

        form = Card(self, title="Add Recurring Item (bill, paycheck, or a one-off you know is coming)")
        form.pack(fill="x", pady=(0, 10))

        self.name_var = tk.StringVar()
        self.payee_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.amount_var = tk.StringVar()
        self.currency_var = tk.StringVar(value=self.app.reporting_currency())
        self.freq_var = tk.StringVar(value="monthly")
        self.next_date_var = tk.StringVar(value=self.app.today.isoformat())
        self.custom_interval_var = tk.StringVar(value="4")

        labels = ["Name", "Payee", "Category", "Amount (+/-)", "Currency", "Frequency", "Next Date", "Account"]
        for i, lbl in enumerate(labels):
            ttk.Label(form, text=lbl, style="CardDim.TLabel").grid(row=0, column=i, sticky="w", padx=3)

        ttk.Entry(form, textvariable=self.name_var, width=16).grid(row=1, column=0, padx=3)
        ttk.Entry(form, textvariable=self.payee_var, width=14).grid(row=1, column=1, padx=3)
        self.category_combo = ttk.Combobox(form, textvariable=self.category_var, width=14, state="readonly")
        self.category_combo.grid(row=1, column=2, padx=3)
        ttk.Entry(form, textvariable=self.amount_var, width=10).grid(row=1, column=3, padx=3)
        ttk.Entry(form, textvariable=self.currency_var, width=6).grid(row=1, column=4, padx=3)
        freq_combo = ttk.Combobox(form, textvariable=self.freq_var,
                                   values=["weekly", "monthly", "yearly", "custom", "once"],
                                   width=10, state="readonly")
        freq_combo.grid(row=1, column=5, padx=3)
        ttk.Entry(form, textvariable=self.next_date_var, width=12).grid(row=1, column=6, padx=3)
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(form, textvariable=self.account_var, width=14, state="readonly")
        self.account_combo.grid(row=1, column=7, padx=3)
        ttk.Button(form, text="Add", style="Good.TButton", command=self.add_recurring).grid(
            row=1, column=8, padx=8)

        self.custom_interval_frame = ttk.Frame(form, style="Card.TFrame")
        self.custom_interval_frame.grid(row=2, column=0, columnspan=9, sticky="w", pady=(6, 0))
        ttk.Label(self.custom_interval_frame, text="Every how many months (e.g. 4 = 3x/year)",
                  style="CardDim.TLabel").pack(side="left")
        ttk.Entry(self.custom_interval_frame, textvariable=self.custom_interval_var, width=6).pack(
            side="left", padx=6)
        self.custom_interval_frame.grid_remove()

        self.once_hint_label = ttk.Label(
            form, text="Posts on Next Date, then deactivates itself — for a known one-off "
                       "you don't want to forget, not a repeating bill.",
            style="CardDim.TLabel", wraplength=700, justify="left")
        self.once_hint_label.grid(row=2, column=0, columnspan=9, sticky="w", pady=(6, 0))
        self.once_hint_label.grid_remove()

        self.freq_var.trace_add("write", lambda *a: self._update_custom_interval_visibility())

        list_card = Card(self, title="All Recurring Items")
        list_card.pack(fill="both", expand=True, pady=(0, 10))
        cols = ("name", "payee", "category", "amount", "currency", "frequency", "next_date", "account", "active")
        tree_frame = ttk.Frame(list_card, style="Card.TFrame")
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=14)
        headers = {"name": "Name", "payee": "Payee", "category": "Category", "amount": "Amount",
                   "currency": "Ccy", "frequency": "Frequency", "next_date": "Next Date",
                   "account": "Account", "active": "Active"}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=110, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Toggle Active", command=self.toggle_active).pack(side="left")
        ttk.Button(btn_row, text="Delete Selected", command=self.delete_selected).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Post Anything Due Now", style="Accent.TButton",
                   command=self.post_due).pack(side="left", padx=6)

        self.upcoming_card = Card(self, title="Coming Up (next 14 days)")
        self.upcoming_card.pack(fill="x", pady=(10, 0))
        self.upcoming_label = ttk.Label(self.upcoming_card, text="", style="Card.TLabel", justify="left")
        self.upcoming_label.pack(anchor="w")

    def _update_custom_interval_visibility(self):
        if self.freq_var.get() == "custom":
            self.custom_interval_frame.grid()
        else:
            self.custom_interval_frame.grid_remove()
        if self.freq_var.get() == "once":
            self.once_hint_label.grid()
        else:
            self.once_hint_label.grid_remove()

    def add_recurring(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Name needed", "Give this recurring item a name.")
            return
        try:
            amount = float(self.amount_var.get())
        except ValueError:
            messagebox.showerror("Invalid amount", "Amount must be a number (negative for bills).")
            return
        try:
            datetime.date.fromisoformat(self.next_date_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid date", "Next date must be YYYY-MM-DD.")
            return
        custom_interval_months = None
        if self.freq_var.get() == "custom":
            try:
                custom_interval_months = int(self.custom_interval_var.get())
                if custom_interval_months < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Invalid interval", "Enter a whole number of months (1 or more).")
                return
        cats = {c["name"]: c["id"] for c in self.app.db.list_categories()}
        cat_id = cats.get(self.category_var.get().strip())
        currency = self.currency_var.get().strip().upper() or self.app.reporting_currency()
        accounts = {a["name"]: a["id"] for a in self.app.db.list_accounts() if a["subtype"] != "roundup_pot"}
        account_id = accounts.get(self.account_var.get().strip())
        self.app.db.add_recurring(name, self.payee_var.get().strip() or None, cat_id, amount,
                                   currency, self.freq_var.get(), self.next_date_var.get().strip(),
                                   account_id=account_id, custom_interval_months=custom_interval_months)
        self.name_var.set("")
        self.payee_var.set("")
        self.amount_var.set("")
        self.app.refresh_all()

    def toggle_active(self):
        sel = self.tree.selection()
        for iid in sel:
            r = next((x for x in self.app.db.list_recurring() if x["id"] == int(iid)), None)
            if r:
                self.app.db.set_recurring_active(r["id"], not r["active"])
        self.app.refresh_all()

    def delete_selected(self):
        for iid in self.tree.selection():
            self.app.db.delete_recurring(int(iid))
        self.app.refresh_all()

    def post_due(self):
        posted = self.app.db.generate_due_recurring(self.app.today)
        if posted:
            messagebox.showinfo("Posted", f"Posted {len(posted)} due item(s).")
        else:
            messagebox.showinfo("Nothing due", "Nothing is due yet.")
        self.app.refresh_all()

    def refresh(self):
        cats = self.app.db.list_categories()
        self.category_combo["values"] = [c["name"] for c in cats]
        accounts = [a for a in self.app.db.list_accounts() if a["subtype"] != "roundup_pot"]
        self.account_combo["values"] = [""] + [a["name"] for a in accounts]

        for row in self.tree.get_children():
            self.tree.delete(row)
        for r in self.app.db.list_recurring():
            freq_text = r["frequency"]
            if r["frequency"] == "custom" and r["custom_interval_months"]:
                freq_text = f"every {r['custom_interval_months']} mo"
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["name"], r["payee"] or "", r["category_name"] or "(none)",
                f"{r['amount']:,.2f}", r["currency"], freq_text, r["next_date"],
                r["account_name"] or "", "yes" if r["active"] else "no"))

        cur = self.app.reporting_currency()
        bills = upcoming_bills(self.app.db, within_days=14, today=self.app.today)
        if bills:
            text = "\n".join(f"• {b['name']} — {fmt_money(b['amount'], cur)} on {b['next_date']}"
                              for b in bills)
        else:
            text = "Nothing due in the next 14 days."
        self.upcoming_label.config(text=text)

        for w in self.detected_rows_frame.winfo_children():
            w.destroy()
        candidates = detect_recurring_candidates(self.app.db)
        if not candidates:
            ttk.Label(self.detected_rows_frame,
                      text="None detected — no undeclared payee is repeating on a regular schedule yet.",
                      style="CardDim.TLabel").pack(anchor="w")
        else:
            for cand in candidates[:8]:
                row = ttk.Frame(self.detected_rows_frame, style="Card.TFrame")
                row.pack(fill="x", pady=2)
                text = (f"{cand['payee']} — {fmt_money(cand['last_amount'], cand['last_currency'])} "
                        f"every ~{cand['avg_interval_days']:.0f} days ({cand['occurrences']}x seen)")
                if cand["price_changed"]:
                    text += (f"  ⚠ changed from "
                             f"{fmt_money(cand['previous_amount'], cand['last_currency'])}")
                ttk.Label(row, text=text, style="Card.TLabel").pack(side="left")
                ttk.Button(row, text="Add to Recurring",
                           command=lambda c=cand: self._prefill_from_candidate(c)).pack(side="right")
                ttk.Button(row, text="Ignore",
                           command=lambda c=cand: self._ignore_candidate(c)).pack(side="right", padx=6)

    def _nearest_frequency(self, avg_days):
        if avg_days <= 10:
            return "weekly"
        if avg_days >= 300:
            return "yearly"
        return "monthly"

    def _prefill_from_candidate(self, cand):
        self.name_var.set(cand["payee"])
        self.payee_var.set(cand["payee"])
        self.amount_var.set(str(cand["last_amount"]))
        self.currency_var.set(cand["last_currency"])
        self.freq_var.set(self._nearest_frequency(cand["avg_interval_days"]))
        next_date = (datetime.date.fromisoformat(cand["last_date"]) +
                     datetime.timedelta(days=round(cand["avg_interval_days"])))
        self.next_date_var.set(next_date.isoformat())

    def _ignore_candidate(self, cand):
        self.app.db.add_ignored_subscription(cand["payee"])
        self.refresh()


# --------------------------------------------------------------------------
# Debt Planner
# --------------------------------------------------------------------------

class DebtPlannerTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        form = Card(self, title="Add Debt")
        form.pack(fill="x", pady=(0, 10))
        self.name_var = tk.StringVar()
        self.balance_var = tk.StringVar()
        self.apr_var = tk.StringVar()
        self.min_pay_var = tk.StringVar()
        self.custom_pay_var = tk.StringVar()
        for i, (label, var) in enumerate([
            ("Name", self.name_var), ("Balance", self.balance_var),
            ("APR %", self.apr_var), ("Min Payment", self.min_pay_var),
            ("Planned Payment (optional)", self.custom_pay_var),
        ]):
            ttk.Label(form, text=label, style="CardDim.TLabel").grid(row=0, column=i, sticky="w")
            ttk.Entry(form, textvariable=var, width=14).grid(row=1, column=i, padx=4)
        ttk.Button(form, text="Add Debt", style="Good.TButton", command=self.add_debt).grid(
            row=1, column=5, padx=8)

        list_card = Card(self, title="Debts")
        list_card.pack(fill="x", pady=(0, 10))
        cols = ("name", "balance", "apr", "min_payment", "custom_payment")
        tree_frame = ttk.Frame(list_card, style="Card.TFrame")
        tree_frame.pack(fill="x", expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=12)
        for c, label in zip(cols, ["Name", "Balance", "APR %", "Min Payment", "Planned Payment"]):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=140)
        self.tree.pack(side="left", fill="x", expand=True)
        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scroll.set)
        btns = ttk.Frame(list_card, style="Card.TFrame")
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Delete Selected Debt", command=self.delete_selected).pack(side="left")
        ttk.Button(btns, text="Import / Sync Credit Card Balances",
                   command=self.import_from_cards).pack(side="left", padx=6)

        sim_frame = Card(self, title="Payoff Simulation")
        sim_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(sim_frame, text="Extra monthly payment (beyond minimums)",
                  style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        self.extra_var = tk.StringVar(value="0")
        ttk.Entry(sim_frame, textvariable=self.extra_var, width=10).grid(row=0, column=1, padx=6)
        ttk.Button(sim_frame, text="Run Comparison", style="Accent.TButton",
                   command=self.run_simulation).grid(row=0, column=2, padx=8)

        result_card = Card(self, title="Result")
        result_card.pack(fill="both", expand=True)
        c = self.app.c
        self.result_text = tk.Text(result_card, wrap="word", state="disabled", height=12,
                                    bg=c["card"], fg=c["text"], relief="flat", font=theme.Fonts.body)
        self.result_text.pack(fill="both", expand=True)

    def add_debt(self):
        try:
            balance = float(self.balance_var.get())
            apr = float(self.apr_var.get())
            min_pay = float(self.min_pay_var.get())
            custom_pay = float(self.custom_pay_var.get()) if self.custom_pay_var.get().strip() else 0.0
        except ValueError:
            messagebox.showerror("Error", "Balance, APR, Min Payment, and Planned Payment must be numbers.")
            return
        name = self.name_var.get().strip() or "Unnamed debt"
        try:
            self.app.db.add_debt(name, balance, apr, min_pay, custom_payment=custom_pay)
        except ValueError as e:
            messagebox.showerror("Invalid payment plan", str(e))
            return
        self.name_var.set("")
        self.balance_var.set("")
        self.apr_var.set("")
        self.min_pay_var.set("")
        self.custom_pay_var.set("")
        self.app.refresh_all()

    def delete_selected(self):
        for iid in self.tree.selection():
            self.app.db.delete_debt(int(iid))
        self.app.refresh_all()

    def import_from_cards(self):
        db = self.app.db
        cards = [a for a in db.list_accounts() if a["subtype"] == "credit_card"]
        if not cards:
            messagebox.showinfo("No credit cards", "Add a credit card account on the Net Worth tab first.")
            return
        existing = {d["name"]: d for d in db.list_debts()}
        added, updated = 0, 0
        for card in cards:
            bal = db.to_reporting(card["balance"], card["currency"])
            if card["name"] in existing:
                db.update_debt_balance(existing[card["name"]]["id"], bal)
                updated += 1
            else:
                db.add_debt(card["name"], bal, 0.0, 0.0, self.app.reporting_currency())
                added += 1
        self.app.refresh_all()
        messagebox.showinfo(
            "Synced",
            f"{added} card(s) added, {updated} existing balance(s) updated.\n\n"
            "Card balances came across, but APR and minimum payment don't live on the "
            "account itself — set those on each imported debt for an accurate payoff simulation.")

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for d in self.app.db.list_debts():
            self.tree.insert("", "end", iid=str(d["id"]), values=(
                d["name"], f"{d['balance']:,.2f}", f"{d['apr']:.2f}", f"{d['min_payment']:,.2f}",
                f"{d['custom_payment']:,.2f}" if d["custom_payment"] else "—"))

    def run_simulation(self):
        debts = [dict(d) for d in self.app.db.list_debts()]
        if not debts:
            messagebox.showinfo("No debts", "Add at least one debt first.")
            return
        try:
            extra = float(self.extra_var.get())
        except ValueError:
            extra = 0.0

        cur = self.app.reporting_currency()
        try:
            _, avalanche_interest, avalanche_months = simulate_payoff(debts, extra, "avalanche")
            _, snowball_interest, snowball_months = simulate_payoff(debts, extra, "snowball")
        except ValueError as e:
            messagebox.showerror("Invalid payoff plan", str(e))
            return

        lines = [
            "AVALANCHE (highest interest rate first — mathematically optimal):",
            f"  Payoff time: {avalanche_months} months",
            f"  Total interest paid: {fmt_money(avalanche_interest, cur)}",
            "",
            "SNOWBALL (smallest balance first — behaviorally powerful, popularized by Dave Ramsey):",
            f"  Payoff time: {snowball_months} months",
            f"  Total interest paid: {fmt_money(snowball_interest, cur)}",
            "",
        ]
        diff = snowball_interest - avalanche_interest
        if diff > 1:
            lines.append(f"Avalanche saves {fmt_money(diff, cur)} in interest vs. snowball.")
        elif diff < -1:
            lines.append(f"Snowball happens to cost {fmt_money(-diff, cur)} less here (unusual, check your numbers).")
        else:
            lines.append("The two methods land within a dollar of each other here — pick whichever "
                          "you're more likely to stick with. Research (Journal of Consumer Research) "
                          "finds snowball participants are more likely to fully pay off debt due to "
                          "the motivational effect of quick wins.")
        lines.append("")
        lines.append("Reminder from the research (Dave Ramsey's Baby Steps): build a small ~$1,000-equivalent "
                      "starter emergency fund BEFORE aggressive debt payoff, so one surprise expense doesn't "
                      "force new borrowing.")

        self.result_text.config(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "\n".join(lines))
        self.result_text.config(state="disabled")


# --------------------------------------------------------------------------
# Net Worth / FI
# --------------------------------------------------------------------------

ACCOUNT_TYPE_OPTIONS = [
    ("Cash / Bank", "cash", "asset"),
    ("Savings", "savings", "asset"),
    ("Emergency Fund", "emergency_fund", "asset"),
    ("Credit Card", "credit_card", "liability"),
    ("Loan", "loan", "liability"),
    ("Other Asset", "other", "asset"),
    ("Other Liability", "other", "liability"),
]
ACCOUNT_TYPE_LABELS = [label for label, _, _ in ACCOUNT_TYPE_OPTIONS]
ACCOUNT_TYPE_BY_LABEL = {label: (subtype, kind) for label, subtype, kind in ACCOUNT_TYPE_OPTIONS}
# Keyed by (subtype, kind), not subtype alone -- "Other Asset" and "Other
# Liability" both use subtype="other" and would otherwise collide, always
# showing whichever option happened to be listed last ("Other Liability").
ACCOUNT_TYPE_BY_SUBTYPE_KIND = {(subtype, kind): label for label, subtype, kind in ACCOUNT_TYPE_OPTIONS}


class AccountsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        form = Card(self, title="Add Account")
        form.pack(fill="x", pady=(0, 10))
        self.acc_name = tk.StringVar()
        self.acc_type = tk.StringVar(value="Cash / Bank")
        self.acc_balance = tk.StringVar()
        self.acc_currency = tk.StringVar(value=self.app.reporting_currency())
        self.acc_liquid = tk.BooleanVar(value=False)
        self.acc_credit_limit = tk.StringVar(value="0")
        self.acc_cashback_rate = tk.StringVar(value="0")
        self.acc_cashback_cap = tk.StringVar(value="0")
        self.acc_due_day = tk.StringVar(value="1")
        self.acc_institution = tk.StringVar()

        ttk.Label(form, text="Name", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.acc_name, width=16).grid(row=1, column=0, padx=4)
        ttk.Label(form, text="Account Type", style="CardDim.TLabel").grid(row=0, column=1, sticky="w")
        type_combo = ttk.Combobox(form, textvariable=self.acc_type, values=ACCOUNT_TYPE_LABELS,
                                   width=14, state="readonly")
        type_combo.grid(row=1, column=1, padx=4)
        type_combo.bind("<<ComboboxSelected>>", lambda e: self._update_extra_fields())
        ttk.Label(form, text="Balance", style="CardDim.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Entry(form, textvariable=self.acc_balance, width=10).grid(row=1, column=2, padx=4)
        self.currency_label = ttk.Label(form, text="Currency", style="CardDim.TLabel")
        self.currency_label.grid(row=0, column=3, sticky="w")
        self.currency_entry = ttk.Entry(form, textvariable=self.acc_currency, width=6)
        self.currency_entry.grid(row=1, column=3, padx=4)
        ttk.Label(form, text="Institution (optional)", style="CardDim.TLabel").grid(
            row=0, column=4, sticky="w")
        ttk.Entry(form, textvariable=self.acc_institution, width=12).grid(row=1, column=4, padx=4)
        ttk.Checkbutton(form, text="Liquid", variable=self.acc_liquid).grid(row=1, column=5, padx=6)
        ttk.Button(form, text="Add Account", style="Good.TButton", command=self.add_account).grid(
            row=1, column=6, padx=8)

        self.extra_frame = ttk.Frame(form, style="Card.TFrame")
        self.extra_frame.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(self.extra_frame, text="Credit limit", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_credit_limit, width=10).grid(row=1, column=0, padx=(0, 12))
        ttk.Label(self.extra_frame, text="Cashback % on spend", style="CardDim.TLabel").grid(
            row=0, column=1, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_cashback_rate, width=10).grid(row=1, column=1, padx=(0, 12))
        ttk.Label(self.extra_frame, text="Monthly cashback cap (0 = no cap)", style="CardDim.TLabel").grid(
            row=0, column=2, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_cashback_cap, width=10).grid(row=1, column=2, padx=(0, 12))
        ttk.Label(self.extra_frame, text="Payment due day (1-28)", style="CardDim.TLabel").grid(
            row=0, column=3, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_due_day, width=10).grid(row=1, column=3)
        self._update_extra_fields()

        list_card = Card(self, title="Accounts")
        list_card.pack(fill="x", pady=(0, 10))
        cols = ("name", "type", "balance", "currency", "liquid")
        acc_tree_frame = ttk.Frame(list_card, style="Card.TFrame")
        acc_tree_frame.pack(fill="x", expand=True)
        self.tree = ttk.Treeview(acc_tree_frame, columns=cols, show="tree headings", height=20)
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=130, anchor="w")
        for c, label in zip(cols, ["Name", "Type", "Balance", "Ccy", "Liquid"]):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=130)
        self.tree.pack(side="left", fill="x", expand=True)
        acc_tree_scroll = ttk.Scrollbar(acc_tree_frame, orient="vertical", command=self.tree.yview)
        acc_tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=acc_tree_scroll.set)
        btn_row = ttk.Frame(list_card, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Edit Selected Account…", command=self.open_edit_account_dialog).pack(
            side="left")
        ttk.Button(btn_row, text="Delete Selected Account", command=self.delete_selected).pack(
            side="left", padx=6)
        ttk.Button(btn_row, text="Transfer Between Accounts…", style="Accent.TButton",
                   command=self.open_transfer_dialog).pack(side="left", padx=6)
        ttk.Button(btn_row, text="View Ledger…", command=self.open_account_ledger).pack(side="left")
        ttk.Button(btn_row, text="Export Statement…", command=self.export_account_statement).pack(
            side="left", padx=6)
        ttk.Button(btn_row, text="Reconcile…", command=self.open_reconcile_dialog).pack(
            side="left", padx=6)

        transfers_card = Card(self, title="Transfers")
        transfers_card.pack(fill="x", pady=(0, 10))
        transfer_cols = ("date", "from", "to", "amount", "received", "rate")
        transfers_tree_frame = ttk.Frame(transfers_card, style="Card.TFrame")
        transfers_tree_frame.pack(fill="x", expand=True)
        self.transfers_tree = ttk.Treeview(transfers_tree_frame, columns=transfer_cols,
                                            show="headings", height=10)
        for col, label in zip(transfer_cols,
                               ["Date", "From", "To", "Amount", "Received", "Rate"]):
            self.transfers_tree.heading(col, text=label)
            self.transfers_tree.column(col, width=120, anchor="w")
        self.transfers_tree.pack(side="left", fill="x", expand=True)
        transfers_tree_scroll = ttk.Scrollbar(transfers_tree_frame, orient="vertical",
                                               command=self.transfers_tree.yview)
        transfers_tree_scroll.pack(side="right", fill="y")
        self.transfers_tree.configure(yscrollcommand=transfers_tree_scroll.set)
        transfers_btn_row = ttk.Frame(transfers_card, style="Card.TFrame")
        transfers_btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(transfers_btn_row, text="Edit Transfer…",
                   command=self.open_edit_transfer_dialog).pack(side="left")
        ttk.Button(transfers_btn_row, text="Delete Transfer",
                   command=self.delete_selected_transfer).pack(side="left", padx=6)

        cc_row = ttk.Frame(self)
        cc_row.pack(fill="x", pady=(0, 10))
        self.cc_card = Card(cc_row, title="Credit Cards — Utilization")
        self.cc_card.pack(fill="x")
        self.cc_inner = ttk.Frame(self.cc_card, style="Card.TFrame")
        self.cc_inner.pack(fill="x")

    def _update_extra_fields(self):
        subtype, _ = ACCOUNT_TYPE_BY_LABEL[self.acc_type.get()]
        if subtype == "credit_card":
            self.extra_frame.grid()
        else:
            self.extra_frame.grid_remove()

    def add_account(self):
        try:
            balance = float(self.acc_balance.get())
        except ValueError:
            messagebox.showerror("Error", "Balance must be a number.")
            return
        name = self.acc_name.get().strip() or "Unnamed account"
        subtype, kind = ACCOUNT_TYPE_BY_LABEL[self.acc_type.get()]
        try:
            credit_limit = float(self.acc_credit_limit.get()) if subtype == "credit_card" else 0.0
            cashback_rate = float(self.acc_cashback_rate.get()) if subtype == "credit_card" else 0.0
            cashback_cap = float(self.acc_cashback_cap.get()) if subtype == "credit_card" else 0.0
        except ValueError:
            credit_limit, cashback_rate, cashback_cap = 0.0, 0.0, 0.0
        due_day = None
        if subtype == "credit_card":
            try:
                due_day = int(self.acc_due_day.get())
                due_day = min(max(due_day, 1), 28)
            except ValueError:
                due_day = None
        liquid = self.acc_liquid.get() or subtype in ("cash", "savings", "emergency_fund")
        self.app.db.add_account(name, kind, balance,
                                 self.acc_currency.get().strip().upper() or "GBP",
                                 liquid, subtype=subtype, credit_limit=credit_limit,
                                 cashback_rate=cashback_rate, due_day=due_day,
                                 cashback_monthly_cap=cashback_cap,
                                 institution=self.acc_institution.get())
        self.acc_name.set("")
        self.acc_balance.set("")
        self.acc_institution.set("")
        self.app.refresh_all()

    def _selected_account_ids(self):
        """Filters the account tree's selection down to real account rows,
        ignoring institution group-header rows (iid "group:<name>") that a
        multi-select or click could otherwise pick up."""
        return [int(iid) for iid in self.tree.selection() if iid.isdigit()]

    def delete_selected(self):
        for account_id in self._selected_account_ids():
            self.app.db.delete_account(account_id)
        self.app.refresh_all()

    def open_edit_account_dialog(self):
        ids = self._selected_account_ids()
        if not ids:
            messagebox.showinfo("Edit Account", "Select an account first.")
            return
        if len(ids) > 1:
            messagebox.showinfo("Edit Account", "Select just one account to edit.")
            return
        account_id = ids[0]
        acc = self.app.db.get_account(account_id)
        if not acc:
            return

        win, content = make_scrollable_toplevel(self, "Edit Account", "440x600")

        ttk.Label(content, text="Name", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        name_var = tk.StringVar(value=acc["name"])
        ttk.Entry(content, textvariable=name_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Currency", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        currency_var = tk.StringVar(value=acc["currency"])
        ttk.Entry(content, textvariable=currency_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Institution (optional)", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        institution_var = tk.StringVar(value=acc["institution"] or "")
        ttk.Entry(content, textvariable=institution_var).pack(fill="x", padx=14)
        ttk.Label(content, wraplength=340, justify="left", style="CardDim.TLabel",
                  text="Groups accounts together in the list below, e.g. \"Lloyds\" for both a "
                       "current and a student account there. Leave blank to keep it ungrouped."
                  ).pack(anchor="w", padx=14, pady=(4, 0))

        ttk.Label(content, text="Balance", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        balance_var = tk.StringVar(value=str(acc["balance"]))
        ttk.Entry(content, textvariable=balance_var).pack(fill="x", padx=14)
        ttk.Label(content, wraplength=340, justify="left", style="CardDim.TLabel",
                  text="Directly sets the balance — no transaction is recorded. Use this to "
                       "backfill an account's starting balance without logging every past "
                       "transaction; use Reconcile… instead if you want an adjustment transaction."
                  ).pack(anchor="w", padx=14, pady=(4, 0))

        liquid_var = tk.BooleanVar(value=bool(acc["liquid"]))
        ttk.Checkbutton(content, text="Liquid", variable=liquid_var).pack(anchor="w", padx=14, pady=(10, 0))

        credit_limit_var = cashback_rate_var = cashback_cap_var = due_day_var = None

        if acc["subtype"] == "credit_card":
            ttk.Label(content, text="Credit limit", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
            credit_limit_var = tk.StringVar(value=str(acc["credit_limit"] or 0))
            ttk.Entry(content, textvariable=credit_limit_var).pack(fill="x", padx=14)

            ttk.Label(content, text="Cashback % on spend", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
            cashback_rate_var = tk.StringVar(value=str(acc["cashback_rate"] or 0))
            ttk.Entry(content, textvariable=cashback_rate_var).pack(fill="x", padx=14)

            ttk.Label(content, text="Monthly cashback cap (0 = no cap)", style="TLabel").pack(
                anchor="w", padx=14, pady=(10, 2))
            cashback_cap_var = tk.StringVar(value=str(acc["cashback_monthly_cap"] or 0))
            ttk.Entry(content, textvariable=cashback_cap_var).pack(fill="x", padx=14)

            ttk.Label(content, text="Payment due day (1-28)", style="TLabel").pack(
                anchor="w", padx=14, pady=(10, 2))
            due_day_var = tk.StringVar(value=str(acc["due_day"] or ""))
            ttk.Entry(content, textvariable=due_day_var).pack(fill="x", padx=14)

        def do_save():
            name = name_var.get().strip()
            currency = currency_var.get().strip().upper()
            if not name or not currency:
                messagebox.showerror("Edit Account", "Name and currency are required.")
                return
            try:
                balance = float(balance_var.get())
            except ValueError:
                messagebox.showerror("Edit Account", "Balance must be a number.")
                return
            self.app.db.update_account_core(account_id, name=name, currency=currency,
                                             liquid=liquid_var.get(), institution=institution_var.get())
            self.app.db.update_account_balance(account_id, balance)

            details = {}
            if credit_limit_var is not None:
                try:
                    details["credit_limit"] = float(credit_limit_var.get())
                except ValueError:
                    pass
            if cashback_rate_var is not None:
                try:
                    details["cashback_rate"] = float(cashback_rate_var.get())
                except ValueError:
                    pass
            if cashback_cap_var is not None:
                try:
                    details["cashback_monthly_cap"] = float(cashback_cap_var.get())
                except ValueError:
                    pass
            if due_day_var is not None:
                raw = due_day_var.get().strip()
                if raw:
                    try:
                        details["due_day"] = min(max(int(raw), 1), 28)
                    except ValueError:
                        pass
            if details:
                self.app.db.update_account_details(account_id, **details)

            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Save", style="Accent.TButton", command=do_save).pack(
            anchor="e", padx=14, pady=16)

    def open_transfer_dialog(self):
        accounts = self.app.db.list_accounts()
        if len(accounts) < 2:
            messagebox.showinfo("Transfer", "You need at least two accounts to transfer between.")
            return
        win, content = make_scrollable_toplevel(self, "Transfer Between Accounts", "440x420")
        names = [a["name"] for a in accounts]
        by_name = {a["name"]: a for a in accounts}

        ids = self._selected_account_ids()
        default_from = self.app.db.get_account(ids[0])["name"] if ids else names[0]

        ttk.Label(content, text="From account", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        from_var = tk.StringVar(value=default_from)
        ttk.Combobox(content, textvariable=from_var, values=names, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="To account", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        to_default = next((n for n in names if n != default_from), names[0])
        to_var = tk.StringVar(value=to_default)
        ttk.Combobox(content, textvariable=to_var, values=names, state="readonly").pack(fill="x", padx=14)

        ttk.Label(content, text="Amount (in From account's currency)", style="TLabel").pack(
            anchor="w", padx=14, pady=(10, 2))
        amount_var = tk.StringVar()
        ttk.Entry(content, textvariable=amount_var).pack(fill="x", padx=14)

        received_label = ttk.Label(content, text="Actual amount received (optional, in To account's currency)",
                                    style="TLabel")
        received_label.pack(anchor="w", padx=14, pady=(10, 2))
        received_var = tk.StringVar()
        received_entry = ttk.Entry(content, textvariable=received_var)
        received_entry.pack(fill="x", padx=14)

        note_var = tk.StringVar()
        ttk.Label(content, text="Note (optional)", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        ttk.Entry(content, textvariable=note_var).pack(fill="x", padx=14)

        rate_label = ttk.Label(content, style="CardDim.TLabel")
        rate_label.pack(anchor="w", padx=14, pady=(8, 0))

        def update_rate_preview(*_):
            f, t = by_name.get(from_var.get()), by_name.get(to_var.get())
            if not f or not t:
                return
            same_currency = f["currency"] == t["currency"]
            received_label.config(state="disabled" if same_currency else "normal")
            received_entry.config(state="disabled" if same_currency else "normal")
            if same_currency:
                rate_label.config(text="")
                return
            try:
                received = float(received_var.get())
            except ValueError:
                received = None
            if received:
                try:
                    amount = float(amount_var.get())
                    rate = received / amount if amount else 0
                    rate_label.config(text=f"Using your real rate: 1 {f['currency']} = "
                                            f"{rate:.4f} {t['currency']} (from the amounts you entered).")
                    return
                except ValueError:
                    pass
            rate = self.app.db.convert(1.0, f["currency"], t["currency"])
            rate_label.config(text=f"Rate today: 1 {f['currency']} ≈ {rate:.4f} {t['currency']} "
                                    f"— fill in \"actual amount received\" above if you know the real figure.")
        from_var.trace_add("write", update_rate_preview)
        to_var.trace_add("write", update_rate_preview)
        amount_var.trace_add("write", update_rate_preview)
        received_var.trace_add("write", update_rate_preview)
        update_rate_preview()

        def do_transfer():
            try:
                amount = float(amount_var.get())
            except ValueError:
                messagebox.showerror("Transfer", "Enter a valid amount.")
                return
            frm, to = by_name.get(from_var.get()), by_name.get(to_var.get())
            if not frm or not to or frm["id"] == to["id"]:
                messagebox.showerror("Transfer", "Choose two different accounts.")
                return
            if amount <= 0:
                messagebox.showerror("Transfer", "Amount must be positive.")
                return
            to_amount = None
            if received_var.get().strip():
                try:
                    to_amount = float(received_var.get())
                except ValueError:
                    messagebox.showerror("Transfer", "Enter a valid received amount, or leave it blank.")
                    return
                if to_amount <= 0:
                    messagebox.showerror("Transfer", "Received amount must be positive.")
                    return
            self.app.db.transfer_between_accounts(
                frm["id"], to["id"], amount, date=self.app.today.isoformat(), note=note_var.get(),
                to_amount=to_amount)
            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Transfer", style="Accent.TButton", command=do_transfer).pack(
            anchor="e", padx=14, pady=16)

    def export_account_statement(self):
        ids = self._selected_account_ids()
        if not ids:
            messagebox.showinfo("Export Statement", "Select an account first.")
            return
        account_id = ids[0]
        acc = self.app.db.get_account(account_id)
        if not acc:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=f"{acc['name'].replace(' ', '_')}_statement.csv")
        if not path:
            return
        n = export_account_statement_csv(self.app.db, account_id, path)
        messagebox.showinfo("Exported", f"Exported {n} row(s) of {acc['name']}'s statement to:\n{path}")

    def open_reconcile_dialog(self):
        ids = self._selected_account_ids()
        if not ids:
            messagebox.showinfo("Reconcile", "Select an account first.")
            return
        account_id = ids[0]
        acc = self.app.db.get_account(account_id)
        if not acc:
            return

        win, content = make_scrollable_toplevel(self, "Reconcile Balance", "420x280")

        ttk.Label(content, text=f"{acc['name']} — tracked balance: "
                             f"{fmt_money(acc['balance'], acc['currency'])}",
                  style="H2.TLabel", wraplength=320, justify="left").pack(
            anchor="w", padx=14, pady=(14, 8))

        ttk.Label(content, text="Actual balance from your statement", style="TLabel").pack(
            anchor="w", padx=14, pady=(0, 2))
        actual_var = tk.StringVar(value=f"{acc['balance']:.2f}")
        ttk.Entry(content, textvariable=actual_var).pack(fill="x", padx=14)

        diff_label = ttk.Label(content, style="CardDim.TLabel")
        diff_label.pack(anchor="w", padx=14, pady=(8, 0))

        def update_diff_preview(*_):
            try:
                actual = float(actual_var.get())
            except ValueError:
                diff_label.config(text="")
                return
            raw_diff = actual - acc["balance"]
            if abs(raw_diff) < 0.005:
                diff_label.config(text="Already matches — no adjustment needed.")
            else:
                # Mirror add_balance_adjustment's own sign convention: for a
                # liability account (credit card/loan), the transaction
                # amount that produces the target balance is the negation
                # of the raw difference — shown here so the preview matches
                # what will actually appear in the ledger afterward.
                delta = -raw_diff if acc["kind"] == "liability" else raw_diff
                diff_label.config(
                    text=f"Will record an adjustment of {fmt_money(delta, acc['currency'])}.")
        actual_var.trace_add("write", update_diff_preview)
        update_diff_preview()

        def do_reconcile():
            try:
                actual = float(actual_var.get())
            except ValueError:
                messagebox.showerror("Reconcile", "Enter a valid balance.")
                return
            self.app.db.add_balance_adjustment(account_id, actual, date=self.app.today.isoformat())
            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Reconcile", style="Accent.TButton", command=do_reconcile).pack(
            anchor="e", padx=14, pady=16)

    def open_edit_transfer_dialog(self):
        from finance_core import ReconciledTransactionError

        sel = self.transfers_tree.selection()
        if not sel:
            messagebox.showinfo("Edit Transfer", "Select a transfer first.")
            return
        if len(sel) > 1:
            messagebox.showinfo("Edit Transfer", "Select just one transfer to edit.")
            return
        leg_id = int(sel[0])
        leg = self.app.db.conn.execute(
            "SELECT * FROM transactions WHERE id=?", (leg_id,)).fetchone()
        if not leg or not leg["transfer_group_id"]:
            return
        group_id = leg["transfer_group_id"]
        transfer = next((t for t in self.app.db.list_transfers()
                          if t["transfer_group_id"] == group_id), None)
        if not transfer:
            return

        accounts = self.app.db.list_accounts()
        names = [a["name"] for a in accounts]
        by_name = {a["name"]: a for a in accounts}
        cross_currency = transfer["from_currency"] != transfer["to_currency"]

        win, content = make_scrollable_toplevel(self, "Edit Transfer", "440x480")

        ttk.Label(content, text="From account", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        from_var = tk.StringVar(value=transfer["from_account"] or names[0])
        ttk.Combobox(content, textvariable=from_var, values=names, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="To account", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        to_var = tk.StringVar(value=transfer["to_account"] or names[0])
        ttk.Combobox(content, textvariable=to_var, values=names, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(content, text="Date (YYYY-MM-DD)", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        date_var = tk.StringVar(value=transfer["date"])
        ttk.Entry(content, textvariable=date_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Amount (in From account's currency)", style="TLabel").pack(
            anchor="w", padx=14, pady=(10, 2))
        amount_var = tk.StringVar(value=f"{transfer['from_amount']:.2f}")
        ttk.Entry(content, textvariable=amount_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Actual amount received (optional, in To account's currency)",
                  style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        # Pre-filled with the transfer's existing converted amount (when the
        # two currencies differ) so leaving this untouched preserves the
        # original effective rate instead of silently re-deriving it from
        # today's fx_rates -- only actually used if the accounts are still
        # cross-currency by the time Save is clicked (see do_save below).
        received_var = tk.StringVar(value=f"{transfer['to_amount']:.2f}" if cross_currency else "")
        ttk.Entry(content, textvariable=received_var).pack(fill="x", padx=14)

        note_var = tk.StringVar(value=leg["note"] or "")
        ttk.Label(content, text="Note (optional)", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        ttk.Entry(content, textvariable=note_var).pack(fill="x", padx=14)

        def do_save():
            try:
                amount = float(amount_var.get())
            except ValueError:
                messagebox.showerror("Edit Transfer", "Enter a valid amount.")
                return
            frm, to = by_name.get(from_var.get()), by_name.get(to_var.get())
            if not frm or not to:
                messagebox.showerror("Edit Transfer", "Choose two accounts.")
                return
            try:
                datetime.date.fromisoformat(date_var.get().strip())
            except ValueError:
                messagebox.showerror("Edit Transfer", "Date must be YYYY-MM-DD.")
                return
            to_amount = None
            # Ignore a stale received-amount value if the accounts chosen
            # now are same-currency -- it has no meaning there and would
            # otherwise silently override the amount.
            if frm["currency"] != to["currency"] and received_var.get().strip():
                try:
                    to_amount = float(received_var.get())
                except ValueError:
                    messagebox.showerror("Edit Transfer",
                                          "Enter a valid received amount, or leave it blank.")
                    return
            try:
                self.app.db.update_transfer(
                    group_id, from_account_id=frm["id"], to_account_id=to["id"], amount=amount,
                    to_amount=to_amount, date=date_var.get().strip(), note=note_var.get().strip())
            except ReconciledTransactionError:
                messagebox.showerror(
                    "Edit Transfer",
                    "This transfer is reconciled/locked. Unreconcile it first if you need to edit it.")
                return
            except ValueError as e:
                messagebox.showerror("Edit Transfer", str(e))
                return
            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Save", style="Accent.TButton", command=do_save).pack(
            anchor="e", padx=14, pady=16)

    def delete_selected_transfer(self):
        from finance_core import ReconciledTransactionError
        sel = self.transfers_tree.selection()
        if not sel:
            messagebox.showinfo("Delete Transfer", "Select a transfer first.")
            return
        blocked = 0
        for iid in sel:
            try:
                self.app.db.delete_transaction(int(iid))
            except ReconciledTransactionError:
                blocked += 1
        if blocked:
            messagebox.showinfo(
                "Reconciled transaction",
                f"{blocked} selected transfer(s) are reconciled/locked and were not deleted. "
                "Unreconcile them first if you need to remove them.")
        self.app.refresh_all()

    def open_account_ledger(self):
        ids = self._selected_account_ids()
        if not ids:
            messagebox.showinfo("Ledger", "Select an account first.")
            return
        account_id = ids[0]
        acc = self.app.db.get_account(account_id)
        if not acc:
            return

        win, content = make_scrollable_toplevel(self, f"Ledger — {acc['name']}", "800x540")

        ttk.Label(content, text=f"{acc['name']} — running balance in {acc['currency']}  ·  "
                             "double-click a row to edit (transfers are edited from the "
                             "Accounts tab's Transfers list)",
                  style="H2.TLabel", wraplength=740, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4))

        cols = ("date", "payee", "amount", "balance", "flags")
        ledger_tree_frame = ttk.Frame(content)
        ledger_tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree = ttk.Treeview(ledger_tree_frame, columns=cols, show="headings", height=18)
        for col, label, w in zip(cols, ["Date", "Payee/Transfer", "Amount", "Balance", ""],
                                  (90, 260, 100, 110, 60)):
            tree.heading(col, text=label)
            tree.column(col, width=w, anchor="w")
        tree.pack(side="left", fill="both", expand=True)
        ledger_tree_scroll = ttk.Scrollbar(ledger_tree_frame, orient="vertical", command=tree.yview)
        ledger_tree_scroll.pack(side="right", fill="y")
        tree.configure(yscrollcommand=ledger_tree_scroll.set)

        def refresh_ledger_rows():
            for row in tree.get_children():
                tree.delete(row)
            for r in self.app.db.account_ledger(account_id):
                flags = ("🔒" if r["reconciled"] else "") + ("⇄" if r["is_transfer"] else "")
                label = r["transfer_to_name"] and (
                    f"Transfer w/ {r['transfer_to_name']}") or (r["payee"] or "")
                tree.insert("", "end", iid=str(r["id"]), values=(
                    r["date"], label, f"{r['amount']:,.2f}", f"{r['running_balance']:,.2f}", flags))

        def on_double_click(_event):
            sel = tree.selection()
            if not sel:
                return
            def after_save():
                self.app.refresh_all()
                refresh_ledger_rows()
            open_transaction_edit_dialog(win, self.app, int(sel[0]), on_saved=after_save)

        tree.bind("<Double-1>", on_double_click)
        refresh_ledger_rows()

    def _edit_cashback(self, account_id):
        acc = self.app.db.get_account(account_id)
        if not acc:
            return
        win, content = make_scrollable_toplevel(self, "Edit Cashback", "380x260")

        ttk.Label(content, text="Cashback % on spend", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        rate_var = tk.StringVar(value=f"{acc['cashback_rate']:.2f}")
        ttk.Entry(content, textvariable=rate_var).pack(fill="x", padx=14)

        ttk.Label(content, text="Monthly cashback cap (0 = no cap)", style="TLabel").pack(
            anchor="w", padx=14, pady=(10, 2))
        cap_var = tk.StringVar(value=f"{acc['cashback_monthly_cap']:.2f}")
        ttk.Entry(content, textvariable=cap_var).pack(fill="x", padx=14)

        def save():
            try:
                rate = float(rate_var.get())
                cap = float(cap_var.get())
            except ValueError:
                messagebox.showerror("Edit Cashback", "Enter valid numbers.")
                return
            self.app.db.update_account_details(account_id, cashback_rate=rate,
                                                cashback_monthly_cap=cap)
            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Save", style="Accent.TButton", command=save).pack(
            anchor="e", padx=14, pady=16)

    def _set_cashback_auto_invest(self, account_id):
        jar = self.app.db.get_or_create_roundup_jar()
        targets = [jar]

        win, content = make_scrollable_toplevel(self, "Cashback Destination", "400x220")

        ttk.Label(content, text="Route this card's cashback straight into:", style="TLabel").pack(
            anchor="w", padx=14, pady=(14, 4))
        names = ["(none — accumulate for manual redemption)"] + [a["name"] for a in targets]
        by_name = {a["name"]: a["id"] for a in targets}
        current = next((a["name"] for a in targets
                         if a["id"] == self.app.db.get_account(account_id)["cashback_auto_invest_account_id"]),
                        names[0])
        target_var = tk.StringVar(value=current)
        ttk.Combobox(content, textvariable=target_var, values=names, state="readonly").pack(fill="x", padx=14)

        def save():
            target_id = by_name.get(target_var.get(), 0)
            self.app.db.update_account_details(account_id, cashback_auto_invest_account_id=target_id)
            win.destroy()
            self.app.refresh_all()

        ttk.Button(content, text="Save", style="Accent.TButton", command=save).pack(anchor="e", padx=14, pady=16)

    def _set_due_day(self, account_id):
        day = simpledialog.askinteger("Payment Due Day", "Day of the month payment is due (1-28):",
                                       parent=self, minvalue=1, maxvalue=28)
        if day is not None:
            self.app.db.update_account_details(account_id, due_day=day)
            self.app.refresh_all()

    def refresh(self):
        if self.app.currency_mode() == "holiday":
            self.currency_label.grid()
            self.currency_entry.grid()
        else:
            self.currency_label.grid_remove()
            self.currency_entry.grid_remove()
            self.acc_currency.set(self.app.reporting_currency())

        for row in self.tree.get_children():
            self.tree.delete(row)
        # Group accounts by institution (e.g. two Lloyds accounts sit under
        # one "Lloyds" header) -- accounts with no institution set fall into
        # a single "Other" group, listed last.
        by_institution = {}
        ungrouped = []
        for a in self.app.db.list_accounts():
            if a["institution"]:
                by_institution.setdefault(a["institution"], []).append(a)
            else:
                ungrouped.append(a)
        groups = sorted(by_institution.items())
        if ungrouped:
            groups.append(("Other", ungrouped))
        self.tree.tag_configure("group", font=theme.Fonts.body_bold)
        acct_color_index = 0
        for group_name, accs in groups:
            group_iid = f"group:{group_name}"
            self.tree.insert("", "end", iid=group_iid, text=group_name, open=True, tags=("group",))
            for a in accs:
                type_label = ACCOUNT_TYPE_BY_SUBTYPE_KIND.get((a["subtype"], a["kind"]), "Other")
                # Every account gets a default color too (cycled the same
                # way categories do), so the list has visual identity per
                # account without requiring any manual setup.
                row_tag = f"acctcolor_{a['id']}"
                self.tree.tag_configure(
                    row_tag, foreground=CATEGORY_CHART_COLORS[acct_color_index % len(CATEGORY_CHART_COLORS)])
                acct_color_index += 1
                self.tree.insert(group_iid, "end", iid=str(a["id"]), values=(
                    a["name"], type_label, f"{a['balance']:,.2f}", a["currency"],
                    "yes" if a["liquid"] else "no"), tags=(row_tag,))

        for row in self.transfers_tree.get_children():
            self.transfers_tree.delete(row)
        for t in self.app.db.list_transfers():
            if t["from_currency"] == t["to_currency"] or t["historical_rate"] is None:
                rate_text = "—"
            else:
                rate_text = f"{t['historical_rate']:.4f}"
            self.transfers_tree.insert("", "end", iid=str(t["leg_id"]), values=(
                t["date"], t["from_account"] or "(deleted)", t["to_account"] or "(deleted)",
                fmt_money(t["from_amount"], t["from_currency"]),
                fmt_money(t["to_amount"], t["to_currency"]), rate_text))

        c = self.app.c
        cur = self.app.reporting_currency()

        # credit cards
        for w in self.cc_inner.winfo_children():
            w.destroy()
        cards = credit_utilization(self.app.db)
        if not cards:
            ttk.Label(self.cc_inner, text="No credit cards with a limit set yet — add one above.",
                      style="CardDim.TLabel").pack(anchor="w")
        else:
            for entry in cards:
                a = entry["account"]
                row = ttk.Frame(self.cc_inner, style="Card.TFrame")
                row.pack(fill="x", pady=6)
                label = f"{a['name']} — {fmt_money(entry['balance'], cur)} of {fmt_money(entry['limit'], cur)}"
                if a["cashback_rate"]:
                    label += f"  ·  {a['cashback_rate']:.1f}% cashback"
                    if a["cashback_monthly_cap"]:
                        earned = self.app.db.cashback_earned_this_month(a["id"], self.app.today.isoformat())
                        label += (f"  ·  {fmt_money(earned, cur)} of "
                                  f"{fmt_money(a['cashback_monthly_cap'], cur)} cap earned this month")
                ttk.Label(row, text=label, style="Card.TLabel").pack(anchor="w")
                bar_bg = tk.Canvas(row, height=10, width=400, bg=c["grid"], highlightthickness=0)
                bar_bg.pack(anchor="w", pady=(3, 0))
                pct = min(entry["utilization"], 1.0)
                fill_w = max(pct * 400, 3)
                color = c["good"] if entry["utilization"] <= 0.3 else (
                    c["warn"] if entry["utilization"] <= 0.7 else c["bad"])
                charts.rounded_rect(bar_bg, 0, 0, fill_w, 10, r=5, fill=color, outline="")
                bottom = ttk.Frame(row, style="Card.TFrame")
                bottom.pack(fill="x", pady=(2, 0))
                due_text = f"Payment due on day {a['due_day']} of the month" if a["due_day"] else \
                    "No payment due date set"
                ttk.Label(bottom, text=f"{entry['utilization']*100:,.0f}% utilized  ·  {due_text}",
                          style="CardDim.TLabel").pack(side="left")
                ttk.Button(bottom, text="Set Due Day",
                           command=lambda aid=a["id"]: self._set_due_day(aid)).pack(side="left", padx=8)
                ttk.Button(bottom, text="Edit Cashback…",
                           command=lambda aid=a["id"]: self._edit_cashback(aid)).pack(side="left", padx=8)
                if a["cashback_rate"]:
                    target = next((acc["name"] for acc in self.app.db.list_accounts()
                                   if acc["id"] == a["cashback_auto_invest_account_id"]), None)
                    dest_text = f"Cashback routed to {target}" if target else "Cashback not routed anywhere"
                    ttk.Label(bottom, text=f"  ·  {dest_text}", style="CardDim.TLabel").pack(side="left")
                    ttk.Button(bottom, text="Set Cashback Destination",
                               command=lambda aid=a["id"]: self._set_cashback_auto_invest(aid)).pack(
                        side="left", padx=8)


# --------------------------------------------------------------------------
# Net Worth / FI overview — totals and charts
# --------------------------------------------------------------------------

class NetWorthTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        c = self.app.c
        summary_row = ttk.Frame(self)
        summary_row.pack(fill="x", pady=(0, 10))
        summary_row.columnconfigure(0, weight=2)
        summary_row.columnconfigure(1, weight=1)

        summary = Card(summary_row, title="Net Worth")
        summary.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.nw_label = ttk.Label(summary, style="Hero.TLabel")
        self.nw_label.pack(anchor="w")
        self.fi_label = ttk.Label(summary, style="CardDim.TLabel", wraplength=420, justify="left")
        self.fi_label.pack(anchor="w", pady=(4, 8))
        ttk.Button(summary, text="Record Net Worth Snapshot (today)", style="Good.TButton",
                   command=self.record_snapshot).pack(anchor="w")

        ring_card = Card(summary_row, title="FI Progress")
        ring_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.fi_ring = tk.Canvas(ring_card, height=140, highlightthickness=0, bg=c["card"])
        self.fi_ring.pack(fill="both", expand=True)

        charts_row = ttk.Frame(self)
        charts_row.pack(fill="both", expand=True)
        charts_row.columnconfigure(0, weight=1)
        charts_row.columnconfigure(1, weight=1)

        breakdown_card = Card(charts_row, title="Net Worth by Type")
        breakdown_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.breakdown_canvas = tk.Canvas(breakdown_card, height=200, highlightthickness=0, bg=c["card"])
        self.breakdown_canvas.pack(fill="both", expand=True)

        trend_card = Card(charts_row, title="Net Worth Over Time")
        trend_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.trend_canvas = tk.Canvas(trend_card, height=200, highlightthickness=0, bg=c["card"])
        self.trend_canvas.pack(fill="both", expand=True)

    def record_snapshot(self):
        nw = net_worth(self.app.db)
        self.app.db.record_networth_snapshot(self.app.today.isoformat(), nw)
        self.refresh()

    def refresh(self):
        c = self.app.c
        cur = self.app.reporting_currency()
        nw = net_worth(self.app.db)
        self.nw_label.config(text=fmt_money(nw, cur))

        y, m = self.app.view_year, self.app.view_month
        _, expenses, _ = monthly_totals(self.app.db, y, m)
        annual_expenses = expenses * 12
        if annual_expenses > 0:
            fi = fi_number(self.app.db, annual_expenses)
            progress = (nw / fi) if fi > 0 else 0
            self.fi_label.config(
                text=f"FI Number (25x this month's annualized expenses): {fmt_money(fi, cur)} "
                     f"— you're at {progress*100:,.1f}% of it")
            charts.draw_progress_ring(self.fi_ring, progress, c, label="of FI number")
        else:
            self.fi_label.config(text="Log some expenses this month to estimate your FI number.")
            charts.draw_progress_ring(self.fi_ring, 0, c, label="of FI number")

        breakdown = net_worth_breakdown(self.app.db)
        segment_colors = {"cash": c["good"], "credit_card": c["bad"],
                           "loan": c["warn"], "other": c["text_faint"],
                           "savings": c["accent"], "emergency_fund": c["accent_hover"]}
        segments = [(k.replace("_", " ").title(), abs(v), segment_colors.get(k, c["text_faint"]))
                    for k, v in breakdown.items() if abs(v) > 0.01]
        charts.draw_donut_chart(self.breakdown_canvas, segments, c,
                                 center_label=fmt_money(nw, cur), center_sub="net worth")

        snaps = self.app.db.list_networth_snapshots()
        values = [s["net_worth"] for s in snaps]
        labels = [s["date"][5:] for s in snaps]
        charts.draw_line_chart(self.trend_canvas, values, labels, c,
                                unit_fmt=lambda v: f"{v:,.0f}")


# --------------------------------------------------------------------------
# Insights — top payees, day-of-month spending heatmap
# --------------------------------------------------------------------------

class InsightsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        c = self.app.c
        ttk.Label(self, text="Where the month's spend actually goes — uses the month "
                              "selected at the top of the app.", style="CardDim.TLabel").pack(
            anchor="w", pady=(0, 8))

        payees_card = Card(self, title="Top Payees This Month")
        payees_card.pack(fill="x", pady=(0, 10))
        self.payees_canvas = tk.Canvas(payees_card, height=220, highlightthickness=0, bg=c["card"])
        self.payees_canvas.pack(fill="both", expand=True)

        heatmap_card = Card(self, title="Spending Heatmap — Day of Month")
        heatmap_card.pack(fill="x", pady=(0, 10))
        self.heatmap_canvas = tk.Canvas(heatmap_card, height=220, highlightthickness=0, bg=c["card"])
        self.heatmap_canvas.pack(fill="both", expand=True)

    def refresh(self):
        db = self.app.db
        c = self.app.c
        y, m = self.app.view_year, self.app.view_month
        cur = self.app.reporting_currency()

        payees = top_payees(db, y, m, limit=8)
        charts.draw_bar_chart(
            self.payees_canvas, [p["payee"] for p in payees],
            [("Spend", "bad", [p["total"] for p in payees])],
            c, unit_fmt=lambda v: fmt_money(v, cur))

        totals = daily_spend_totals(db, y, m)
        charts.draw_calendar_heatmap(self.heatmap_canvas, y, m, totals, c,
                                      unit_fmt=lambda v: fmt_money(v, cur))


# --------------------------------------------------------------------------
# Forecast — spend trend/run-rate, actual-vs-budgeted, what-if, goal tracker
# --------------------------------------------------------------------------

FORECAST_RANGE_LABELS = {"6 months": 6, "12 months": 12, "24 months": 24, "36 months": 36}
WHATIF_KIND_LABELS = {"Need": "need", "Want": "want", "Saving": "saving"}


class ForecastTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        c = self.app.c
        ttk.Label(self, text="Where spending is heading, and what it takes to hit a goal — "
                              "forward-looking, unlike Insights' look back at where money went.",
                  style="CardDim.TLabel", wraplength=800, justify="left").pack(anchor="w", pady=(0, 8))

        trend_card = Card(self, title="Expense Trend")
        trend_card.pack(fill="x", pady=(0, 10))
        range_row = ttk.Frame(trend_card, style="Card.TFrame")
        range_row.pack(fill="x", anchor="e")
        ttk.Label(range_row, text="Range", style="CardDim.TLabel").pack(side="left", padx=(0, 6))
        self.trend_range_var = tk.StringVar(value="6 months")
        range_combo = ttk.Combobox(range_row, textvariable=self.trend_range_var,
                                    values=list(FORECAST_RANGE_LABELS.keys()), width=10, state="readonly")
        range_combo.pack(side="left")
        range_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        self.trend_canvas = tk.Canvas(trend_card, height=200, highlightthickness=0, bg=c["card"])
        self.trend_canvas.pack(fill="both", expand=True)

        run_rate_card = Card(self, title="Run-Rate Projection — This Period")
        run_rate_card.pack(fill="x", pady=(0, 10))
        ttk.Label(run_rate_card, text="Budgeted categories projected from spend-so-far, worst first.",
                  style="CardDim.TLabel").pack(anchor="w")
        self.run_rate_frame = ttk.Frame(run_rate_card, style="Card.TFrame")
        self.run_rate_frame.pack(fill="x", pady=(6, 0))

        donuts_card = Card(self, title="Actual vs. Budgeted — This Period")
        donuts_card.pack(fill="x", pady=(0, 10))
        donuts_row = ttk.Frame(donuts_card, style="Card.TFrame")
        donuts_row.pack(fill="both", expand=True)
        actual_col = ttk.Frame(donuts_row, style="Card.TFrame")
        actual_col.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ttk.Label(actual_col, text="Actual spend by category", style="CardDim.TLabel").pack(anchor="w")
        self.actual_donut_canvas = tk.Canvas(actual_col, height=200, highlightthickness=0, bg=c["card"])
        self.actual_donut_canvas.pack(fill="both", expand=True)
        budgeted_col = ttk.Frame(donuts_row, style="Card.TFrame")
        budgeted_col.pack(side="left", fill="both", expand=True, padx=(5, 0))
        ttk.Label(budgeted_col, text="Budgeted allocation by category", style="CardDim.TLabel").pack(
            anchor="w")
        self.budgeted_donut_canvas = tk.Canvas(budgeted_col, height=200, highlightthickness=0, bg=c["card"])
        self.budgeted_donut_canvas.pack(fill="both", expand=True)

        ttk.Label(donuts_card, text="Plan vs. Actual (Need/Want/Saving split)",
                  style="CardDim.TLabel").pack(anchor="w", pady=(10, 0))
        self.plan_actual_frame = ttk.Frame(donuts_card, style="Card.TFrame")
        self.plan_actual_frame.pack(fill="x", pady=(4, 0))

        whatif_card = Card(self, title="What If…")
        whatif_card.pack(fill="x", pady=(0, 10))
        ttk.Label(whatif_card, text="See the effect of spending more or less in a category type this "
                                     "period, without changing any real data.",
                  style="CardDim.TLabel", wraplength=760, justify="left").pack(anchor="w")
        whatif_row = ttk.Frame(whatif_card, style="Card.TFrame")
        whatif_row.pack(fill="x", pady=(8, 0))
        ttk.Label(whatif_row, text="Category type", style="CardDim.TLabel").pack(side="left")
        self.whatif_kind_var = tk.StringVar(value="Want")
        ttk.Combobox(whatif_row, textvariable=self.whatif_kind_var, values=list(WHATIF_KIND_LABELS.keys()),
                     width=10, state="readonly").pack(side="left", padx=(4, 12))
        ttk.Label(whatif_row, text="Adjust spend by (negative = spend less)",
                  style="CardDim.TLabel").pack(side="left")
        self.whatif_delta_var = tk.StringVar(value="-50")
        ttk.Entry(whatif_row, textvariable=self.whatif_delta_var, width=10).pack(side="left", padx=(4, 12))
        ttk.Button(whatif_row, text="Calculate", style="Accent.TButton",
                   command=self._calculate_whatif).pack(side="left")
        self.whatif_result_label = ttk.Label(whatif_card, style="CardDim.TLabel", wraplength=760,
                                              justify="left")
        self.whatif_result_label.pack(anchor="w", pady=(8, 0))

        goal_card = Card(self, title="Savings / Net Worth Goal")
        goal_card.pack(fill="x", pady=(0, 10))
        goal_row = ttk.Frame(goal_card, style="Card.TFrame")
        goal_row.pack(fill="x")
        ttk.Label(goal_row, text="Target amount", style="CardDim.TLabel").pack(side="left")
        self.goal_amount_var = tk.StringVar()
        ttk.Entry(goal_row, textvariable=self.goal_amount_var, width=12).pack(side="left", padx=(4, 12))
        ttk.Label(goal_row, text="By date (YYYY-MM-DD)", style="CardDim.TLabel").pack(side="left")
        self.goal_date_var = tk.StringVar()
        ttk.Entry(goal_row, textvariable=self.goal_date_var, width=12).pack(side="left", padx=(4, 12))
        ttk.Button(goal_row, text="Save Goal", style="Accent.TButton",
                   command=self._save_goal).pack(side="left")
        self.goal_progress_label = ttk.Label(goal_card, style="Card.TLabel", font=theme.Fonts.body_bold)
        self.goal_progress_label.pack(anchor="w", pady=(10, 2))
        self.goal_progress_canvas = tk.Canvas(goal_card, height=14, highlightthickness=0, bg=c["card"])
        self.goal_progress_canvas.pack(fill="x", pady=(0, 6))
        self.goal_result_label = ttk.Label(goal_card, style="CardDim.TLabel", wraplength=760,
                                            justify="left")
        self.goal_result_label.pack(anchor="w", pady=(2, 0))

    def _draw_goal_progress_bar(self, pct):
        canvas = self.goal_progress_canvas
        w = canvas.winfo_width()
        h = canvas.winfo_height() or 14
        if w < 10:
            canvas.after(50, lambda: self._draw_goal_progress_bar(pct) if canvas.winfo_exists() else None)
            return
        c = self.app.c
        canvas.delete("all")
        charts.rounded_rect(canvas, 0, 0, w, h, r=h / 2, fill=c["grid"], outline="")
        pct = max(0.0, min(pct, 1.0))
        if pct > 0:
            fill_w = max(h, w * pct)
            color = c["good"] if pct >= 1.0 else c["accent"]
            charts.rounded_rect(canvas, 0, 0, fill_w, h, r=h / 2, fill=color, outline="")

    def _calculate_whatif(self):
        db = self.app.db
        cur = self.app.reporting_currency()
        y, m = self.app.view_year, self.app.view_month
        kind = WHATIF_KIND_LABELS[self.whatif_kind_var.get()]
        try:
            delta = float(self.whatif_delta_var.get())
        except ValueError:
            self.whatif_result_label.config(text="Enter a valid number.")
            return
        result = whatif_category_adjustment(db, y, m, category_kind=kind, delta_amount=delta)
        if result["income"] <= 0:
            self.whatif_result_label.config(
                text="No income logged this period yet — savings rate can't be projected.")
            return
        cur_rate = result["current_savings_rate"] or 0.0
        new_rate = result["new_savings_rate"] or 0.0
        self.whatif_result_label.config(
            text=f"Expenses: {fmt_money(result['current_expenses'], cur)} → "
                 f"{fmt_money(result['new_expenses'], cur)}   ·   "
                 f"Savings rate: {cur_rate*100:.1f}% → {new_rate*100:.1f}%")

    def _save_goal(self):
        try:
            amount = float(self.goal_amount_var.get())
        except ValueError:
            messagebox.showerror("Goal", "Target amount must be a number.")
            return
        try:
            datetime.date.fromisoformat(self.goal_date_var.get().strip())
        except ValueError:
            messagebox.showerror("Goal", "Target date must be YYYY-MM-DD.")
            return
        self.app.db.set_setting("goal_target_amount", amount)
        self.app.db.set_setting("goal_target_date", self.goal_date_var.get().strip())
        self.refresh()

    def refresh(self):
        db = self.app.db
        c = self.app.c
        y, m = self.app.view_year, self.app.view_month
        cur = self.app.reporting_currency()

        n_months = FORECAST_RANGE_LABELS.get(self.trend_range_var.get(), 6)
        history = monthly_history(db, y, m, n_months=n_months)
        cats = [label for label, _, _ in history]
        income_series = [i for _, i, _ in history]
        expense_series = [e for _, _, e in history]
        charts.draw_bar_chart(
            self.trend_canvas, cats,
            [("Income", "good", income_series), ("Expenses", "bad", expense_series)],
            c, unit_fmt=lambda v: fmt_money(v, cur))

        for w in self.run_rate_frame.winfo_children():
            w.destroy()
        run_rate = [r for r in budget_run_rate(db, y, m, today=self.app.today) if r["budget"] > 0]
        if not run_rate:
            ttk.Label(self.run_rate_frame, text="No budgeted categories yet.",
                      style="CardDim.TLabel").pack(anchor="w")
        for r in run_rate:
            row = ttk.Frame(self.run_rate_frame, style="Card.TFrame")
            row.pack(fill="x", pady=2)
            style = "Bad.TLabel" if r["projected_over"] else "CardDim.TLabel"
            over_text = f" (over by {fmt_money(r['projected'] - r['budget'], cur)})" if r["projected_over"] else ""
            ttk.Label(row, text=f"{r['category']['name']}: on pace for {fmt_money(r['projected'], cur)} "
                                 f"of {fmt_money(r['budget'], cur)}{over_text}",
                      style=style).pack(anchor="w")

        spend_by_cat = {}
        for t in db.transactions_in_month(y, m):
            if t["amount"] < 0 and t["category_id"] is not None:
                spend_by_cat[t["category_id"]] = spend_by_cat.get(t["category_id"], 0.0) - db.to_reporting(
                    t["amount"], t["currency"])
        all_cats = db.list_categories()
        resolved_colors = resolve_category_colors(all_cats)
        spend_categories = [cat for cat in all_cats if cat["kind"] in ("need", "want", "saving")]

        actual_segments = [
            (cat["name"], spend_by_cat.get(cat["id"], 0.0), resolved_colors[cat["id"]])
            for cat in spend_categories if spend_by_cat.get(cat["id"], 0.0) > 0
        ]
        budgeted_segments = [
            (cat["name"], cat["monthly_budget"] or 0.0, resolved_colors[cat["id"]])
            for cat in spend_categories if (cat["monthly_budget"] or 0.0) > 0
        ]
        total_actual = sum(v for _, v, _ in actual_segments)
        total_budgeted = sum(v for _, v, _ in budgeted_segments)
        charts.draw_donut_chart(self.actual_donut_canvas, actual_segments, c,
                                 center_label=fmt_money(total_actual, cur), center_sub="actual")
        charts.draw_donut_chart(self.budgeted_donut_canvas, budgeted_segments, c,
                                 center_label=fmt_money(total_budgeted, cur), center_sub="budgeted")

        for w in self.plan_actual_frame.winfo_children():
            w.destroy()
        kind_spend = spend_by_kind(db, y, m)
        total_spend = sum(kind_spend.values())
        for i, (kind, plan_pct, kind_label) in enumerate(
                (("need", 0.50, "Needs"), ("want", 0.30, "Wants"), ("saving", 0.20, "Savings"))):
            actual_pct = (kind_spend[kind] / total_spend) if total_spend > 0 else 0.0
            # Under plan is favorable for need/want (spending less than
            # budgeted), but unfavorable for saving (saving less than the
            # target share) -- the two kinds read the same comparison
            # in opposite directions.
            over_plan = actual_pct > plan_pct + 0.01
            under_plan = actual_pct < plan_pct - 0.01
            if kind == "saving":
                style = "Bad.TLabel" if under_plan else "Good.TLabel"
            else:
                style = "Bad.TLabel" if over_plan else "Good.TLabel"
            row = ttk.Frame(self.plan_actual_frame, style="Card.TFrame")
            row.grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else 18, 0))
            ttk.Label(row, text=kind_label, style="Card.TLabel", font=theme.Fonts.body_bold).pack(
                anchor="w")
            ttk.Label(row, text=f"Plan {plan_pct*100:.0f}%", style="CardDim.TLabel").pack(anchor="w")
            ttk.Label(row, text=f"Actual {actual_pct*100:.0f}%", style=style).pack(anchor="w")

        saved_amount = db.get_setting_float("goal_target_amount", 0.0)
        saved_date = db.get_setting("goal_target_date", "")
        if saved_amount:
            self.goal_amount_var.set(str(saved_amount))
        if saved_date:
            self.goal_date_var.set(saved_date)
        if saved_amount and saved_date:
            try:
                result = goal_projection(db, saved_amount, saved_date, today=self.app.today)
            except ValueError:
                self.goal_progress_label.config(text="")
                self.goal_progress_canvas.delete("all")
                self.goal_result_label.config(text="Saved target date isn't valid — re-enter it above.")
            else:
                if result["on_track"]:
                    status = ("Goal already reached." if result["remaining"] <= 0 else
                               f"On track — averaging {fmt_money(result['avg_monthly_savings'], cur)}/mo "
                               f"against {fmt_money(result['monthly_needed'], cur)}/mo needed.")
                else:
                    needed_text = (f"{fmt_money(result['monthly_needed'], cur)}/mo needed"
                                   if result["monthly_needed"] is not None else "target date has passed")
                    status = (f"Not on track — averaging {fmt_money(result['avg_monthly_savings'], cur)}/mo "
                              f"against {needed_text}.")
                self.goal_progress_label.config(
                    text=f"{fmt_money(result['current'], cur)} / {fmt_money(saved_amount, cur)}")
                self._draw_goal_progress_bar(result["current"] / saved_amount if saved_amount else 0.0)
                self.goal_result_label.config(
                    text=f"Remaining: {fmt_money(result['remaining'], cur)}  ·  "
                         f"{result['months_left']} month(s) left. {status}")
        else:
            self.goal_progress_label.config(text="")
            self.goal_progress_canvas.delete("all")
            self.goal_result_label.config(text="Set a target amount and date to see a projection.")


# --------------------------------------------------------------------------
# Rewards — round-up spare change jar + cashback
# --------------------------------------------------------------------------

class RewardsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        c = self.app.c

        # --- Round-up jar ---
        jar_row = ttk.Frame(self)
        jar_row.pack(fill="x", pady=(0, 10))
        jar_row.columnconfigure(0, weight=1)
        jar_row.columnconfigure(1, weight=1)

        settings_card = Card(jar_row, title="🐷  Spare-Change Round-Ups")
        settings_card.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ttk.Label(settings_card, text="Every time you spend, round the expense up to the "
                                       "nearest amount below and sweep the difference "
                                       "(times the multiplier) into a Round-Up Jar — "
                                       "Acorns/Monzo-style spare-change saving.",
                  style="CardDim.TLabel", wraplength=380, justify="left").pack(anchor="w", pady=(0, 8))

        self.roundup_enabled_var = tk.BooleanVar()
        ttk.Checkbutton(settings_card, text="Enable round-ups", variable=self.roundup_enabled_var).pack(anchor="w")

        row1 = ttk.Frame(settings_card, style="Card.TFrame")
        row1.pack(fill="x", pady=(8, 0))
        ttk.Label(row1, text="Round up to nearest", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        self.roundup_nearest_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.roundup_nearest_var, width=8).grid(row=1, column=0, padx=(0, 12))
        ttk.Label(row1, text="Multiplier", style="CardDim.TLabel").grid(row=0, column=1, sticky="w")
        self.roundup_multiplier_var = tk.StringVar()
        ttk.Combobox(row1, textvariable=self.roundup_multiplier_var,
                     values=["1", "2", "3", "5", "10"], width=6, state="readonly").grid(row=1, column=1)
        ttk.Button(settings_card, text="Save Round-Up Settings", style="Accent.TButton",
                   command=self.save_roundup_settings).pack(anchor="w", pady=(10, 0))

        jar_card = Card(jar_row, title="Round-Up Jar")
        jar_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ttk.Label(jar_card, text="CURRENT BALANCE", style="CardDim.TLabel").pack(anchor="w")
        self.jar_balance_label = ttk.Label(jar_card, text="—", style="Hero.TLabel")
        self.jar_balance_label.pack(anchor="w")
        self.jar_lifetime_label = ttk.Label(jar_card, style="CardDim.TLabel")
        self.jar_lifetime_label.pack(anchor="w", pady=(4, 10))

        sweep_row = ttk.Frame(jar_card, style="Card.TFrame")
        sweep_row.pack(fill="x")
        ttk.Label(sweep_row, text="Sweep jar into", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        self.sweep_target_var = tk.StringVar()
        self.sweep_combo = ttk.Combobox(sweep_row, textvariable=self.sweep_target_var, width=20, state="readonly")
        self.sweep_combo.grid(row=1, column=0, padx=(0, 8))
        ttk.Button(sweep_row, text="Sweep Now", style="Accent.TButton", command=self.sweep_jar).grid(
            row=1, column=1)

        roundup_chart_card = Card(self, title="Round-Ups Over Time (cumulative)")
        roundup_chart_card.pack(fill="both", expand=True, pady=(0, 10))
        self.roundup_canvas = tk.Canvas(roundup_chart_card, height=170, highlightthickness=0, bg=c["card"])
        self.roundup_canvas.pack(fill="both", expand=True)

        # --- Cashback ---
        cb_row = ttk.Frame(self)
        cb_row.pack(fill="x", pady=(0, 10))
        cb_row.columnconfigure(0, weight=1)
        cb_row.columnconfigure(1, weight=1)

        cb_summary = Card(cb_row, title="💳  Cashback Rewards")
        cb_summary.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        ttk.Label(cb_summary, text="LIFETIME EARNED", style="CardDim.TLabel").pack(anchor="w")
        self.cb_lifetime_label = ttk.Label(cb_summary, text="—", style="Hero.TLabel")
        self.cb_lifetime_label.pack(anchor="w")
        self.cb_unredeemed_label = ttk.Label(cb_summary, style="CardDim.TLabel")
        self.cb_unredeemed_label.pack(anchor="w", pady=(4, 10))

        redeem_row = ttk.Frame(cb_summary, style="Card.TFrame")
        redeem_row.pack(fill="x")
        ttk.Label(redeem_row, text="Credit redeemed cashback to", style="CardDim.TLabel").grid(
            row=0, column=0, sticky="w")
        self.redeem_target_var = tk.StringVar()
        self.redeem_combo = ttk.Combobox(redeem_row, textvariable=self.redeem_target_var, width=20,
                                          state="readonly")
        self.redeem_combo.grid(row=1, column=0, padx=(0, 8))
        ttk.Button(redeem_row, text="Redeem Now", style="Accent.TButton", command=self.redeem_cashback).grid(
            row=1, column=1)

        cb_chart_card = Card(cb_row, title="Cashback Earned by Card")
        cb_chart_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.cb_canvas = tk.Canvas(cb_chart_card, height=170, highlightthickness=0, bg=c["card"])
        self.cb_canvas.pack(fill="both", expand=True)

    def save_roundup_settings(self):
        db = self.app.db
        db.set_setting("roundup_enabled", "1" if self.roundup_enabled_var.get() else "0")
        try:
            nearest = float(self.roundup_nearest_var.get())
            if nearest > 0:
                db.set_setting("roundup_nearest", str(nearest))
        except ValueError:
            pass
        mult = self.roundup_multiplier_var.get().strip() or "1"
        db.set_setting("roundup_multiplier", mult)
        self.app.refresh_all()

    def sweep_jar(self):
        db = self.app.db
        jar = db.get_or_create_roundup_jar()
        if jar["balance"] <= 0:
            messagebox.showinfo("Nothing to sweep", "The Round-Up Jar is empty right now.")
            return
        target = self.sweep_targets.get(self.sweep_target_var.get())
        if not target:
            messagebox.showinfo("Choose an account", "Pick an account to sweep the jar into first.")
            return
        db.transfer_between_accounts(jar["id"], target["id"], jar["balance"])
        self.app.refresh_all()

    def redeem_cashback(self):
        db = self.app.db
        unredeemed = db.get_unredeemed_cashback()
        if unredeemed <= 0:
            messagebox.showinfo("Nothing to redeem", "No unredeemed cashback yet.")
            return
        target = self.redeem_targets.get(self.redeem_target_var.get())
        total = db.redeem_cashback(target["id"] if target else None)
        messagebox.showinfo("Redeemed", f"Redeemed {fmt_money(total, self.app.reporting_currency())} of "
                                         f"cashback as income.")
        self.app.refresh_all()

    def refresh(self):
        db = self.app.db
        c = self.app.c
        cur = self.app.reporting_currency()

        self.roundup_enabled_var.set(db.get_setting("roundup_enabled", "0") == "1")
        self.roundup_nearest_var.set(db.get_setting("roundup_nearest", "1"))
        self.roundup_multiplier_var.set(db.get_setting("roundup_multiplier", "1"))

        jar = db.get_or_create_roundup_jar()
        self.jar_balance_label.config(text=fmt_money(jar["balance"], cur))
        self.jar_lifetime_label.config(text=f"{fmt_money(db.total_roundups(), cur)} swept lifetime")

        assets = [a for a in db.list_accounts() if a["kind"] == "asset" and a["subtype"] != "roundup_pot"]
        self.sweep_targets = {a["name"]: a for a in assets}
        self.sweep_combo["values"] = list(self.sweep_targets.keys())

        self.redeem_targets = {a["name"]: a for a in assets}
        self.redeem_combo["values"] = ["(none — just log as income)"] + list(self.redeem_targets.keys())

        self.cb_lifetime_label.config(text=fmt_money(db.total_lifetime_cashback(), cur))
        self.cb_unredeemed_label.config(
            text=f"{fmt_money(db.get_unredeemed_cashback(), cur)} unredeemed right now")

        roundups = db.list_roundups()
        running = 0.0
        values, labels = [], []
        for r in roundups:
            running += r["roundup_amount"]
            values.append(running)
            labels.append(r["date"][5:])
        charts.draw_line_chart(self.roundup_canvas, values, labels, c,
                                unit_fmt=lambda v: f"{v:,.2f}",
                                empty_text="No round-ups yet — enable them above and add an expense.")

        cb_accounts = db.cashback_by_account()
        cats = [row["account_name"] for row in cb_accounts]
        vals = [row["total"] for row in cb_accounts]
        charts.draw_bar_chart(self.cb_canvas, cats, [("Cashback", "good", vals)], c,
                               unit_fmt=lambda v: f"{v:,.2f}")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

class SettingsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        general = Card(self, title="General")
        general.pack(fill="x", pady=(0, 10))

        ttk.Label(general, text="Reporting currency (ISO code)", style="CardDim.TLabel").grid(
            row=0, column=0, sticky="w")
        self.reporting_currency_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.reporting_currency_var, width=10).grid(row=0, column=1, padx=6)

        ttk.Label(general, text="Monthly savings target", style="CardDim.TLabel").grid(
            row=1, column=0, sticky="w")
        self.savings_target_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.savings_target_var, width=10).grid(row=1, column=1, padx=6)

        ttk.Label(general, text="Hourly wage (life-energy view, 0 = off)", style="CardDim.TLabel").grid(
            row=2, column=0, sticky="w")
        self.hourly_wage_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.hourly_wage_var, width=10).grid(row=2, column=1, padx=6)


        ttk.Label(general, text="Appearance", style="CardDim.TLabel").grid(row=3, column=0, sticky="w")
        self.theme_var = tk.StringVar(value=theme.Palette.mode)
        theme_combo = ttk.Combobox(general, textvariable=self.theme_var, values=["dark", "light"],
                                    width=10, state="readonly")
        theme_combo.grid(row=3, column=1, padx=6, sticky="w")

        ttk.Label(general, text="Currency mode", style="CardDim.TLabel").grid(row=4, column=0, sticky="w")
        self.currency_mode_var = tk.StringVar(value=self.app.currency_mode())
        mode_combo = ttk.Combobox(general, textvariable=self.currency_mode_var,
                                   values=["home", "holiday"], width=10, state="readonly")
        mode_combo.grid(row=4, column=1, padx=6, sticky="w")
        ttk.Label(general, wraplength=420, justify="left", style="CardDim.TLabel",
                  text="Home: hides FX rates and per-account currency pickers for everyday single-currency "
                       "use. Holiday: shows full multi-currency controls. Doesn't change your data, only "
                       "what's shown.").grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Label(general, text="Budget alert threshold (% of category budget)",
                  style="CardDim.TLabel").grid(row=6, column=0, sticky="w")
        self.budget_alert_threshold_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.budget_alert_threshold_var, width=10).grid(
            row=6, column=1, padx=6)

        ttk.Label(general, text="Month start day (1 = calendar month)",
                  style="CardDim.TLabel").grid(row=7, column=0, sticky="w")
        self.month_start_day_var = tk.StringVar()
        ttk.Entry(general, textvariable=self.month_start_day_var, width=10).grid(
            row=7, column=1, padx=6)
        ttk.Label(general, wraplength=420, justify="left", style="CardDim.TLabel",
                  text="e.g. 25 if you're paid on the 25th — the Dashboard/Budgets/Insights "
                       "\"month\" then runs 25th-24th instead of the 1st-end of the calendar "
                       "month. Doesn't affect when bills are due or the UK tax year."
                  ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(2, 0))

        ttk.Button(general, text="Save Settings", style="Accent.TButton",
                   command=self.save_settings).grid(row=9, column=0, pady=10, sticky="w")

        profile_card = Card(self, title="Profile")
        profile_card.pack(fill="x", pady=(0, 10))
        self.signed_in_label = ttk.Label(
            profile_card, text=f"Signed in as: {self.app.profile['name']}", style="Card.TLabel")
        self.signed_in_label.pack(anchor="w")
        btn_row = ttk.Frame(profile_card, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Rename Profile…", command=self.rename_profile).pack(side="left")
        ttk.Button(btn_row, text="Switch Profile", command=self.app.switch_profile).pack(
            side="left", padx=6)

        # Progressive disclosure: General/Profile above are what you touch
        # day to day; everything below is power-user configuration, tucked
        # behind an explicit expand instead of always taking up space.
        self._advanced_expanded = False
        self.advanced_toggle_btn = ttk.Button(self, text="▸ Advanced Settings",
                                               command=self._toggle_advanced)
        self.advanced_toggle_btn.pack(anchor="w", pady=(0, 10))
        self.advanced_container = ttk.Frame(self)

        self.fx_frame = Card(self.advanced_container,
                              title="FX Rates (1 unit of currency = X reporting currency)")
        fx_frame = self.fx_frame
        self._fx_visible = self.app.currency_mode() == "holiday"
        if self._fx_visible:
            fx_frame.pack(fill="x", pady=(0, 10))

        self.fx_currency_var = tk.StringVar()
        self.fx_rate_var = tk.StringVar()
        ttk.Label(fx_frame, text="Currency code", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(fx_frame, textvariable=self.fx_currency_var, width=8).grid(row=1, column=0, padx=4)
        ttk.Label(fx_frame, text="Rate to reporting currency", style="CardDim.TLabel").grid(
            row=0, column=1, sticky="w")
        ttk.Entry(fx_frame, textvariable=self.fx_rate_var, width=12).grid(row=1, column=1, padx=4)
        ttk.Button(fx_frame, text="Set Rate", command=self.set_fx_rate).grid(row=1, column=2, padx=8)

        c = self.app.c
        self.fx_list = tk.Text(fx_frame, height=6, width=50, bg=c["card"], fg=c["text"],
                                relief="flat", font=theme.Fonts.body)
        self.fx_list.grid(row=2, column=0, columnspan=3, pady=6, sticky="w")

        nav_card = Card(self.advanced_container, title="Customize Navigation")
        nav_card._settings_role = "nav_card"
        nav_card.pack(fill="x", pady=(0, 10))
        ttk.Label(nav_card, text="Hide tabs you don't use — Dashboard and Settings always stay.",
                  style="CardDim.TLabel").pack(anchor="w")
        nav_checks_frame = ttk.Frame(nav_card, style="Card.TFrame")
        nav_checks_frame.pack(fill="x", pady=(6, 0))
        self.nav_visibility_vars = {}
        hideable_items = [item for item in NAV_ITEMS if item[0] not in PROTECTED_NAV_KEYS]
        for i, (key, icon, label) in enumerate(hideable_items):
            var = tk.BooleanVar(value=True)
            self.nav_visibility_vars[key] = var
            ttk.Checkbutton(nav_checks_frame, text=f"{icon} {label}", variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)
        ttk.Button(nav_card, text="Save Navigation", style="Accent.TButton",
                   command=self.save_nav_visibility).pack(anchor="w", pady=(8, 0))

        dashboard_card = Card(self.advanced_container, title="Customize Dashboard")
        dashboard_card.pack(fill="x", pady=(0, 10))
        ttk.Label(dashboard_card, text="Show/hide Dashboard sections — drag their grip "
                                        "handle (⠿) on the Dashboard itself to reorder them.",
                  style="CardDim.TLabel").pack(anchor="w")
        dashboard_checks_frame = ttk.Frame(dashboard_card, style="Card.TFrame")
        dashboard_checks_frame.pack(fill="x", pady=(6, 0))
        self.dashboard_visibility_vars = {}
        for i, (key, label) in enumerate(DASHBOARD_SECTIONS):
            var = tk.BooleanVar(value=True)
            self.dashboard_visibility_vars[key] = var
            ttk.Checkbutton(dashboard_checks_frame, text=label, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)
        ttk.Button(dashboard_card, text="Save Dashboard Layout", style="Accent.TButton",
                   command=self.save_dashboard_visibility).pack(anchor="w", pady=(8, 0))

        ignored_subs_card = Card(self.advanced_container, title="Ignored Subscriptions")
        ignored_subs_card.pack(fill="x", pady=(0, 10))
        ttk.Label(ignored_subs_card,
                  text="Dismissed from the Recurring tab's Detected Subscriptions list.",
                  style="CardDim.TLabel").pack(anchor="w")
        self.ignored_subs_count_label = ttk.Label(ignored_subs_card, text="", style="Card.TLabel")
        self.ignored_subs_count_label.pack(anchor="w", pady=(6, 0))
        ttk.Button(ignored_subs_card, text="Manage Ignored Subscriptions…",
                   command=self.open_ignored_subscriptions_window).pack(anchor="w", pady=(6, 0))

        data_files_card = Card(self.advanced_container, title="Data Files")
        data_files_card.pack(fill="x", pady=(0, 10))
        ttk.Label(data_files_card, wraplength=760, justify="left", style="CardDim.TLabel",
                  text="Every profile has its own folder with editable CSV files — "
                       "transactions.csv, accounts.csv, categories.csv — for quick "
                       "bulk edits or loading historical data outside the app. Nothing here happens "
                       "automatically: Refresh writes the files, Apply reads them back in."
                  ).pack(anchor="w")
        df_btn_row = ttk.Frame(data_files_card, style="Card.TFrame")
        df_btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(df_btn_row, text="Refresh CSVs from App", command=self.refresh_csvs).pack(side="left")
        ttk.Button(df_btn_row, text="Apply Changes from CSVs…", style="Accent.TButton",
                   command=self.apply_csvs).pack(side="left", padx=6)
        ttk.Button(df_btn_row, text="Open Profile Folder",
                   command=self.open_profile_folder).pack(side="left", padx=6)
        ttk.Label(data_files_card, wraplength=760, justify="left", style="CardDim.TLabel",
                  text="Transfers, reconciled transactions, and split transactions show up for "
                       "reference but are protected — edit those from the app itself. Every Apply "
                       "backs up the database first (kept in a csv_sync_backups subfolder)."
                  ).pack(anchor="w", pady=(6, 0))

        self.note_label = ttk.Label(
            self, wraplength=800, justify="left",
            text="Everything is stored locally per profile in the 'Profiles' folder "
                 "next to the app — "
                 "local-first storage, no network calls. If you ever sync these files "
                 "to the cloud, encrypt them first.",
            style="Dim.TLabel")
        self.note_label.pack(fill="x", pady=8)

    def _toggle_advanced(self):
        self._advanced_expanded = not self._advanced_expanded
        if self._advanced_expanded:
            self.advanced_container.pack(fill="x", before=self.note_label)
            self.advanced_toggle_btn.config(text="▾ Advanced Settings")
        else:
            self.advanced_container.pack_forget()
            self.advanced_toggle_btn.config(text="▸ Advanced Settings")

    def refresh_csvs(self):
        profile_dir = profiles.profile_dir_for(self.app.profile["slug"])
        refresh_profile_csvs(self.app.db, profile_dir)
        messagebox.showinfo("Refreshed", f"CSV files updated in:\n{profile_dir}")

    def apply_csvs(self):
        profile_dir = profiles.profile_dir_for(self.app.profile["slug"])
        if not messagebox.askyesno(
                "Apply Changes from CSVs",
                "This reads transactions.csv, accounts.csv, and categories.csv "
                "from your profile folder and applies any adds/edits/deletes back into the app. "
                "Your database is backed up first. Continue?"):
            return
        db_path = profiles.db_path_for(self.app.profile["slug"])
        result = apply_profile_csvs(self.app.db, profile_dir, db_path)

        lines = [f"Added: {result['added']}", f"Edited: {result['edited']}",
                 f"Deleted: {result['deleted']}"]
        if result["skipped"]:
            lines.append(f"\nSkipped {len(result['skipped'])} row(s):")
            for s in result["skipped"][:15]:
                lines.append(f"  [{s['file']}] id={s['id'] or '(new)'}: {s['reason']}")
            if len(result["skipped"]) > 15:
                lines.append(f"  …and {len(result['skipped']) - 15} more")
        lines.append(f"\nBackup saved to:\n{result['backup_path']}")
        messagebox.showinfo("Sync complete", "\n".join(lines))
        self.app.refresh_all()

    def open_profile_folder(self):
        profile_dir = profiles.profile_dir_for(self.app.profile["slug"])
        if sys.platform == "win32":
            os.startfile(profile_dir)
        else:
            import subprocess
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", profile_dir])

    def rename_profile(self):
        new_name = simpledialog.askstring(
            "Rename Profile", "New name for this profile:",
            initialvalue=self.app.profile["name"], parent=self)
        if new_name is None:
            return
        self.app.rename_profile(new_name)

    def save_settings(self):
        db = self.app.db
        old_month_start_day = db.get_setting("month_start_day", "1")
        db.set_setting("reporting_currency", self.reporting_currency_var.get().strip().upper() or "GBP")
        try:
            float(self.savings_target_var.get())
            db.set_setting("monthly_savings_target", self.savings_target_var.get())
        except ValueError:
            pass
        try:
            float(self.hourly_wage_var.get())
            db.set_setting("hourly_wage", self.hourly_wage_var.get())
        except ValueError:
            pass
        try:
            float(self.budget_alert_threshold_var.get())
            db.set_setting("budget_alert_threshold_pct", self.budget_alert_threshold_var.get())
        except ValueError:
            pass
        try:
            day = int(self.month_start_day_var.get())
            if 1 <= day <= 28:
                db.set_setting("month_start_day", str(day))
        except ValueError:
            pass
        old_mode = db.get_setting("theme_mode", "dark")
        db.set_setting("theme_mode", self.theme_var.get())
        db.set_setting("currency_mode", self.currency_mode_var.get())
        if db.get_setting("month_start_day", "1") != old_month_start_day:
            # The current view was anchored under the old period definition --
            # re-anchor it to today's period under the new one, same as goto_today().
            self.app.view_year, self.app.view_month = custom_month_for_date(db, self.app.today)
        self.app.refresh_all()
        if self.theme_var.get() != old_mode:
            messagebox.showinfo("Theme changed", "Restart The Ledger to fully apply the new theme.")

    def save_nav_visibility(self):
        hidden = {key for key, var in self.nav_visibility_vars.items() if not var.get()}
        set_hidden_nav_tabs(self.app.db, hidden)
        self.app._build_nav_buttons()
        if getattr(self.app, "current_page", None) in hidden:
            self.app.show_page("dashboard")

    def save_dashboard_visibility(self):
        db = self.app.db
        layout = resolve_dashboard_layout(db)
        visibility = {key: var.get() for key, var in self.dashboard_visibility_vars.items()}
        new_layout = [{"key": e["key"], "visible": visibility[e["key"]]} for e in layout]
        db.set_dashboard_layout(new_layout)
        self.app.refresh_all()

    def set_fx_rate(self):
        code = self.fx_currency_var.get().strip().upper()
        try:
            rate = float(self.fx_rate_var.get())
        except ValueError:
            messagebox.showerror("Error", "Rate must be a number.")
            return
        if not code:
            return
        self.app.db.set_fx_rate(code, rate)
        self.fx_currency_var.set("")
        self.fx_rate_var.set("")
        self.refresh()

    def refresh(self):
        db = self.app.db
        self.reporting_currency_var.set(db.get_setting("reporting_currency", "GBP"))
        self.savings_target_var.set(db.get_setting("monthly_savings_target", "0"))
        self.hourly_wage_var.set(db.get_setting("hourly_wage", "0"))
        self.budget_alert_threshold_var.set(db.get_setting("budget_alert_threshold_pct", "80"))
        self.month_start_day_var.set(db.get_setting("month_start_day", "1"))
        self.currency_mode_var.set(self.app.currency_mode())

        hidden_now = get_hidden_nav_tabs(db)
        for key, var in self.nav_visibility_vars.items():
            var.set(key not in hidden_now)

        dashboard_layout_now = resolve_dashboard_layout(db)
        for entry in dashboard_layout_now:
            if entry["key"] in self.dashboard_visibility_vars:
                self.dashboard_visibility_vars[entry["key"]].set(entry["visible"])

        self.signed_in_label.config(text=f"Signed in as: {self.app.profile['name']}")

        ignored_count = len(db.list_ignored_subscriptions())
        self.ignored_subs_count_label.config(
            text="None ignored." if not ignored_count else f"{ignored_count} ignored.")

        if self.app.currency_mode() == "holiday":
            if not self._fx_visible:
                self.fx_frame.pack(fill="x", pady=(0, 10), before=self._after_fx_widget())
                self._fx_visible = True
        else:
            self.fx_frame.pack_forget()
            self._fx_visible = False

        rates = db.get_fx_rates()
        self.fx_list.config(state="normal")
        self.fx_list.delete("1.0", "end")
        for code, rate in rates.items():
            self.fx_list.insert("end", f"{code}: 1 {code} = {rate} {self.reporting_currency_var.get()}\n")
        self.fx_list.config(state="disabled")

    def open_ignored_subscriptions_window(self):
        win, content = make_scrollable_toplevel(self, "Ignored Subscriptions", "520x600")

        ttk.Label(content, wraplength=420, justify="left", style="TLabel",
                  text="Dismissed from the Recurring tab's Detected Subscriptions list — "
                       "deleting one here lets it resurface as a suggestion again, and can be "
                       "undone from Recently Deleted below."
                  ).pack(anchor="w", padx=14, pady=(14, 8))

        list_frame = ttk.Frame(content)
        list_frame.pack(fill="both", expand=True, padx=14)

        ttk.Separator(content).pack(fill="x", padx=14, pady=10)

        ttk.Label(content, text="Recently Deleted", style="H2.TLabel").pack(anchor="w", padx=14)
        deleted_frame = ttk.Frame(content)
        deleted_frame.pack(fill="both", expand=True, padx=14, pady=(4, 14))

        def render():
            for w in list_frame.winfo_children():
                w.destroy()
            ignored = self.app.db.list_ignored_subscriptions()
            if not ignored:
                ttk.Label(list_frame, text="None ignored.", style="TLabel").pack(anchor="w")
            for row in ignored:
                r = ttk.Frame(list_frame)
                r.pack(fill="x", pady=2)
                ttk.Label(r, text=f"{row['payee']} (dismissed {row['dismissed_date']})",
                          style="TLabel").pack(side="left")
                ttk.Button(r, text="Delete",
                           command=lambda p=row["payee"]: do_delete(p)).pack(side="right")

            for w in deleted_frame.winfo_children():
                w.destroy()
            deleted = self.app.db.list_recently_deleted_ignored_subscriptions()
            if not deleted:
                ttk.Label(deleted_frame, text="Nothing deleted.", style="CardDim.TLabel").pack(anchor="w")
            for row in deleted:
                r = ttk.Frame(deleted_frame)
                r.pack(fill="x", pady=2)
                ttk.Label(r, text=f"{row['payee']} (deleted {row['deleted_at']})",
                          style="CardDim.TLabel").pack(side="left")
                ttk.Button(r, text="Restore",
                           command=lambda p=row["payee"]: do_restore(p)).pack(side="right")

        def do_delete(payee):
            if not messagebox.askyesno("Delete", f"Stop ignoring '{payee}'? It can be restored "
                                        "afterward from Recently Deleted if you change your mind."):
                return
            self.app.db.remove_ignored_subscription(payee)
            self.app.refresh_all()
            render()

        def do_restore(payee):
            self.app.db.restore_ignored_subscription(payee)
            self.app.refresh_all()
            render()

        render()

    def _after_fx_widget(self):
        """The widget immediately after the FX card's usual slot within
        advanced_container, so re-showing it in holiday mode restores the
        original stacking order instead of appending it below Data Files."""
        for child in self.advanced_container.pack_slaves():
            if getattr(child, "_settings_role", None) == "nav_card":
                return child
        return None


if __name__ == "__main__":
    launcher = ProfileLauncher()
    launcher.mainloop()
