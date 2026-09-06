"""
charts.py — hand-drawn, dependency-free Tkinter Canvas charts.

The app stays stdlib-only (no matplotlib / no pip installs), but the
charts still get gradients, smoothed curves, rounded bars, and a real
legend instead of a plain polyline on a white rectangle.

Every draw_* function takes a plain tk.Canvas (already placed/sized) and
a `colors` dict from theme.Palette.c, and re-renders it from scratch —
simplest possible API for the tabs to call on refresh().
"""

import tkinter as tk

import theme


# --------------------------------------------------------------------------
# Dirty-tracking: skip a full canvas rebuild when nothing about to be drawn
# has actually changed. With high transaction volumes, refresh() can get
# called often (tab switches, periodic dashboard refresh, window resize
# events) and re-running the smoothing/gradient/rounded-rect math plus
# re-creating potentially hundreds of canvas items on every call is wasted
# work if the underlying data and pixel size are identical to last time.
#
# Each draw_* function computes a lightweight signature of "everything that
# would affect the pixels" (the data, the theme colors, and the canvas
# size) and stores it on the canvas widget itself. If the incoming
# signature matches, the function returns immediately without touching the
# canvas. This is deliberately a hash-compare, not a diff — these charts
# are cheap to fully redraw once something *does* change, so there's no
# need for per-element dirty regions, just a fast "did anything change at
# all" gate before paying for the redraw.
# --------------------------------------------------------------------------

def _sig(*parts):
    """Cheap, order-sensitive signature for dirty-tracking. repr() is good
    enough here (not cryptographic, just needs to change when data does)."""
    return hash(repr(parts))


def _skip_if_clean(canvas: tk.Canvas, attr: str, signature) -> bool:
    """Returns True (skip redraw) if this canvas already shows `signature`.
    Otherwise records it and returns False so the caller proceeds to draw."""
    if getattr(canvas, attr, None) == signature:
        return True
    setattr(canvas, attr, signature)
    return False


def mark_dirty(canvas: tk.Canvas):
    """Call after any operation that invalidates a canvas's cached signature
    without going through its draw_* function directly (e.g. manually
    clearing it) so the next refresh() is forced to actually redraw."""
    for attr in ("_sig_line", "_sig_bar", "_sig_donut", "_sig_ring", "_sig_heatmap"):
        if hasattr(canvas, attr):
            delattr(canvas, attr)


# --------------------------------------------------------------------------
# color helpers
# --------------------------------------------------------------------------

def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def lerp_color(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def rounded_rect(canvas, x0, y0, x1, y1, r, **kw):
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    if r <= 0:
        return canvas.create_rectangle(x0, y0, x1, y1, **kw)
    points = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


def _chaikin_smooth(points, iterations=2):
    """Corner-cutting smoothing so lines curve gently instead of zig-zagging."""
    pts = points[:]
    for _ in range(iterations):
        if len(pts) < 3:
            break
        new_pts = [pts[0]]
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            r = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            new_pts.extend([q, r])
        new_pts.append(pts[-1])
        pts = new_pts
    return pts


# --------------------------------------------------------------------------
# Line / area chart (net worth trend, etc.)
# --------------------------------------------------------------------------

def draw_line_chart(canvas: tk.Canvas, values, labels, colors, unit_fmt=None,
                     line_color=None, empty_text="Not enough history yet — check in over a few months.",
                     force=False):
    w = canvas.winfo_width() or int(canvas["width"])
    h = canvas.winfo_height() or int(canvas["height"])
    if w < 10 or h < 10:
        canvas.after(50, lambda: draw_line_chart(canvas, values, labels, colors, unit_fmt, line_color,
                                                   empty_text, force)
                     if canvas.winfo_exists() else None)
        return
    sig = _sig("line", values, labels, colors.get("card"), line_color or colors.get("accent"), w, h)
    if not force and _skip_if_clean(canvas, "_sig_line", sig):
        return
    canvas.delete("all")

    pad_l, pad_r, pad_t, pad_b = 54, 20, 20, 28
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    line_color = line_color or colors["accent"]

    canvas.create_rectangle(0, 0, w, h, fill=colors["card"], outline="")

    if len(values) < 2:
        canvas.create_text(w / 2, h / 2, text=empty_text, fill=colors["text_faint"],
                            font=(theme.Fonts.family, 10))
        return

    vmin, vmax = min(values), max(values)
    if vmin == vmax:
        vmin -= 1
        vmax += 1
    span = vmax - vmin
    pad_span = span * 0.15
    vmin -= pad_span
    vmax += pad_span
    span = vmax - vmin

    # gridlines + y-axis labels (4 bands)
    for i in range(4):
        frac = i / 3
        y = pad_t + plot_h * (1 - frac)
        val = vmin + span * frac
        canvas.create_line(pad_l, y, w - pad_r, y, fill=colors["grid"], width=1)
        label = unit_fmt(val) if unit_fmt else f"{val:,.0f}"
        canvas.create_text(pad_l - 8, y, text=label, fill=colors["text_faint"],
                            font=(theme.Fonts.family, 8), anchor="e")

    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad_l + (plot_w * i / (n - 1) if n > 1 else 0)
        y = pad_t + plot_h * (1 - (v - vmin) / span)
        pts.append((x, y))

    smooth_pts = _chaikin_smooth(pts, iterations=3)

    # gradient area fill under the curve: horizontal bands from line color -> card bg
    area_top = min(p[1] for p in smooth_pts)
    bands = 18
    for b in range(bands):
        t0 = b / bands
        t1 = (b + 1) / bands
        y0 = area_top + (pad_t + plot_h - area_top) * t0
        y1 = area_top + (pad_t + plot_h - area_top) * t1
        alpha = 1 - (b / bands) * 0.92
        band_color = lerp_color(colors["card"], line_color, alpha * 0.55)
        poly = [(pad_l, y1)]
        for px, py in smooth_pts:
            if y0 <= py <= y1 or True:
                poly.append((px, min(max(py, y0), y1)))
        poly.append((w - pad_r, y1))
        flat = [c for pt in poly for c in pt]
        if len(flat) >= 6:
            canvas.create_polygon(flat, fill=band_color, outline="")

    # the smoothed line itself
    flat_line = [c for pt in smooth_pts for c in pt]
    canvas.create_line(*flat_line, fill=line_color, width=2.5, smooth=True, capstyle="round")

    # data point dots + x labels
    step = max(1, n // 6)
    for i, (x, y) in enumerate(pts):
        if i == n - 1 or i % step == 0:
            canvas.create_oval(x - 3.5, y - 3.5, x + 3.5, y + 3.5, fill=colors["card"],
                                outline=line_color, width=2)
            if i < len(labels):
                canvas.create_text(x, h - pad_b + 14, text=labels[i], fill=colors["text_faint"],
                                    font=(theme.Fonts.family, 8))
    # always label the final point value
    last_x, last_y = pts[-1]
    canvas.create_text(last_x, max(last_y - 16, 12),
                        text=(unit_fmt(values[-1]) if unit_fmt else f"{values[-1]:,.0f}"),
                        fill=colors["text"], font=(theme.Fonts.family, 9, "bold"), anchor="s")


# --------------------------------------------------------------------------
# Grouped bar chart (income vs. expenses across months)
# --------------------------------------------------------------------------

def draw_bar_chart(canvas: tk.Canvas, categories, series, colors, unit_fmt=None, force=False):
    """series: list of (label, color_key_or_hex, values[len(categories)])"""
    w = canvas.winfo_width() or int(canvas["width"])
    h = canvas.winfo_height() or int(canvas["height"])
    if w < 10 or h < 10:
        canvas.after(50, lambda: draw_bar_chart(canvas, categories, series, colors, unit_fmt, force)
                     if canvas.winfo_exists() else None)
        return
    sig = _sig("bar", categories, series, colors.get("card"), w, h)
    if not force and _skip_if_clean(canvas, "_sig_bar", sig):
        return
    canvas.delete("all")

    pad_l, pad_r, pad_t, pad_b = 54, 16, 30, 28
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    canvas.create_rectangle(0, 0, w, h, fill=colors["card"], outline="")

    all_vals = [v for _, _, vals in series for v in vals]
    if not all_vals or not categories:
        canvas.create_text(w / 2, h / 2, text="No data yet — add a few transactions.",
                            fill=colors["text_faint"], font=(theme.Fonts.family, 10))
        return
    vmax = max(all_vals) or 1

    for i in range(4):
        frac = i / 3
        y = pad_t + plot_h * (1 - frac)
        canvas.create_line(pad_l, y, w - pad_r, y, fill=colors["grid"], width=1)
        val = vmax * frac
        label = unit_fmt(val) if unit_fmt else f"{val:,.0f}"
        canvas.create_text(pad_l - 8, y, text=label, fill=colors["text_faint"],
                            font=(theme.Fonts.family, 8), anchor="e")

    n_cat = len(categories)
    n_series = len(series)
    group_w = plot_w / n_cat
    bar_gap = group_w * 0.16
    bar_w = (group_w - bar_gap * (n_series + 1)) / n_series

    # legend: lay swatches out left to right, estimating each label's pixel
    # width from its character count (6px/char) since Tkinter doesn't expose
    # real text metrics before the text is actually drawn
    lx = pad_l
    for label, color_key, _ in series:
        color = colors.get(color_key, color_key)
        canvas.create_rectangle(lx, 6, lx + 10, 16, fill=color, outline="")
        canvas.create_text(lx + 15, 11, text=label, fill=colors["text_dim"],
                            font=(theme.Fonts.family, 8), anchor="w")
        lx += 15 + len(label) * 6 + 16

    for ci, cat in enumerate(categories):
        gx0 = pad_l + ci * group_w
        for si, (label, color_key, vals) in enumerate(series):
            color = colors.get(color_key, color_key)
            v = vals[ci] if ci < len(vals) else 0
            bar_h = (v / vmax) * plot_h if vmax else 0
            x0 = gx0 + bar_gap + si * (bar_w + bar_gap)
            x1 = x0 + bar_w
            y1 = pad_t + plot_h
            y0 = y1 - bar_h
            if bar_h > 1:
                rounded_rect(canvas, x0, y0, x1, y1, r=min(5, bar_w / 2), fill=color, outline="")
        canvas.create_text(gx0 + group_w / 2, h - pad_b + 14, text=cat,
                            fill=colors["text_faint"], font=(theme.Fonts.family, 8))


# --------------------------------------------------------------------------
# Donut chart (envelope allocation, need/want/saving split)
# --------------------------------------------------------------------------

def draw_donut_chart(canvas: tk.Canvas, segments, colors, center_label="", center_sub="", force=False):
    """segments: list of (label, value, color_hex)"""
    w = canvas.winfo_width() or int(canvas["width"])
    h = canvas.winfo_height() or int(canvas["height"])
    if w < 10 or h < 10:
        canvas.after(50, lambda: draw_donut_chart(canvas, segments, colors, center_label, center_sub, force)
                     if canvas.winfo_exists() else None)
        return
    sig = _sig("donut", segments, colors.get("card"), center_label, center_sub, w, h)
    if not force and _skip_if_clean(canvas, "_sig_donut", sig):
        return
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=colors["card"], outline="")

    total = sum(max(v, 0) for _, v, _ in segments)
    diam = min(w, h) * 0.62
    cx, cy = diam / 2 + 14, h / 2
    r_out = diam / 2
    r_in = r_out * 0.58

    if total <= 0:
        canvas.create_oval(cx - r_out, cy - r_out, cx + r_out, cy + r_out,
                            outline=colors["grid"], width=2)
        canvas.create_text(cx, cy, text="No spend yet", fill=colors["text_faint"],
                            font=(theme.Fonts.family, 9))
    else:
        start = 90.0
        for label, value, color in segments:
            if value <= 0:
                continue
            extent = -360.0 * (value / total)
            canvas.create_arc(cx - r_out, cy - r_out, cx + r_out, cy + r_out,
                               start=start, extent=extent, fill=color, outline=colors["card"],
                               width=2, style="pieslice")
            start += extent
        canvas.create_oval(cx - r_in, cy - r_in, cx + r_in, cy + r_in,
                            fill=colors["card"], outline="")
        canvas.create_text(cx, cy - 8, text=center_label, fill=colors["text"],
                            font=(theme.Fonts.family, 13, "bold"))
        canvas.create_text(cx, cy + 12, text=center_sub, fill=colors["text_faint"],
                            font=(theme.Fonts.family, 8))

    # legend to the right
    lx = diam + 40
    ly = cy - len(segments) * 11
    for label, value, color in segments:
        pct = f"{(value / total * 100):.0f}%" if total > 0 else "0%"
        canvas.create_oval(lx, ly, lx + 10, ly + 10, fill=color, outline="")
        canvas.create_text(lx + 16, ly + 5, text=f"{label} · {pct}", fill=colors["text_dim"],
                            font=(theme.Fonts.family, 9), anchor="w")
        ly += 22


def draw_period_heatmap(canvas: tk.Canvas, daily_totals, colors, unit_fmt=None, force=False):
    """daily_totals: an ordered {date_iso: total} dict covering every
    consecutive day of one reporting period, as returned by
    finance_core.daily_spend_totals. Shades a plain Day-1..Day-N grid (not
    aligned to real weekdays) by spend intensity, so the chart still renders
    correctly for a custom month_start_day period that spans two calendar
    months -- the previous version rendered a literal weekday-aligned
    calendar grid for one named (year, month), which had no sensible way to
    show days that belonged to the reporting period but fell in a different
    real calendar month, and silently dropped them instead."""
    w = canvas.winfo_width() or int(canvas["width"])
    h = canvas.winfo_height() or int(canvas["height"])
    if w < 10 or h < 10:
        canvas.after(50, lambda: draw_period_heatmap(canvas, daily_totals, colors, unit_fmt, force)
                     if canvas.winfo_exists() else None)
        return
    sig = _sig("period_heatmap", tuple(daily_totals.items()), colors.get("card"), w, h)
    if not force and _skip_if_clean(canvas, "_sig_period_heatmap", sig):
        return
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=colors["card"], outline="")

    days = list(daily_totals.items())
    if not days:
        return

    top_pad, side_pad = 4, 4
    cols = 7
    rows = (len(days) + cols - 1) // cols
    cell_w = (w - side_pad * 2) / cols
    cell_h = (h - top_pad - side_pad) / rows if rows else 0

    max_val = max(v for _, v in days)
    accent = colors.get("bad", colors["accent"])

    for i, (_date_iso, value) in enumerate(days):
        row, col = divmod(i, cols)
        x0 = side_pad + col * cell_w
        y0 = top_pad + row * cell_h
        x1, y1 = x0 + cell_w - 2, y0 + cell_h - 2
        t = min(value / max_val, 1.0) if max_val > 0 else 0.0
        fill = lerp_color(colors["card"], accent, t)
        rounded_rect(canvas, x0, y0, x1, y1, r=4, fill=fill, outline=colors["grid"])
        canvas.create_text(x0 + 7, y0 + 8, text=f"Day {i + 1}", fill=colors["text_dim"],
                            font=(theme.Fonts.family, 7), anchor="w")
        if value > 0:
            label_text = unit_fmt(value) if unit_fmt else f"{value:,.0f}"
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2 + 6, text=label_text,
                                fill=colors["text"], font=(theme.Fonts.family, 7))


# --------------------------------------------------------------------------
# Progress ring (single value vs. target — FI progress, savings rate, etc.)
# --------------------------------------------------------------------------

def draw_progress_ring(canvas: tk.Canvas, pct, colors, label="", ring_color=None, force=False):
    w = canvas.winfo_width() or int(canvas["width"])
    h = canvas.winfo_height() or int(canvas["height"])
    if w < 10 or h < 10:
        canvas.after(50, lambda: draw_progress_ring(canvas, pct, colors, label, ring_color, force)
                     if canvas.winfo_exists() else None)
        return
    sig = _sig("ring", round(pct, 4), colors.get("card"), label, ring_color or colors.get("accent"), w, h)
    if not force and _skip_if_clean(canvas, "_sig_ring", sig):
        return
    canvas.delete("all")
    canvas.create_rectangle(0, 0, w, h, fill=colors["card"], outline="")
    pct = max(0.0, min(pct, 1.0))
    ring_color = ring_color or colors["accent"]
    diam = min(w, h) - 10
    cx, cy = w / 2, h / 2
    r = diam / 2
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=colors["grid"], width=8)
    if pct > 0:
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * pct,
                           outline=ring_color, width=8, style="arc")
    canvas.create_text(cx, cy - 6, text=f"{pct*100:.0f}%", fill=colors["text"],
                        font=(theme.Fonts.family, 16, "bold"))
    canvas.create_text(cx, cy + 16, text=label, fill=colors["text_faint"],
                        font=(theme.Fonts.family, 8))
