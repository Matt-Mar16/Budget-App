"""
theme.py — visual design system for The Ledger.

Centralizes color palettes, font choices, and ttk styling so the whole
app looks like one deliberately-designed product instead of default
Tkinter widgets. Supports a dark theme (default) and a light theme,
toggle-able per profile.

Font stack: prefers a clean humanist sans available on the user's OS
(Segoe UI on Windows, SF/Helvetica Neue on macOS, Inter/Ubuntu on Linux),
falling back gracefully so nothing ever renders in the default Tk font.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# --------------------------------------------------------------------------
# Font stack
# --------------------------------------------------------------------------

_FONT_CANDIDATES = ["Segoe UI Variable", "Segoe UI", "SF Pro Text", "Helvetica Neue",
                    "Inter", "Ubuntu", "Cantarell", "Noto Sans", "Arial"]
_MONO_CANDIDATES = ["Cascadia Code", "SF Mono", "Consolas", "JetBrains Mono",
                    "DejaVu Sans Mono", "Courier New"]


def pick_font(root, candidates, fallback="TkDefaultFont"):
    available = set(tkfont.families(root))
    for name in candidates:
        if name in available:
            return name
    return fallback


class Fonts:
    """Populated once at startup via Fonts.init(root)."""
    family = "TkDefaultFont"
    mono = "TkFixedFont"

    display = None   # big hero numbers
    h1 = None         # section titles
    h2 = None         # card titles
    body = None
    body_bold = None
    small = None
    small_bold = None
    button = None

    @classmethod
    def init(cls, root):
        cls.family = pick_font(root, _FONT_CANDIDATES)
        cls.mono = pick_font(root, _MONO_CANDIDATES, fallback="TkFixedFont")
        cls.display = (cls.family, 32, "bold")
        cls.h1 = (cls.family, 16, "bold")
        cls.h2 = (cls.family, 12, "bold")
        cls.body = (cls.family, 10)
        cls.body_bold = (cls.family, 10, "bold")
        cls.small = (cls.family, 9)
        cls.small_bold = (cls.family, 9, "bold")
        cls.button = (cls.family, 10)
        cls.mono_body = (cls.mono, 10)


# --------------------------------------------------------------------------
# Color palettes
# --------------------------------------------------------------------------

DARK = {
    "bg": "#14161C",
    "bg_alt": "#1B1E27",
    "sidebar": "#10121A",
    "card": "#1F2330",
    "card_hover": "#262B3A",
    "border": "#2C3040",
    "text": "#EDEFF5",
    "text_dim": "#9AA0B4",
    "text_faint": "#666C82",
    "accent": "#5B8DEF",
    "accent_hover": "#729BF2",
    "accent_soft": "#26314F",
    "good": "#4CC9A0",
    "warn": "#F2994A",
    "bad": "#E4574C",
    "grid": "#252A3A",
    "chip_bg": "#262B3A",
}

LIGHT = {
    "bg": "#F4F5F8",
    "bg_alt": "#EAEBF0",
    "sidebar": "#FFFFFF",
    "card": "#FFFFFF",
    "card_hover": "#F0F1F6",
    "border": "#DCDFE6",
    "text": "#1B1E27",
    "text_dim": "#5B6070",
    "text_faint": "#8A8F9E",
    "accent": "#3B6FE0",
    "accent_hover": "#2E5BC2",
    "accent_soft": "#E4ECFC",
    "good": "#1F9D74",
    "warn": "#C77420",
    "bad": "#D1453B",
    "grid": "#E7E9EE",
    "chip_bg": "#EEF1F8",
}


class Palette:
    """Mutable holder for the active color set, swapped on theme toggle."""
    mode = "dark"
    c = DARK

    @classmethod
    def set_mode(cls, mode):
        cls.mode = mode
        cls.c = DARK if mode == "dark" else LIGHT


def apply_theme(root, style: ttk.Style, mode="dark"):
    Palette.set_mode(mode)
    c = Palette.c
    Fonts.init(root)

    root.configure(bg=c["bg"])

    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=c["bg"], foreground=c["text"],
                     font=Fonts.body, borderwidth=0, focuscolor=c["accent"])

    style.configure("TFrame", background=c["bg"])
    style.configure("Card.TFrame", background=c["card"])
    style.configure("Sidebar.TFrame", background=c["sidebar"])
    style.configure("Hero.TFrame", background=c["card"])

    style.configure("TLabel", background=c["bg"], foreground=c["text"], font=Fonts.body)
    style.configure("Card.TLabel", background=c["card"], foreground=c["text"], font=Fonts.body)
    style.configure("Dim.TLabel", background=c["bg"], foreground=c["text_dim"], font=Fonts.small)
    style.configure("CardDim.TLabel", background=c["card"], foreground=c["text_dim"], font=Fonts.small)
    style.configure("H1.TLabel", background=c["bg"], foreground=c["text"], font=Fonts.h1)
    style.configure("H2.TLabel", background=c["card"], foreground=c["text"], font=Fonts.h2)
    style.configure("Hero.TLabel", background=c["card"], foreground=c["text"], font=Fonts.display)
    style.configure("Good.TLabel", background=c["card"], foreground=c["good"], font=Fonts.body_bold)
    style.configure("Warn.TLabel", background=c["card"], foreground=c["warn"], font=Fonts.body_bold)
    style.configure("Bad.TLabel", background=c["card"], foreground=c["bad"], font=Fonts.body_bold)

    style.configure("TButton", background=c["card_hover"], foreground=c["text"],
                     font=Fonts.button, padding=(12, 7), borderwidth=0)
    style.map("TButton",
              background=[("active", c["border"]), ("pressed", c["border"])])

    style.configure("Accent.TButton", background=c["accent"], foreground="#FFFFFF",
                     font=Fonts.body_bold, padding=(14, 8), borderwidth=0)
    style.map("Accent.TButton",
              background=[("active", c["accent_hover"]), ("pressed", c["accent_hover"])])

    style.configure("Nav.TButton", background=c["sidebar"], foreground=c["text_dim"],
                     font=Fonts.body, padding=(14, 10), borderwidth=0, anchor="w")
    style.map("Nav.TButton",
              background=[("active", c["bg_alt"])],
              foreground=[("active", c["text"])])
    style.configure("NavActive.TButton", background=c["accent_soft"], foreground=c["accent"],
                     font=Fonts.body_bold, padding=(14, 10), borderwidth=0, anchor="w")
    style.map("NavActive.TButton", background=[("active", c["accent_soft"])])

    style.configure("TEntry", fieldbackground=c["card_hover"], foreground=c["text"],
                     insertcolor=c["text"], borderwidth=1, padding=6,
                     bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"])
    style.map("TEntry", bordercolor=[("focus", c["accent"])])

    style.configure("TCombobox", fieldbackground=c["card_hover"], foreground=c["text"],
                     background=c["card_hover"], arrowcolor=c["text_dim"], padding=6,
                     bordercolor=c["border"])
    style.map("TCombobox", fieldbackground=[("readonly", c["card_hover"])],
              foreground=[("readonly", c["text"])])

    style.configure("TCheckbutton", background=c["card"], foreground=c["text"], font=Fonts.body)
    style.map("TCheckbutton", background=[("active", c["card"])])

    style.configure("TLabelframe", background=c["card"], borderwidth=1,
                     bordercolor=c["border"], relief="solid")
    style.configure("TLabelframe.Label", background=c["card"], foreground=c["text_dim"],
                     font=Fonts.h2)

    style.configure("Treeview", background=c["card"], fieldbackground=c["card"],
                     foreground=c["text"], borderwidth=0, font=Fonts.body, rowheight=26)
    style.configure("Treeview.Heading", background=c["bg_alt"], foreground=c["text_dim"],
                     font=Fonts.small_bold, borderwidth=0, relief="flat")
    style.map("Treeview.Heading", background=[("active", c["bg_alt"])])
    style.map("Treeview",
              background=[("selected", c["accent_soft"])],
              foreground=[("selected", c["text"])])

    style.configure("TNotebook", background=c["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=c["bg_alt"], foreground=c["text_dim"],
                     padding=(14, 8), font=Fonts.body)
    style.map("TNotebook.Tab",
              background=[("selected", c["card"])],
              foreground=[("selected", c["text"])])

    style.configure("TScrollbar", background=c["bg_alt"], troughcolor=c["bg"],
                     bordercolor=c["bg"], arrowcolor=c["text_dim"])

    style.configure("Horizontal.TProgressbar", background=c["accent"],
                     troughcolor=c["bg_alt"], borderwidth=0)

    style.configure("TSeparator", background=c["border"])

    return c
