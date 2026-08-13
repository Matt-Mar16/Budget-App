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

Feature list (mapped to Part XII of the original research, plus additions):
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
13. Light gamification (streaks/check-ins)                  -> Dashboard
14. Low-friction "set once, check monthly" mode              -> whole app is check-in based
15. Local-first storage (SQLite file per profile)            -> finance_core.Database
16. Multiple user profiles, each fully isolated              -> profiles.py + launcher screen
17. Recurring bills / paychecks, auto-posted on open         -> Recurring tab
18. CSV export                                               -> Transactions tab
19. Dark / light theme                                       -> Settings tab
20. Trend & allocation charts (net worth, income vs. expense, envelope split)
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import csv
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
    net_worth_breakdown, credit_utilization, investment_summary,
    upcoming_card_payments, investment_projection, investment_projection_with_bands,
    budget_run_rate, categories_over_threshold, top_payees, daily_spend_totals,
    detect_recurring_candidates, refresh_profile_csvs, apply_profile_csvs,
    income_by_category,
)
import profiles
import theme
import charts

APP_TITLE = "The Ledger"

CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "JPY": "¥", "AUD": "A$",
                     "CAD": "C$", "CHF": "CHF", "NZD": "NZ$", "INR": "₹"}


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

        super().__init__(canvas, padding=(0, 0, 12, 12))
        window_id = canvas.create_window((0, 0), window=self, anchor="nw")

        self.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    def grid(self, **kw):
        self.wrapper.grid(**kw)

    def tkraise(self, *args, **kw):
        self.wrapper.tkraise(*args, **kw)


def metric_cell(parent, title):
    cell = Card(parent, title="")
    ttk.Label(cell, text=title, style="CardDim.TLabel").pack(anchor="w")
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
        ttk.Button(new_row, text="+ Create Profile", style="Accent.TButton",
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
        if profile.get("locked"):
            password = simpledialog.askstring(
                "Locked profile", f"Enter the password for '{profile['name']}':",
                show="*", parent=self)
            if not password:
                return
            try:
                profiles.unlock_profile(profile["slug"], password)
            except RuntimeError as e:
                messagebox.showerror("Couldn't unlock", str(e))
                return
            profile = next((p for p in profiles.list_profiles() if p["slug"] == profile["slug"]), profile)
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
    ]),
    ("Planning", [
        ("recurring", "🔁", "Recurring"),
        ("debt", "📉", "Debt Planner"),
        ("networth", "📈", "Net Worth / FI"),
        ("investments", "📊", "Investments"),
        ("tax", "🧮", "Tax"),
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


class App(tk.Tk):
    def __init__(self, profile):
        super().__init__()
        self.profile = profile
        self.title(f"{APP_TITLE} — {profile['name']}")
        self.geometry("1220x760")
        self.minsize(980, 620)

        self.db = Database(profiles.db_path_for(profile["slug"]))
        self.today = datetime.date.today()
        self.view_year = self.today.year
        self.view_month = self.today.month

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
            "networth": NetWorthTab(self.container, self),
            "investments": InvestmentsTab(self.container, self),
            "tax": TaxTab(self.container, self),
            "insights": InsightsTab(self.container, self),
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
        self.month_label.configure(
            text=datetime.date(self.view_year, self.view_month, 1).strftime("%B %Y"))

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
        self.view_year, self.view_month = self.today.year, self.today.month
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
        # Safe-to-spend hero
        hero = Card(self, title="")
        hero.pack(fill="x", pady=(0, 10))
        ttk.Label(hero, text="SAFE TO SPEND / DAY", style="CardDim.TLabel").pack(anchor="w")
        self.safe_to_spend_label = ttk.Label(hero, text="—", style="Hero.TLabel")
        self.safe_to_spend_label.pack(anchor="w")
        self.safe_to_spend_sub = ttk.Label(hero, text="", style="CardDim.TLabel")
        self.safe_to_spend_sub.pack(anchor="w", pady=(4, 0))

        # Metrics grid
        grid = ttk.Frame(self)
        grid.pack(fill="x", pady=(0, 10))
        self.metric_labels = {}
        metrics = ["Savings Rate", "Emergency Fund", "Debt-to-Income",
                   "Housing Ratio", "Income (mo.)", "Expenses (mo.)"]
        for i, m in enumerate(metrics):
            cell, val = metric_cell(grid, m)
            cell.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            grid.columnconfigure(i % 3, weight=1)
            self.metric_labels[m] = val

        # Charts row: allocation donut + 6-month trend bar chart
        charts_row = ttk.Frame(self)
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

        # Flags panel
        flags_card = Card(self, title="Flags & Nudges")
        flags_card.pack(fill="both", expand=True)
        self.flags_text = tk.Text(flags_card, wrap="word", state="disabled", height=10,
                                   bg=c["card"], fg=c["text"], insertbackground=c["text"],
                                   relief="flat", font=theme.Fonts.body, padx=4, pady=4)
        self.flags_text.pack(fill="both", expand=True)
        self.flags_text.tag_configure("warn", foreground=c["warn"])
        self.flags_text.tag_configure("good", foreground=c["good"])
        self.flags_text.tag_configure("info", foreground=c["accent"])

    def refresh(self):
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

        self.metric_labels["Savings Rate"].config(text=fmt_pct(sr))
        self.metric_labels["Emergency Fund"].config(text=(f"{ef:,.1f} mo" if ef is not None else "n/a"))
        self.metric_labels["Debt-to-Income"].config(text=(fmt_pct(dti) if dti is not None else "n/a"))
        self.metric_labels["Housing Ratio"].config(text=(fmt_pct(hr) if hr is not None else "n/a"))
        self.metric_labels["Income (mo.)"].config(text=fmt_money(income, cur))
        self.metric_labels["Expenses (mo.)"].config(text=fmt_money(expenses, cur))

        # donut: need/want/saving split
        kind_spend = spend_by_kind(db, y, m)
        segments = [
            ("Needs", kind_spend["need"], c["accent"]),
            ("Wants", kind_spend["want"], c["warn"]),
            ("Saving", kind_spend["saving"], c["good"]),
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
            lines.append(("warn", f"⚠ Savings rate is {fmt_pct(sr)} — below the 10% baseline."))
        elif sr < 0.15:
            lines.append(("info", f"ℹ Savings rate is {fmt_pct(sr)} — acceptable, aim for 15–20%+."))
        else:
            lines.append(("good", f"✓ Savings rate is {fmt_pct(sr)} — at or above the recommended range."))

        if target > 0 and savings < target:
            lines.append(("warn", f"⚠ Monthly savings target of {fmt_money(target, cur)} not yet met "
                                   f"({fmt_money(savings, cur)} recorded in saving categories)."))

        if ef is not None:
            if ef < 3:
                lines.append(("warn", f"⚠ Emergency fund covers {ef:,.1f} months — build toward 3–6 minimum."))
            else:
                lines.append(("good", f"✓ Emergency fund covers {ef:,.1f} months of essentials."))

        if dti is not None and dti > 0.36:
            lines.append(("warn", f"⚠ Debt-to-income is {fmt_pct(dti)} — above the 36% healthy threshold."))

        threshold_pct = db.get_setting_float("budget_alert_threshold_pct", 80.0)
        for row in categories_over_threshold(db, y, m, threshold_pct=threshold_pct):
            if row["over"]:
                lines.append(("warn", f"⚠ '{row['category']['name']}' is over budget: "
                                       f"{fmt_money(row['spent'], cur)} / {fmt_money(row['budget'], cur)}."))
            else:
                lines.append(("info", f"ℹ '{row['category']['name']}' has reached {fmt_pct(row['pct'])} "
                                       f"of its {fmt_money(row['budget'], cur)} budget."))

        idle = idle_cash_nudge(db, y, m)
        if idle:
            lines.append(("info", f"💡 ~{fmt_money(idle, cur)} sits idle above your buffer — "
                                   f"consider investing it or extra debt payoff."))

        for card in credit_utilization(db):
            util = card["utilization"]
            if util >= 0.70:
                lines.append(("warn", f"⚠ '{card['account']['name']}' is at {util*100:,.0f}% utilization "
                                       f"({fmt_money(card['balance'], cur)} / {fmt_money(card['limit'], cur)}) — "
                                       f"high utilization can hurt your credit score; aim to keep it under 30%."))

        for due in upcoming_card_payments(db, within_days=7, today=self.app.today):
            lines.append(("warn", f"💳 '{due['account']['name']}' payment of {fmt_money(due['balance'], cur)} "
                                   f"is due {due['due_date']}."))

        unredeemed = db.get_unredeemed_cashback()
        if unredeemed >= 5:
            lines.append(("info", f"💳 You have {fmt_money(unredeemed, cur)} unredeemed cashback — "
                                   f"redeem it on the Rewards tab whenever you like."))

        jar = db.get_or_create_roundup_jar()
        if jar["balance"] >= 10:
            lines.append(("info", f"🐷 Your Round-Up Jar has {fmt_money(jar['balance'], cur)} in it — "
                                   f"sweep it into savings or investing on the Rewards tab."))

        bills = upcoming_bills(db, within_days=14, today=self.app.today)
        for b in bills[:4]:
            lines.append(("info", f"📅 '{b['name']}' ({fmt_money(b['amount'], cur)}) is due {b['next_date']}."))

        for f in lifestyle_inflation_flags(db, y, m)[:4]:
            lines.append(("warn", f"⚠ Lifestyle inflation: '{f['category']}' grew {fmt_pct(f['growth'])} "
                                   f"vs. {fmt_pct(f['income_growth'])} income growth."))

        for a in category_anomalies(db)[:4]:
            t = a["transaction"]
            lines.append(("info", f"🔍 Anomaly: {t['payee'] or t['category_name']} on {t['date']} was "
                                   f"{fmt_money(a['amount'], cur)} — above its usual average."))

        if not lines:
            lines.append(("good", "Nothing flagged this month. Looking healthy."))

        self.flags_text.config(state="normal")
        self.flags_text.delete("1.0", "end")
        for i, (tag, text) in enumerate(lines):
            if i:
                self.flags_text.insert("end", "\n\n")
            self.flags_text.insert("end", text, tag)
        self.flags_text.config(state="disabled")


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

    win = tk.Toplevel(parent)
    win.title("Edit Transaction")
    win.configure(bg=app.c["bg"])
    win.geometry("380x420")

    cats = db.list_categories()
    cat_names = [c["name"] for c in cats]
    cat_id_by_name = {c["name"]: c["id"] for c in cats}
    cat_name_by_id = {c["id"]: c["name"] for c in cats}

    accounts = [a for a in db.list_accounts() if a["subtype"] != "roundup_pot"]
    acc_names = [a["name"] for a in accounts]
    acc_id_by_name = {a["name"]: a["id"] for a in accounts}
    acc_name_by_id = {a["id"]: a["name"] for a in accounts}

    if tx["reconciled"]:
        ttk.Label(win, text="🔒 This transaction is reconciled/locked.",
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

    fields = [
        ("Date (YYYY-MM-DD)", date_var, None),
        ("Payee", payee_var, None),
        ("Category", category_var, [""] + cat_names),
        ("Amount (+income / -expense)", amount_var, None),
        ("Currency", currency_var, None),
        ("Note", note_var, None),
        ("Paid from", account_var, [""] + acc_names),
        ("Tags (comma-separated)", tags_var, None),
    ]
    for label, var, options in fields:
        ttk.Label(win, text=label, style="TLabel").pack(anchor="w", padx=14, pady=(8, 2))
        if options is not None:
            ttk.Combobox(win, textvariable=var, values=options, state="readonly").pack(
                fill="x", padx=14)
        else:
            ttk.Entry(win, textvariable=var).pack(fill="x", padx=14)

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

        try:
            db.update_transaction(
                tx_id, date=date_var.get().strip(), payee=payee_var.get().strip(),
                category_id=category_id, amount=amount, currency=currency,
                note=note_var.get().strip(), account_id=account_id,
            )
        except ReconciledTransactionError:
            if messagebox.askyesno(
                    "Reconciled transaction",
                    "This transaction is reconciled/locked. Unreconcile and save the edit anyway?"):
                db.update_transaction(
                    tx_id, date=date_var.get().strip(), payee=payee_var.get().strip(),
                    category_id=category_id, amount=amount, currency=currency,
                    note=note_var.get().strip(), account_id=account_id,
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

    btn_row = ttk.Frame(win)
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

        ttk.Button(form, text="Add", style="Accent.TButton", command=self.add_transaction).grid(
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

        win = tk.Toplevel(self)
        win.title("Mark as Owed")
        win.geometry("320x220")
        win.configure(bg=theme.Palette.c["bg"])

        ttk.Label(win, text=f"{tx['payee'] or '(no payee)'} — {fmt_money(tx['amount'], tx['currency'])}",
                  style="H2.TLabel", wraplength=280, justify="left").pack(anchor="w", padx=12, pady=(12, 8))

        ttk.Label(win, text="Owed by", style="TLabel").pack(anchor="w", padx=12)
        owed_by_var = tk.StringVar()
        ttk.Entry(win, textvariable=owed_by_var).pack(fill="x", padx=12)

        ttk.Label(win, text="Amount owed", style="TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        amount_var = tk.StringVar(value=f"{abs(tx['amount']):.2f}")
        ttk.Entry(win, textvariable=amount_var).pack(fill="x", padx=12)

        ttk.Label(win, text="Note", style="TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        note_var = tk.StringVar()
        ttk.Entry(win, textvariable=note_var).pack(fill="x", padx=12)

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

        ttk.Button(win, text="Save", style="Accent.TButton", command=do_save).pack(pady=14)

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

    def refresh(self):
        cats = self.app.db.list_categories()
        self.categories_by_name = {c["name"]: c["id"] for c in cats}
        self.category_combo["values"] = list(self.categories_by_name.keys())

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
        for t in all_txs:
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
            self.tree.insert("", "end", iid=str(t["id"]), values=(
                t["date"], t["payee"] or "", category_label,
                f"{t['amount']:,.2f}", t["currency"],
                f"{reporting_amt:,.2f}", t["account_name"] or "", t["note"] or "",
                tags_label, "🔒" if t["reconciled"] else ""
            ))

        self._refresh_reimbursements()

    def add_transaction(self):
        date = self.date_var.get().strip()
        payee = self.payee_var.get().strip()
        cat_name = self.category_var.get().strip()
        amount_raw = self.amount_var.get().strip()
        currency = self.currency_var.get().strip().upper() or self.app.reporting_currency()
        note = self.note_var.get().strip()

        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            messagebox.showerror("Invalid date", "Please use YYYY-MM-DD format.")
            return
        try:
            amount = float(amount_raw)
        except ValueError:
            messagebox.showerror("Invalid amount", "Amount must be a number (negative for expenses).")
            return

        cat_id = self.categories_by_name.get(cat_name)
        account = self.accounts_by_name.get(self.account_var.get().strip())
        account_id = account["id"] if account else None

        if cat_id and amount < 0:
            from finance_core import would_exceed_budget
            exceeds, spent_after, budget = would_exceed_budget(self.app.db, cat_id, amount, currency)
            if exceeds:
                cur = self.app.reporting_currency()
                proceed = messagebox.askyesno(
                    "Over budget",
                    f"This would bring '{cat_name}' spending to {fmt_money(spent_after, cur)}, "
                    f"over its {fmt_money(budget, cur)} monthly budget. Add it anyway?")
                if not proceed:
                    return

        tx_id = self.app.db.add_transaction(date, payee, cat_id, amount, currency, note, account_id=account_id)
        tag_names = [t.strip() for t in self.tags_var.get().split(",") if t.strip()]
        if tag_names:
            self.app.db.set_transaction_tags(tx_id, tag_names)
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

        win = tk.Toplevel(self)
        win.title(f"Split — {tx['payee'] or '(no payee)'}")
        win.geometry("520x380")
        c = theme.Palette.c
        win.configure(bg=c["bg"])

        ttk.Label(win, text=f"Total: {fmt_money(tx['amount'], tx['currency'])} — splits must add up "
                             "to exactly this (money moved doesn't change, only how it's categorized).",
                  style="H2.TLabel", wraplength=480, justify="left").pack(anchor="w", padx=10, pady=(10, 6))

        rows_frame = ttk.Frame(win)
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

        ttk.Button(win, text="+ Add Row", command=lambda: add_row()).pack(anchor="w", padx=10, pady=(6, 0))

        btns = ttk.Frame(win)
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

        win = tk.Toplevel(self)
        win.title("Import preview")
        win.geometry("760x420")
        c = theme.Palette.c
        win.configure(bg=c["bg"])

        n_ok = sum(1 for r in rows if r["parsed_ok"])
        n_bad = len(rows) - n_ok
        n_dup = sum(1 for r in rows if r["likely_duplicate"])
        ttk.Label(win, text=f"{len(rows)} rows found — {n_ok} look valid, {n_bad} have problems, "
                             f"{n_dup} look like duplicates of transactions you already have.",
                  style="H2.TLabel").pack(anchor="w", padx=10, pady=(10, 4))
        if n_dup:
            ttk.Label(win, wraplength=740, justify="left", style="Dim.TLabel",
                      text="Likely-duplicate rows are pre-selected below and will be skipped on Commit. "
                           "Click a row to un-select it if it's a genuine second charge (e.g. two identical "
                           "coffees the same day) rather than an actual duplicate."
                      ).pack(anchor="w", padx=10, pady=(0, 4))

        cols = ("row", "date", "payee", "amount", "status", "dup")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14, selectmode="extended")
        for col, w, title in zip(cols, (45, 90, 190, 90, 200, 110),
                                  ("Row", "Date", "Payee", "Amount", "Status", "Duplicate?")):
            tree.heading(col, text=title)
            tree.column(col, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=10)
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

        btns = ttk.Frame(win)
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
        ttk.Button(add_frame, text="Add Category", style="Accent.TButton",
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

        groups = {"need": [], "want": [], "saving": [], "income": []}
        for cat in db.list_categories():
            groups[cat["kind"]].append(cat)
        income_totals = {r["category_id"]: r["total"] for r in income_by_category(db, y, m)}

        titles = {"need": "Needs (50%)", "want": "Wants (30%)", "saving": "Savings/Debt (20%)"}
        col = 0
        for kind in ("need", "want", "saving"):
            frame = Card(self.canvas_frame, title=titles[kind])
            frame.grid(row=0, column=col, sticky="nsew", padx=6)
            self.canvas_frame.columnconfigure(col, weight=1)
            col += 1
            for cat in groups[kind]:
                spent = spend_by_cat.get(cat["id"], 0.0)
                budget = cat["monthly_budget"] or 0.0
                row = ttk.Frame(frame, style="Card.TFrame")
                row.pack(fill="x", pady=5)
                label_text = f"{cat['name']}: {fmt_money(spent, cur)}"
                if budget > 0:
                    label_text += f" / {fmt_money(budget, cur)}"
                ttk.Label(row, text=label_text, style="Card.TLabel").pack(anchor="w")

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

        income_frame = Card(self.canvas_frame, title="Income")
        income_frame.grid(row=0, column=col, sticky="nsew", padx=6)
        self.canvas_frame.columnconfigure(col, weight=1)
        if not groups["income"]:
            ttk.Label(income_frame, text="No income categories yet.",
                      style="CardDim.TLabel").pack(anchor="w")
        for cat in groups["income"]:
            total = income_totals.get(cat["id"], 0.0)
            row = ttk.Frame(income_frame, style="Card.TFrame")
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=f"{cat['name']}: {fmt_money(total, cur)}",
                      style="Card.TLabel").pack(side="left")
            ttk.Button(row, text="Delete",
                       command=lambda cid=cat["id"], name=cat["name"]:
                           self._delete_category(cid, name)).pack(side="right")

    def _set_budget(self, cat_id, var):
        try:
            val = float(var.get())
        except ValueError:
            return
        self.app.db.set_category_budget(cat_id, val)
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

        form = Card(self, title="Add Recurring Item (bill or paycheck)")
        form.pack(fill="x", pady=(0, 10))

        self.name_var = tk.StringVar()
        self.payee_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.amount_var = tk.StringVar()
        self.currency_var = tk.StringVar(value=self.app.reporting_currency())
        self.freq_var = tk.StringVar(value="monthly")
        self.next_date_var = tk.StringVar(value=self.app.today.isoformat())

        labels = ["Name", "Payee", "Category", "Amount (+/-)", "Currency", "Frequency", "Next Date", "Account"]
        for i, lbl in enumerate(labels):
            ttk.Label(form, text=lbl, style="CardDim.TLabel").grid(row=0, column=i, sticky="w", padx=3)

        ttk.Entry(form, textvariable=self.name_var, width=16).grid(row=1, column=0, padx=3)
        ttk.Entry(form, textvariable=self.payee_var, width=14).grid(row=1, column=1, padx=3)
        self.category_combo = ttk.Combobox(form, textvariable=self.category_var, width=14, state="readonly")
        self.category_combo.grid(row=1, column=2, padx=3)
        ttk.Entry(form, textvariable=self.amount_var, width=10).grid(row=1, column=3, padx=3)
        ttk.Entry(form, textvariable=self.currency_var, width=6).grid(row=1, column=4, padx=3)
        ttk.Combobox(form, textvariable=self.freq_var, values=["weekly", "monthly", "yearly"],
                     width=10, state="readonly").grid(row=1, column=5, padx=3)
        ttk.Entry(form, textvariable=self.next_date_var, width=12).grid(row=1, column=6, padx=3)
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(form, textvariable=self.account_var, width=14, state="readonly")
        self.account_combo.grid(row=1, column=7, padx=3)
        ttk.Button(form, text="Add", style="Accent.TButton", command=self.add_recurring).grid(
            row=1, column=8, padx=8)

        list_card = Card(self, title="All Recurring Items")
        list_card.pack(fill="both", expand=True, pady=(0, 10))
        cols = ("name", "payee", "category", "amount", "currency", "frequency", "next_date", "account", "active")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings", height=8)
        headers = {"name": "Name", "payee": "Payee", "category": "Category", "amount": "Amount",
                   "currency": "Ccy", "frequency": "Frequency", "next_date": "Next Date",
                   "account": "Account", "active": "Active"}
        for c in cols:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=110, anchor="w")
        self.tree.pack(fill="both", expand=True)

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
        cats = {c["name"]: c["id"] for c in self.app.db.list_categories()}
        cat_id = cats.get(self.category_var.get().strip())
        currency = self.currency_var.get().strip().upper() or self.app.reporting_currency()
        accounts = {a["name"]: a["id"] for a in self.app.db.list_accounts() if a["subtype"] != "roundup_pot"}
        account_id = accounts.get(self.account_var.get().strip())
        self.app.db.add_recurring(name, self.payee_var.get().strip() or None, cat_id, amount,
                                   currency, self.freq_var.get(), self.next_date_var.get().strip(),
                                   account_id=account_id)
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
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["name"], r["payee"] or "", r["category_name"] or "(none)",
                f"{r['amount']:,.2f}", r["currency"], r["frequency"], r["next_date"],
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
        ttk.Button(form, text="Add Debt", style="Accent.TButton", command=self.add_debt).grid(
            row=1, column=5, padx=8)

        list_card = Card(self, title="Debts")
        list_card.pack(fill="x", pady=(0, 10))
        cols = ("name", "balance", "apr", "min_payment", "custom_payment")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings", height=5)
        for c, label in zip(cols, ["Name", "Balance", "APR %", "Min Payment", "Planned Payment"]):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=140)
        self.tree.pack(fill="x", expand=True)
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
    ("Credit Card", "credit_card", "liability"),
    ("Investment", "investment", "asset"),
    ("Loan", "loan", "liability"),
    ("Other Asset", "other", "asset"),
    ("Other Liability", "other", "liability"),
]
ACCOUNT_TYPE_LABELS = [label for label, _, _ in ACCOUNT_TYPE_OPTIONS]
ACCOUNT_TYPE_BY_LABEL = {label: (subtype, kind) for label, subtype, kind in ACCOUNT_TYPE_OPTIONS}
ACCOUNT_TYPE_BY_SUBTYPE = {subtype: label for label, subtype, _ in ACCOUNT_TYPE_OPTIONS}


class NetWorthTab(ScrollableTab):
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
        self.acc_due_day = tk.StringVar(value="1")
        self.acc_expected_return = tk.StringVar(value="5")
        self.acc_monthly_contribution = tk.StringVar(value="0")

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
        ttk.Checkbutton(form, text="Liquid", variable=self.acc_liquid).grid(row=1, column=4, padx=6)
        ttk.Button(form, text="Add Account", style="Accent.TButton", command=self.add_account).grid(
            row=1, column=5, padx=8)

        self.extra_frame = ttk.Frame(form, style="Card.TFrame")
        self.extra_frame.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(self.extra_frame, text="Credit limit", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_credit_limit, width=10).grid(row=1, column=0, padx=(0, 12))
        ttk.Label(self.extra_frame, text="Cashback % on spend", style="CardDim.TLabel").grid(
            row=0, column=1, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_cashback_rate, width=10).grid(row=1, column=1, padx=(0, 12))
        ttk.Label(self.extra_frame, text="Payment due day (1-28)", style="CardDim.TLabel").grid(
            row=0, column=2, sticky="w")
        ttk.Entry(self.extra_frame, textvariable=self.acc_due_day, width=10).grid(row=1, column=2)

        self.inv_extra_frame = ttk.Frame(form, style="Card.TFrame")
        self.inv_extra_frame.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(self.inv_extra_frame, text="Expected annual return %", style="CardDim.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(self.inv_extra_frame, textvariable=self.acc_expected_return, width=10).grid(
            row=1, column=0, padx=(0, 12))
        ttk.Label(self.inv_extra_frame, text="Planned monthly contribution", style="CardDim.TLabel").grid(
            row=0, column=1, sticky="w")
        ttk.Entry(self.inv_extra_frame, textvariable=self.acc_monthly_contribution, width=12).grid(
            row=1, column=1)
        ttk.Label(self.inv_extra_frame, text="(used only for the illustrative growth projection below — "
                                              "not a promise of future returns)",
                  style="CardDim.TLabel", wraplength=380, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._update_extra_fields()

        list_card = Card(self, title="Accounts")
        list_card.pack(fill="x", pady=(0, 10))
        cols = ("name", "type", "balance", "currency", "liquid")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings", height=6)
        for c, label in zip(cols, ["Name", "Type", "Balance", "Ccy", "Liquid"]):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=130)
        self.tree.pack(fill="x", expand=True)
        btn_row = ttk.Frame(list_card, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Delete Selected Account", command=self.delete_selected).pack(
            side="left")
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
        self.transfers_tree = ttk.Treeview(transfers_card, columns=transfer_cols,
                                            show="headings", height=6)
        for col, label in zip(transfer_cols,
                               ["Date", "From", "To", "Amount", "Received", "Rate"]):
            self.transfers_tree.heading(col, text=label)
            self.transfers_tree.column(col, width=120, anchor="w")
        self.transfers_tree.pack(fill="x", expand=True)
        ttk.Button(transfers_card, text="Delete Transfer", command=self.delete_selected_transfer).pack(
            anchor="w", pady=(8, 0))

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
        ttk.Button(summary, text="Record Net Worth Snapshot (today)", style="Accent.TButton",
                   command=self.record_snapshot).pack(anchor="w")

        ring_card = Card(summary_row, title="FI Progress")
        ring_card.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        c = self.app.c
        self.fi_ring = tk.Canvas(ring_card, height=140, highlightthickness=0, bg=c["card"])
        self.fi_ring.pack(fill="both", expand=True)

        cc_row = ttk.Frame(self)
        cc_row.pack(fill="x", pady=(0, 10))
        self.cc_card = Card(cc_row, title="Credit Cards — Utilization")
        self.cc_card.pack(fill="x")
        self.cc_inner = ttk.Frame(self.cc_card, style="Card.TFrame")
        self.cc_inner.pack(fill="x")

        inv_row = ttk.Frame(self)
        inv_row.pack(fill="x", pady=(0, 10))
        self.inv_card = Card(inv_row, title="Investments")
        self.inv_card.pack(fill="x")
        self.inv_inner = ttk.Frame(self.inv_card, style="Card.TFrame")
        self.inv_inner.pack(fill="x")

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

        projection_card = Card(self, title="Investment Growth Projection (illustrative, 10 years)")
        projection_card.pack(fill="both", expand=True, pady=(10, 0))
        self.projection_canvas = tk.Canvas(projection_card, height=170, highlightthickness=0, bg=c["card"])
        self.projection_canvas.pack(fill="both", expand=True)

    def _update_extra_fields(self):
        subtype, _ = ACCOUNT_TYPE_BY_LABEL[self.acc_type.get()]
        if subtype == "credit_card":
            self.extra_frame.grid()
        else:
            self.extra_frame.grid_remove()
        if subtype == "investment":
            self.inv_extra_frame.grid()
        else:
            self.inv_extra_frame.grid_remove()

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
        except ValueError:
            credit_limit, cashback_rate = 0.0, 0.0
        due_day = None
        if subtype == "credit_card":
            try:
                due_day = int(self.acc_due_day.get())
                due_day = min(max(due_day, 1), 28)
            except ValueError:
                due_day = None
        expected_return, monthly_contribution = 0.0, 0.0
        if subtype == "investment":
            try:
                expected_return = float(self.acc_expected_return.get())
            except ValueError:
                expected_return = 0.0
            try:
                monthly_contribution = float(self.acc_monthly_contribution.get())
            except ValueError:
                monthly_contribution = 0.0
        liquid = self.acc_liquid.get() or subtype == "cash"
        self.app.db.add_account(name, kind, balance,
                                 self.acc_currency.get().strip().upper() or "GBP",
                                 liquid, subtype=subtype, credit_limit=credit_limit,
                                 cashback_rate=cashback_rate, due_day=due_day,
                                 expected_return_pct=expected_return,
                                 monthly_contribution=monthly_contribution)
        self.acc_name.set("")
        self.acc_balance.set("")
        self.app.refresh_all()

    def delete_selected(self):
        for iid in self.tree.selection():
            self.app.db.delete_account(int(iid))
        self.app.refresh_all()

    def open_transfer_dialog(self):
        accounts = self.app.db.list_accounts()
        if len(accounts) < 2:
            messagebox.showinfo("Transfer", "You need at least two accounts to transfer between.")
            return
        win = tk.Toplevel(self)
        win.title("Transfer Between Accounts")
        win.configure(bg=self.app.c["bg"])
        win.geometry("380x320")
        names = [a["name"] for a in accounts]
        by_name = {a["name"]: a for a in accounts}

        sel = self.tree.selection()
        default_from = self.tree.item(sel[0])["values"][0] if sel else names[0]

        ttk.Label(win, text="From account", style="TLabel").pack(anchor="w", padx=14, pady=(14, 2))
        from_var = tk.StringVar(value=default_from)
        ttk.Combobox(win, textvariable=from_var, values=names, state="readonly").pack(
            fill="x", padx=14)

        ttk.Label(win, text="To account", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        to_default = next((n for n in names if n != default_from), names[0])
        to_var = tk.StringVar(value=to_default)
        ttk.Combobox(win, textvariable=to_var, values=names, state="readonly").pack(fill="x", padx=14)

        ttk.Label(win, text="Amount (in From account's currency)", style="TLabel").pack(
            anchor="w", padx=14, pady=(10, 2))
        amount_var = tk.StringVar()
        ttk.Entry(win, textvariable=amount_var).pack(fill="x", padx=14)

        received_label = ttk.Label(win, text="Actual amount received (optional, in To account's currency)",
                                    style="TLabel")
        received_label.pack(anchor="w", padx=14, pady=(10, 2))
        received_var = tk.StringVar()
        received_entry = ttk.Entry(win, textvariable=received_var)
        received_entry.pack(fill="x", padx=14)

        note_var = tk.StringVar()
        ttk.Label(win, text="Note (optional)", style="TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        ttk.Entry(win, textvariable=note_var).pack(fill="x", padx=14)

        rate_label = ttk.Label(win, style="CardDim.TLabel")
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

        ttk.Button(win, text="Transfer", style="Accent.TButton", command=do_transfer).pack(
            anchor="e", padx=14, pady=16)

    def export_account_statement(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Export Statement", "Select an account first.")
            return
        account_id = int(sel[0])
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
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Reconcile", "Select an account first.")
            return
        account_id = int(sel[0])
        acc = self.app.db.get_account(account_id)
        if not acc:
            return

        win = tk.Toplevel(self)
        win.title("Reconcile Balance")
        win.configure(bg=self.app.c["bg"])
        win.geometry("360x220")

        ttk.Label(win, text=f"{acc['name']} — tracked balance: "
                             f"{fmt_money(acc['balance'], acc['currency'])}",
                  style="H2.TLabel", wraplength=320, justify="left").pack(
            anchor="w", padx=14, pady=(14, 8))

        ttk.Label(win, text="Actual balance from your statement", style="TLabel").pack(
            anchor="w", padx=14, pady=(0, 2))
        actual_var = tk.StringVar(value=f"{acc['balance']:.2f}")
        ttk.Entry(win, textvariable=actual_var).pack(fill="x", padx=14)

        diff_label = ttk.Label(win, style="CardDim.TLabel")
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

        ttk.Button(win, text="Reconcile", style="Accent.TButton", command=do_reconcile).pack(
            anchor="e", padx=14, pady=16)

    def delete_selected_transfer(self):
        from finance_core import ReconciledTransactionError
        sel = self.transfers_tree.selection()
        if not sel:
            messagebox.showinfo("Delete Transfer", "Select a transfer first.")
            return
        try:
            self.app.db.delete_transaction(int(sel[0]))
        except ReconciledTransactionError:
            messagebox.showinfo(
                "Reconciled transaction",
                "One leg of this transfer is reconciled/locked and was not deleted. "
                "Unreconcile it first if you need to remove this transfer.")
            return
        self.app.refresh_all()

    def open_account_ledger(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Ledger", "Select an account first.")
            return
        account_id = int(sel[0])
        acc = self.app.db.get_account(account_id)
        if not acc:
            return

        win = tk.Toplevel(self)
        win.title(f"Ledger — {acc['name']}")
        win.geometry("760x460")
        win.configure(bg=self.app.c["bg"])

        ttk.Label(win, text=f"{acc['name']} — running balance in {acc['currency']}  ·  "
                             "double-click a row to edit (transfers must be edited from the "
                             "Transactions tab or deleted/recreated)",
                  style="H2.TLabel", wraplength=740, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4))

        cols = ("date", "payee", "amount", "balance", "flags")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=18)
        for col, label, w in zip(cols, ["Date", "Payee/Transfer", "Amount", "Balance", ""],
                                  (90, 260, 100, 110, 60)):
            tree.heading(col, text=label)
            tree.column(col, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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

    def record_snapshot(self):
        nw = net_worth(self.app.db)
        self.app.db.record_networth_snapshot(self.app.today.isoformat(), nw)
        self.refresh()

    def _ask_amount(self, title, prompt):
        return simpledialog.askfloat(title, prompt, parent=self)

    def _add_contribution(self, account_id):
        amt = self._ask_amount("Add Contribution", "How much are you adding?")
        if amt:
            self.app.db.add_investment_contribution(account_id, amt)
            self.app.refresh_all()

    def _update_value(self, account_id, current_balance):
        val = self._ask_amount("Update Market Value", "New current value of this account:")
        if val is not None:
            self.app.db.update_investment_value(account_id, val)
            self.app.refresh_all()

    def _set_cashback_auto_invest(self, account_id):
        investments = [a for a in self.app.db.list_accounts() if a["subtype"] == "investment"]
        if not investments:
            messagebox.showinfo(
                "Auto-Invest Cashback",
                "You need at least one Investment account first — add one above, then come back here.")
            return

        win = tk.Toplevel(self)
        win.title("Auto-Invest Cashback")
        win.configure(bg=self.app.c["bg"])
        win.geometry("340x160")

        ttk.Label(win, text="Route this card's cashback straight into:", style="TLabel").pack(
            anchor="w", padx=14, pady=(14, 4))
        names = ["(none — accumulate for manual redemption)"] + [a["name"] for a in investments]
        by_name = {a["name"]: a["id"] for a in investments}
        current = next((a["name"] for a in investments
                         if a["id"] == self.app.db.get_account(account_id)["cashback_auto_invest_account_id"]),
                        names[0])
        target_var = tk.StringVar(value=current)
        ttk.Combobox(win, textvariable=target_var, values=names, state="readonly").pack(fill="x", padx=14)

        def save():
            target_id = by_name.get(target_var.get(), 0)
            self.app.db.update_account_details(account_id, cashback_auto_invest_account_id=target_id)
            win.destroy()
            self.app.refresh_all()

        ttk.Button(win, text="Save", style="Accent.TButton", command=save).pack(anchor="e", padx=14, pady=16)

    def _set_due_day(self, account_id):
        day = simpledialog.askinteger("Payment Due Day", "Day of the month payment is due (1-28):",
                                       parent=self, minvalue=1, maxvalue=28)
        if day is not None:
            self.app.db.update_account_details(account_id, due_day=day)
            self.app.refresh_all()

    def _set_projection_assumptions(self, account_id):
        rate = simpledialog.askfloat("Expected Annual Return %", "Assumed annual return, e.g. 5 for 5%:",
                                      parent=self, minvalue=-50, maxvalue=100)
        if rate is None:
            return
        contrib = simpledialog.askfloat("Planned Monthly Contribution",
                                         "How much do you plan to add each month?",
                                         parent=self, minvalue=0)
        if contrib is None:
            contrib = 0.0
        volatility = simpledialog.askfloat(
            "Return Volatility %",
            "Assumed annual volatility (stdev of returns), e.g. 15 for a typical equity fund. "
            "Used to draw a low/high illustrative range around the projection, not just a single line:",
            parent=self, minvalue=0, maxvalue=100)
        if volatility is None:
            volatility = 0.0
        self.app.db.update_account_details(account_id, expected_return_pct=rate,
                                            monthly_contribution=contrib,
                                            return_volatility_pct=volatility)
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
        for a in self.app.db.list_accounts():
            type_label = ACCOUNT_TYPE_BY_SUBTYPE.get(a["subtype"], "Other")
            self.tree.insert("", "end", iid=str(a["id"]), values=(
                a["name"], type_label, f"{a['balance']:,.2f}", a["currency"],
                "yes" if a["liquid"] else "no"))

        for row in self.transfers_tree.get_children():
            self.transfers_tree.delete(row)
        for t in self.app.db.list_transfers():
            rate_text = f"{t['historical_rate']:.4f}" if t["from_currency"] != t["to_currency"] else "—"
            self.transfers_tree.insert("", "end", iid=str(t["leg_id"]), values=(
                t["date"], t["from_account"] or "(deleted)", t["to_account"] or "(deleted)",
                fmt_money(t["from_amount"], t["from_currency"]),
                fmt_money(t["to_amount"], t["to_currency"]), rate_text))

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
                if a["cashback_rate"]:
                    target = next((acc["name"] for acc in self.app.db.list_accounts()
                                   if acc["id"] == a["cashback_auto_invest_account_id"]), None)
                    invest_text = f"Auto-invests into {target}" if target else "Cashback not auto-invested"
                    ttk.Label(bottom, text=f"  ·  {invest_text}", style="CardDim.TLabel").pack(side="left")
                    ttk.Button(bottom, text="Set Auto-Invest",
                               command=lambda aid=a["id"]: self._set_cashback_auto_invest(aid)).pack(
                        side="left", padx=8)

        # investments
        for w in self.inv_inner.winfo_children():
            w.destroy()
        invs = investment_summary(self.app.db)
        if not invs:
            ttk.Label(self.inv_inner, text="No investment accounts yet — add one above to track growth.",
                      style="CardDim.TLabel").pack(anchor="w")
        else:
            for entry in invs:
                a = entry["account"]
                row = ttk.Frame(self.inv_inner, style="Card.TFrame")
                row.pack(fill="x", pady=6)
                growth_style = "Good.TLabel" if entry["growth"] >= 0 else "Bad.TLabel"
                top = ttk.Frame(row, style="Card.TFrame")
                top.pack(fill="x")
                ttk.Label(top, text=f"{a['name']}: {fmt_money(entry['balance'], cur)}",
                          style="Card.TLabel", font=theme.Fonts.body_bold).pack(side="left")
                ttk.Label(top, text=f"  ({'+' if entry['growth'] >= 0 else ''}{fmt_money(entry['growth'], cur)}, "
                                     f"{entry['growth_pct']*100:+.1f}%)",
                          style=growth_style).pack(side="left")
                ttk.Label(row, text=f"Contributed: {fmt_money(entry['contributions'], cur)}",
                          style="CardDim.TLabel").pack(anchor="w")
                assumptions = f"Assuming {a['expected_return_pct'] or 0:.1f}%/yr"
                if a["monthly_contribution"]:
                    assumptions += f" + {fmt_money(a['monthly_contribution'], cur)}/mo"
                ttk.Label(row, text=assumptions, style="CardDim.TLabel").pack(anchor="w")
                btn_row = ttk.Frame(row, style="Card.TFrame")
                btn_row.pack(anchor="w", pady=(4, 0))
                ttk.Button(btn_row, text="Add Contribution",
                           command=lambda aid=a["id"]: self._add_contribution(aid)).pack(side="left")
                ttk.Button(btn_row, text="Update Market Value",
                           command=lambda aid=a["id"], b=entry["balance"]: self._update_value(aid, b)).pack(
                    side="left", padx=6)
                ttk.Button(btn_row, text="Set Growth Assumptions",
                           command=lambda aid=a["id"]: self._set_projection_assumptions(aid)).pack(
                    side="left", padx=6)

        breakdown = net_worth_breakdown(self.app.db)
        segment_colors = {"cash": c["good"], "credit_card": c["bad"], "investment": c["accent"],
                           "loan": c["warn"], "other": c["text_faint"]}
        segments = [(k.replace("_", " ").title(), abs(v), segment_colors.get(k, c["text_faint"]))
                    for k, v in breakdown.items() if abs(v) > 0.01]
        charts.draw_donut_chart(self.breakdown_canvas, segments, c,
                                 center_label=fmt_money(nw, cur), center_sub="net worth")

        snaps = self.app.db.list_networth_snapshots()
        values = [s["net_worth"] for s in snaps]
        labels = [s["date"][5:] for s in snaps]
        charts.draw_line_chart(self.trend_canvas, values, labels, c,
                                unit_fmt=lambda v: f"{v:,.0f}")

        proj_labels, proj_mid, proj_low, proj_high = investment_projection_with_bands(self.app.db, years=10)
        charts.draw_band_chart(self.projection_canvas, proj_mid, proj_low, proj_high, proj_labels, c,
                                unit_fmt=lambda v: f"{v:,.0f}")


# --------------------------------------------------------------------------
# Investments — per-security buy/sell lots, Section 104 pooling, capital gains
# --------------------------------------------------------------------------

SECURITY_IMPORT_COLUMNS = ["Date", "Security", "Action", "Quantity", "Price", "Fees", "Note"]


class InvestmentsTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _investment_accounts(self):
        return [a for a in self.app.db.list_accounts() if a["subtype"] == "investment"]

    def _build(self):
        form = Card(self, title="Add Security Transaction")
        form.pack(fill="x", pady=(0, 10))

        accounts = self._investment_accounts()
        self.tx_account = tk.StringVar(value=accounts[0]["name"] if accounts else "")
        self.tx_security = tk.StringVar()
        self.tx_action = tk.StringVar(value="buy")
        self.tx_quantity = tk.StringVar()
        self.tx_price = tk.StringVar()
        self.tx_fees = tk.StringVar(value="0")
        self.tx_date = tk.StringVar(value=self.app.today.isoformat())

        ttk.Label(form, text="Account", style="CardDim.TLabel").grid(row=0, column=0, sticky="w")
        self.account_combo = ttk.Combobox(form, textvariable=self.tx_account,
                                           values=[a["name"] for a in accounts], width=16, state="readonly")
        self.account_combo.grid(row=1, column=0, padx=4)

        ttk.Label(form, text="Security", style="CardDim.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Entry(form, textvariable=self.tx_security, width=12).grid(row=1, column=1, padx=4)

        ttk.Label(form, text="Action", style="CardDim.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Combobox(form, textvariable=self.tx_action, values=["buy", "sell"], width=6,
                     state="readonly").grid(row=1, column=2, padx=4)

        ttk.Label(form, text="Quantity", style="CardDim.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Entry(form, textvariable=self.tx_quantity, width=10).grid(row=1, column=3, padx=4)

        ttk.Label(form, text="Price/unit", style="CardDim.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Entry(form, textvariable=self.tx_price, width=10).grid(row=1, column=4, padx=4)

        ttk.Label(form, text="Fees", style="CardDim.TLabel").grid(row=0, column=5, sticky="w")
        ttk.Entry(form, textvariable=self.tx_fees, width=8).grid(row=1, column=5, padx=4)

        ttk.Label(form, text="Date (YYYY-MM-DD)", style="CardDim.TLabel").grid(row=0, column=6, sticky="w")
        ttk.Entry(form, textvariable=self.tx_date, width=12).grid(row=1, column=6, padx=4)

        ttk.Button(form, text="Add", style="Accent.TButton", command=self.add_transaction).grid(
            row=1, column=7, padx=8)

        import_card = Card(self, title="Import Past Transactions from CSV")
        import_card.pack(fill="x", pady=(0, 10))
        ttk.Label(import_card, wraplength=760, justify="left", style="CardDim.TLabel",
                  text=f"Expected columns: {', '.join(SECURITY_IMPORT_COLUMNS)} (Date as YYYY-MM-DD, "
                       "Action as buy/sell, Fees and Note optional). Excel/PDF import isn't built yet — "
                       "export your broker history to CSV first.").pack(anchor="w")
        ttk.Button(import_card, text="Choose CSV File…", command=self.import_csv).pack(anchor="w", pady=(8, 0))

        self.holdings_frame = ttk.Frame(self)
        self.holdings_frame.pack(fill="x", pady=(0, 10))

        self.gains_frame = ttk.Frame(self)
        self.gains_frame.pack(fill="x", pady=(0, 10))

    def add_transaction(self):
        accounts = {a["name"]: a["id"] for a in self._investment_accounts()}
        account_id = accounts.get(self.tx_account.get())
        security = self.tx_security.get().strip().upper()
        if not account_id or not security:
            messagebox.showerror("Error", "Choose an account and enter a security.")
            return
        try:
            quantity = float(self.tx_quantity.get())
            price = float(self.tx_price.get())
            fees = float(self.tx_fees.get() or 0)
        except ValueError:
            messagebox.showerror("Error", "Quantity, price and fees must be numbers.")
            return
        try:
            self.app.db.add_security_transaction(
                account_id, security, self.tx_date.get().strip(), self.tx_action.get(), quantity, price,
                fees=fees)
        except (ValueError, Exception) as e:
            messagebox.showerror("Error", str(e))
            return
        self.tx_security.set("")
        self.tx_quantity.set("")
        self.tx_price.set("")
        self.tx_fees.set("0")
        self.app.refresh_all()

    def import_csv(self):
        accounts = {a["name"]: a["id"] for a in self._investment_accounts()}
        if not accounts:
            messagebox.showinfo("Import", "Add an Investment account on the Net Worth tab first.")
            return
        account_id = accounts.get(self.tx_account.get()) or next(iter(accounts.values()))

        path = filedialog.askopenfilename(title="Import security transactions",
                                           filetypes=[("CSV files", "*.csv")])
        if not path:
            return

        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))

        errors = []
        parsed = []
        for i, row in enumerate(rows, start=2):  # header is row 1
            try:
                date = row["Date"].strip()
                security = row["Security"].strip().upper()
                action = row["Action"].strip().lower()
                quantity = float(row["Quantity"])
                price = float(row["Price"])
                fees = float(row["Fees"]) if row.get("Fees") else 0.0
                note = row.get("Note", "") or ""
                if action not in ("buy", "sell"):
                    raise ValueError(f"Action must be 'buy' or 'sell', got {action!r}")
                parsed.append((date, security, action, quantity, price, fees, note))
            except (KeyError, ValueError) as e:
                errors.append(f"Row {i}: {e}")

        if errors:
            messagebox.showerror("Import failed — nothing was imported",
                                  "Fix these rows and try again:\n\n" + "\n".join(errors[:20]))
            return

        for date, security, action, quantity, price, fees, note in parsed:
            self.app.db.add_security_transaction(account_id, security, date, action, quantity, price,
                                                   fees=fees, note=note)

        messagebox.showinfo("Import complete", f"Imported {len(parsed)} transaction(s).")
        self.app.refresh_all()

    def refresh(self):
        accounts = self._investment_accounts()
        self.account_combo.config(values=[a["name"] for a in accounts])
        if not self.tx_account.get() and accounts:
            self.tx_account.set(accounts[0]["name"])

        for w in self.holdings_frame.winfo_children():
            w.destroy()
        ttk.Label(self.holdings_frame, text="Current Holdings", style="H2.TLabel",
                  font=theme.Fonts.body_bold).pack(anchor="w", pady=(0, 6))
        cur = self.app.reporting_currency()
        any_holdings = False
        for acc in accounts:
            for row in self.app.db.list_securities(acc["id"]):
                qty, cost, avg_cost = self.app.db.security_pool_state(acc["id"], row["security"])
                if qty <= 0:
                    continue
                any_holdings = True
                card = Card(self.holdings_frame, title=f"{row['security']} — {acc['name']}")
                card.pack(fill="x", pady=4)
                ttk.Label(card, text=f"{qty:,.4f} units  ·  avg cost {fmt_money(avg_cost, cur)}/unit  ·  "
                                      f"pool cost {fmt_money(cost, cur)}",
                          style="Card.TLabel").pack(anchor="w")
        if not any_holdings:
            ttk.Label(self.holdings_frame, text="No open holdings yet — add a buy above.",
                      style="CardDim.TLabel").pack(anchor="w")

        for w in self.gains_frame.winfo_children():
            w.destroy()
        ttk.Label(self.gains_frame, text="Realized Gains (this UK tax year)", style="H2.TLabel",
                  font=theme.Fonts.body_bold).pack(anchor="w", pady=(0, 6))
        tax_year_start = uk_tax_year_start(self.app.today)
        result = self.app.db.realized_gains_for_uk_tax_year(tax_year_start)
        card = Card(self.gains_frame, title=f"Tax year {result['tax_year']}")
        card.pack(fill="x", pady=4)
        ttk.Label(card, text=f"Net realized gain: {fmt_money(result['total_gain'], cur)} across "
                              f"{len(result['sells'])} disposal(s)", style="Card.TLabel").pack(anchor="w")
        for s in result["sells"]:
            ttk.Label(card, text=f"  {s['date']}  {s['security']} ({s['account_name']})  "
                                  f"{fmt_money(s['realized_gain'] or 0, cur)}",
                      style="CardDim.TLabel").pack(anchor="w")


def uk_tax_year_start(as_of):
    """The UK tax year is 6 Apr -> 5 Apr. Returns the starting year of the
    tax year `as_of` falls in, e.g. 2026-05-01 -> 2026 (the 2026/27 year),
    2026-02-01 -> 2025 (still the 2025/26 year, since it's before 6 Apr)."""
    if (as_of.month, as_of.day) >= (4, 6):
        return as_of.year
    return as_of.year - 1


# --------------------------------------------------------------------------
# Tax — UK capital gains tax summary
# --------------------------------------------------------------------------

class TaxTab(ScrollableTab):
    def __init__(self, parent, app: App):
        super().__init__(parent, app)
        self.app = app
        self._build()

    def _build(self):
        disclaimer = Card(self, title="Before you rely on these numbers")
        disclaimer.pack(fill="x", pady=(0, 10))
        ttk.Label(disclaimer, wraplength=760, justify="left", style="CardDim.TLabel",
                  text="This is a rough estimate, not tax advice. Capital gains use plain Section 104 "
                       "average-cost pooling — HMRC's same-day and 30-day \"bed and breakfast\" matching "
                       "rules aren't applied, which can change the real figure if you buy and sell the "
                       "same security in quick succession. Verify the CGT allowance below is this tax "
                       "year's actual HMRC figure before using this for a real Self Assessment.").pack(
            anchor="w")

        settings_card = Card(self, title="CGT Annual Exempt Amount")
        settings_card.pack(fill="x", pady=(0, 10))
        ttk.Label(settings_card, text="Annual exempt amount for this tax year", style="CardDim.TLabel").grid(
            row=0, column=0, sticky="w")
        self.allowance_var = tk.StringVar()
        ttk.Entry(settings_card, textvariable=self.allowance_var, width=10).grid(row=1, column=0, padx=4)
        ttk.Button(settings_card, text="Save", command=self.save_allowance).grid(row=1, column=1, padx=8)

        self.summary_frame = ttk.Frame(self)
        self.summary_frame.pack(fill="x", pady=(0, 10))

    def save_allowance(self):
        try:
            value = float(self.allowance_var.get())
        except ValueError:
            messagebox.showerror("Error", "Enter a number.")
            return
        self.app.db.set_setting("cgt_annual_exempt_amount", str(value))
        self.app.refresh_all()

    def refresh(self):
        cur = self.app.reporting_currency()
        default_allowance = self.app.db.get_setting("cgt_annual_exempt_amount", "3000")
        self.allowance_var.set(default_allowance)

        for w in self.summary_frame.winfo_children():
            w.destroy()

        tax_year_start = uk_tax_year_start(self.app.today)
        result = self.app.db.realized_gains_for_uk_tax_year(tax_year_start)
        allowance = float(default_allowance)
        taxable = max(0.0, result["total_gain"] - allowance)

        card = Card(self.summary_frame, title=f"Capital Gains — Tax Year {result['tax_year']}")
        card.pack(fill="x", pady=4)
        ttk.Label(card, text=f"Net realized gain: {fmt_money(result['total_gain'], cur)}",
                  style="Card.TLabel").pack(anchor="w")
        ttk.Label(card, text=f"Annual exempt amount: {fmt_money(allowance, cur)}",
                  style="CardDim.TLabel").pack(anchor="w")
        flag = "  OVER ALLOWANCE" if taxable > 0 else ""
        ttk.Label(card, text=f"Estimated taxable gain: {fmt_money(taxable, cur)}{flag}",
                  style="Card.TLabel").pack(anchor="w", pady=(4, 0))


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

        ttk.Button(general, text="Save Settings", style="Accent.TButton",
                   command=self.save_settings).grid(row=7, column=0, pady=10, sticky="w")

        self.fx_frame = Card(self, title="FX Rates (1 unit of currency = X reporting currency)")
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

        nav_card = Card(self, title="Customize Navigation")
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

        ignored_subs_card = Card(self, title="Ignored Subscriptions")
        ignored_subs_card.pack(fill="x", pady=(0, 10))
        ttk.Label(ignored_subs_card,
                  text="Dismissed from the Recurring tab's Detected Subscriptions list.",
                  style="CardDim.TLabel").pack(anchor="w")
        self.ignored_subs_frame = ttk.Frame(ignored_subs_card, style="Card.TFrame")
        self.ignored_subs_frame.pack(fill="x", pady=(6, 0))

        profile_card = Card(self, title="Profile")
        profile_card._settings_role = "profile_card"
        profile_card.pack(fill="x", pady=(0, 10))
        self.signed_in_label = ttk.Label(
            profile_card, text=f"Signed in as: {self.app.profile['name']}", style="Card.TLabel")
        self.signed_in_label.pack(anchor="w")
        btn_row = ttk.Frame(profile_card, style="Card.TFrame")
        btn_row.pack(fill="x", pady=(8, 0))
        ttk.Button(btn_row, text="Rename Profile…", command=self.rename_profile).pack(side="left")
        ttk.Button(btn_row, text="Switch Profile", command=self.app.switch_profile).pack(
            side="left", padx=6)
        ttk.Button(btn_row, text="Lock This Profile With a Password…",
                   command=self.lock_profile).pack(side="left", padx=6)
        ttk.Label(profile_card, wraplength=760, justify="left", style="CardDim.TLabel",
                  text="Locking encrypts this profile's data file with a password you set and closes "
                       "it — you'll need the password to reopen it. This uses a stdlib-only cipher "
                       "(no extra dependencies), which is solid against casual snooping but hasn't had "
                       "the independent security review a maintained library gets. For anything highly "
                       "sensitive, full-disk encryption on this machine is still the stronger option."
                  ).pack(anchor="w", pady=(6, 0))

        data_files_card = Card(self, title="Data Files")
        data_files_card.pack(fill="x", pady=(0, 10))
        ttk.Label(data_files_card, wraplength=760, justify="left", style="CardDim.TLabel",
                  text="Every profile has its own folder with editable CSV files — "
                       "transactions.csv, accounts.csv, categories.csv, investments.csv — for quick "
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

        note = ttk.Label(self, wraplength=800, justify="left",
                          text="Everything is stored locally per profile in the 'Profiles' folder "
                               "next to the app — "
                               "local-first storage, no network calls. If you ever sync these files "
                               "to the cloud, encrypt them first.",
                          style="Dim.TLabel")
        note.pack(fill="x", pady=8)

    def refresh_csvs(self):
        profile_dir = profiles.profile_dir_for(self.app.profile["slug"])
        refresh_profile_csvs(self.app.db, profile_dir)
        messagebox.showinfo("Refreshed", f"CSV files updated in:\n{profile_dir}")

    def apply_csvs(self):
        profile_dir = profiles.profile_dir_for(self.app.profile["slug"])
        if not messagebox.askyesno(
                "Apply Changes from CSVs",
                "This reads transactions.csv, accounts.csv, categories.csv, and investments.csv "
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

    def lock_profile(self):
        password = simpledialog.askstring(
            "Set a password", "Choose a password to lock this profile with:", show="*", parent=self)
        if not password:
            return
        confirm = simpledialog.askstring(
            "Confirm password", "Enter the same password again:", show="*", parent=self)
        if confirm != password:
            messagebox.showerror("Passwords don't match", "Try again — both entries must match.")
            return
        if not messagebox.askyesno(
                "Lock profile",
                "This will close and encrypt this profile now, and return you to the profile picker. "
                "You'll need this exact password to reopen it — there is no recovery if you forget it. "
                "Continue?"):
            return
        slug = self.app.profile["slug"]
        self.app.db.close()
        try:
            profiles.lock_profile(slug, password)
        except Exception as e:
            messagebox.showerror("Couldn't lock profile", str(e))
            # db connection is already closed; reopen so the app keeps working
            self.app.db = Database(profiles.db_path_for(slug))
            return
        messagebox.showinfo("Profile locked", "This profile is now locked. Returning to the profile picker.")
        self.app.destroy()
        launcher = ProfileLauncher()
        launcher.mainloop()

    def save_settings(self):
        db = self.app.db
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
        old_mode = db.get_setting("theme_mode", "dark")
        db.set_setting("theme_mode", self.theme_var.get())
        db.set_setting("currency_mode", self.currency_mode_var.get())
        self.app.refresh_all()
        if self.theme_var.get() != old_mode:
            messagebox.showinfo("Theme changed", "Restart The Ledger to fully apply the new theme.")

    def save_nav_visibility(self):
        hidden = {key for key, var in self.nav_visibility_vars.items() if not var.get()}
        set_hidden_nav_tabs(self.app.db, hidden)
        self.app._build_nav_buttons()
        if getattr(self.app, "current_page", None) in hidden:
            self.app.show_page("dashboard")

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
        self.currency_mode_var.set(self.app.currency_mode())

        hidden_now = get_hidden_nav_tabs(db)
        for key, var in self.nav_visibility_vars.items():
            var.set(key not in hidden_now)

        self.signed_in_label.config(text=f"Signed in as: {self.app.profile['name']}")

        for w in self.ignored_subs_frame.winfo_children():
            w.destroy()
        ignored = db.list_ignored_subscriptions()
        if not ignored:
            ttk.Label(self.ignored_subs_frame, text="None ignored.",
                      style="CardDim.TLabel").pack(anchor="w")
        for row in ignored:
            r = ttk.Frame(self.ignored_subs_frame, style="Card.TFrame")
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=f"{row['payee']} (dismissed {row['dismissed_date']})",
                      style="Card.TLabel").pack(side="left")
            ttk.Button(r, text="Un-ignore",
                       command=lambda p=row["payee"]: self._unignore_subscription(p)).pack(side="right")

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

    def _unignore_subscription(self, payee):
        self.app.db.remove_ignored_subscription(payee)
        self.app.refresh_all()

    def _after_fx_widget(self):
        """The widget immediately after the FX card's usual slot, so
        re-showing it in holiday mode restores the original stacking order
        instead of appending it below Profile."""
        for child in self.pack_slaves():
            if getattr(child, "_settings_role", None) == "profile_card":
                return child
        return None


if __name__ == "__main__":
    launcher = ProfileLauncher()
    launcher.mainloop()
