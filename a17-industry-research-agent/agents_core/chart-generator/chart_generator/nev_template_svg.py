"""SVG layouts for the A17 reference figures. All plotted values are caller-supplied."""

from __future__ import annotations

from html import escape
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .nev_template import Figure

INK = "#12201d"
MUTED = "#53635f"
GRID = "#e4ebe8"
LIGHT = "#f3f7f5"
GREEN = "#0b4f4a"
TEAL = "#2f7d72"
BLUE = "#1d6f8c"
GOLD = "#b8872f"
RED = "#a33a2b"
PALETTE = (GREEN, TEAL, GOLD, BLUE, "#7fa79f")
COMPANY = dict(zip(("比亚迪", "长安汽车", "赛力斯", "宁德时代", "亿纬锂能"), PALETTE))
CHAIN_TEMPLATE = Path(__file__).with_name("assets") / "a17_nev_industry_chain_2025.svg"


def text(x, y, value, size=14, color=MUTED, anchor="start", weight=400):
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(str(value))}</text>')


def rect(x, y, width, height, fill, stroke="none", radius=0):
    return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{height:.2f}" '
            f'fill="{fill}" stroke="{stroke}" rx="{radius}"/>')


def line(x1, y1, x2, y2, color=GRID, width=1, dashed=False):
    pattern = ' stroke-dasharray="6 4"' if dashed else ""
    return (f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{width}"{pattern}/>')


def dot(x, y, color, radius=5):
    return f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="{color}"/>'


def polyline(points, color, dashed=False):
    coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    pattern = ' stroke-dasharray="7 5"' if dashed else ""
    return f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.5"{pattern}/>'


def maximum(values, step=None):
    value = max(values, default=0)
    if step is None:
        step = 10 ** math.floor(math.log10(value)) / 2 if value > 0 else 1
    return max(step, math.ceil(value / step) * step)


def values(cells):
    return [float(cell.value) if cell is not None else None for cell in cells]


def legends(names, parts, *, x=56, y=100):
    for i, name in enumerate(names):
        color = COMPANY.get(name, PALETTE[i % len(PALETTE)])
        parts.extend((rect(x, y - 10, 11, 11, color, radius=2), text(x + 17, y, name, 12)))
        x += max(100, len(name) * 13 + 36)


def vertical_axis(parts, x, right, top, bottom, low, high, *, right_axis=False):
    for i in range(6):
        tick = low + (high - low) * i / 5
        y = bottom - (bottom - top) * i / 5
        parts.append(text(right + 10 if right_axis else x - 10, y + 4, f"{tick:g}",
                          11, MUTED, "start" if right_axis else "end"))
        if not right_axis:
            parts.append(line(x, y, right, y))


def timeline(data: Figure, parts: list[str]) -> None:
    x, right, top, bottom = 96, 1066, 134, 478
    count = len(data.categories)
    names = list(data.series)
    has_bars = data.layout in {"volume_growth", "grouped"}
    is_combo = data.layout == "volume_growth"
    is_penetration = data.layout == "penetration"
    rows = {name: values(cells) for name, cells in data.series.items()}
    plotted = [v for name in (names[:1] if is_combo else names) for v in rows[name] if v is not None]
    low = min(0.0, min(plotted, default=0))
    high = max(65, maximum(plotted)) if is_penetration else maximum(plotted)
    if high == low:
        high += 1
    recent = [value for value in rows[names[1]] if value is not None] if is_combo else []
    secondary = maximum(recent, 10) if is_combo else high
    secondary_low = min(0.0, min(recent, default=0))
    step = (right - x) / (count if has_bars else max(1, count - 1))
    xs = [x + step * (i + 0.5 if has_bars else i) for i in range(count)]

    def y(value, second=False):
        floor, ceiling = (secondary_low, secondary) if second else (low, high)
        return bottom - (value - floor) / (ceiling - floor) * (bottom - top)

    legends(names, parts)
    parts.append(text(x, top - 10, data.units[names[0]], 11))
    vertical_axis(parts, x, right, top, bottom, low, high)
    if is_combo:
        vertical_axis(parts, x, right, top, bottom, secondary_low, secondary, right_axis=True)
        parts.append(text(right + 12, top - 10, "%", 11))
    if is_penetration:
        details = data.details
        start, end = details["peak"], details["end"]
        parts.append(rect(xs[start], top, xs[end] - xs[start], bottom - top, "#f9eee5"))
        steps = []
        for i, mean in enumerate(details["average"]):
            if i:
                steps.append((xs[i], y(details["average"][i - 1])))
            steps.append((xs[i], y(mean)))
        for guide in (20, 40, 60):
            parts.extend((line(x, y(guide), right, y(guide), MUTED, 1, True),
                          text(right + 10, y(guide) + 4, f"{guide}%", 12)))
        parts.append(polyline(steps, GOLD, True))
        for i, mean in enumerate(details["average"]):
            if i == 0 or data.categories[i].endswith("-01"):
                parts.append(text(xs[i] + 8, y(mean) - 10, f"{mean:.2f}%", 11, GOLD))
        parts.append(text((xs[start] + xs[end]) / 2, top + 19, f"最大回撤 −{details['drawdown']:.1f} 个百分点", 13, RED, "middle"))

    for j, (name, row) in enumerate(rows.items()):
        color = RED if is_combo and j == 1 else COMPANY.get(name, PALETTE[j % len(PALETTE)])
        if has_bars and not (is_combo and j == 1):
            bars = 1 if is_combo else len(rows)
            width = min(66, step * .65 / bars)
            for i, value in enumerate(row):
                if value is None:
                    continue
                left = xs[i] + (j - bars / 2) * width
                level = y(value)
                parts.append(rect(left, min(level, y(0)), width - 3, abs(level - y(0)), color, radius=2))
                parts.append(text(left + width / 2, level - 9, f"{value:,.2f}", 12, color, "middle", 600))
            continue
        second = is_combo and j == 1
        segment = []
        for i, value in enumerate(row):
            if value is None:
                if segment:
                    parts.append(polyline(segment, color))
                    segment = []
                continue
            coord = xs[i], y(value, second)
            segment.append(coord)
            if count <= 12 or is_penetration:
                parts.append(dot(*coord, color, 4 if count <= 12 else 2))
            if count <= 12:
                parts.append(text(coord[0], coord[1] - 11, f"{value:,.2f}", 11, color, "middle"))
        if segment:
            parts.append(polyline(segment, color))
            if data.number == 15 and row[-1] is not None:
                xx, yy = segment[-1]
                parts.append(dot(xx, yy, color, 4))
                parts.append(text(xx + 8, yy + 4, f"{row[-1]:.2f}", 12, color))
    ticks = list(range(count)) if count <= 12 else sorted({0, count - 1, *range(11, count - 1, 12)})
    for i in ticks:
        parts.append(text(xs[i], bottom + 25, data.categories[i], 12, MUTED, "middle"))


def horizontal(data: Figure, parts: list[str]) -> None:
    row = values(next(iter(data.series.values())))
    x, width, top = 258, 790, 146
    upper = 100 if data.layout == "percentile" else maximum(row, 10)
    for i, (name, value) in enumerate(zip(data.categories, row)):
        y = top + i * 60
        color = COMPANY.get(name, GREEN)
        parts.extend((text(64, y + 22, name, 15, INK, weight=700),
                      rect(x, y, width, 30, LIGHT, radius=4),
                      rect(x, y, width * value / upper, 30, color, radius=4),
                      text(x + width * value / upper + 12, y + 22, f"{value:.2f}%", 14, INK)))
    if data.layout == "percentile":
        for p in range(0, 101, 20):
            parts.append(text(x + width * p / 100, 374, f"{p}%", 12, MUTED, "middle"))
        details = data.details
        parts.append(text(64, 440, "n=60；基准 PB：" + "   ".join(
            f"{name} {value:.4f} 倍" for name, value in zip(data.categories, details["current"])
        ), 14))
    else:
        parts.extend((line(224, top - 5, 224, top + 155, GOLD, 2),
                      line(217, top - 5, 224, top - 5, GOLD, 2),
                      line(217, top + 155, 224, top + 155, GOLD, 2)))
        parts.append(text(64, 483, f"CR3 {data.details['cr3']:.2f}%    HHI {data.details['hhi']:.4f}", 15, GREEN, weight=700))


def composition(data: Figure, parts: list[str]) -> None:
    legends(data.series, parts)
    x0, width = 245, 785
    for i, label in enumerate(data.categories):
        y = 180 + 152 * i
        parts.append(text(65, y + 14, label, 15, INK, weight=700))
        parts.append(text(65, y + 41, f"{data.details['totals'][i]:,.2f} 亿元", 13))
        x = x0
        for j, cells in enumerate(data.series.values()):
            v = float(cells[i].value)
            color = PALETTE[j % len(PALETTE)]
            span = width * v / 100
            parts.append(rect(x, y, span, 52, color))
            if v >= 10:
                parts.append(text(x + span / 2, y + 34, f"{v:.2f}%", 15, "#fff", "middle", 600))
            elif v >= 1:
                parts.append(text(x + span / 2, y - 10, f"{v:.2f}%", 13, color, "middle", 600))
            else:
                parts.append(line(x + span, y + 25, 1050, y + 25, color, dashed=True))
                parts.append(text(1055, y + 29, f"{v:.2f}%", 12, color))
            x += span


def small_multiples(data: Figure, parts: list[str]) -> None:
    for j, (name, row) in enumerate(data.series.items()):
        x = 40 + j * 385
        values_ = values(row)
        low = min(0, min(values_))
        high = 100 if name == "资产负债率" else maximum(values_, 5)
        parts.extend((rect(x, 118, 353, 346, "#fff", GRID, 7),
                      text(x + 18, 155, name, 18, INK, weight=700),
                      text(x + 322, 155, "%", 12, MUTED, "end")))
        origin, width = x + 106 + (0 - low) / (high - low) * 171, 171
        for i, (company, value) in enumerate(zip(data.categories, values_)):
            y = 199 + i * 63
            end = x + 106 + (value - low) / (high - low) * width
            parts.extend((text(x + 17, y + 17, company, 13, INK),
                          rect(x + 106, y, width, 23, LIGHT, radius=3),
                          rect(min(origin, end), y, abs(end - origin), 23, COMPANY[company], radius=3),
                          text(max(origin, end) + 7, y + 17, f"{value:.2f}%", 12, INK)))
        for i in range(3):
            parts.append(text(x + 106 + i * width / 2, 421, f"{low + i*(high-low)/2:g}",
                              11, MUTED, "middle"))


def cashflow_panels(data: Figure, parts: list[str]) -> None:
    row = values(next(iter(data.series.values())))
    for i, (name, start, end) in enumerate(data.details["panels"]):
        x = 56 + 562 * i
        group = row[start:end]
        low, high = min(0, min(group)), maximum(group, 100)
        mean = sum(group) / len(group)
        y_for = lambda value: 443 - (value - low) / (high - low) * 241
        parts.append(rect(x, 116, 520, 404, "#fff", GRID, 8))
        parts.append(text(x + 18, 154, f"{name} · 均值 {mean:,.2f} 亿元", 18, INK, weight=700))
        vertical_axis(parts, x + 70, x + 484, 202, 443, low, high)
        parts.append(line(x + 70, y_for(mean), x + 484, y_for(mean), GOLD, 2, True))
        for offset, value in enumerate(group):
            company = data.categories[start + offset]
            xx = x + 70 + 414 * (offset + .5) / len(group)
            yy = y_for(value)
            parts.extend((dot(xx, yy, COMPANY[company], 6),
                          text(xx, yy - 13, f"{value:,.2f}", 12, INK, "middle"),
                          text(xx, 475, company, 13, MUTED, "middle")))


def render_figure(data: Figure, title: str) -> str:
    if data.layout == "chain_structure":
        return CHAIN_TEMPLATE.read_text(encoding="utf-8")

    parts = [rect(0, 0, 1200, 570, "#fff"),
             text(48, 46, f"图 {data.number}  {title}", 24, INK, weight=700)]
    if data.layout == "cashflow_panels":
        cashflow_panels(data, parts)
    elif data.layout == "small_multiples":
        small_multiples(data, parts)
    elif data.layout == "composition":
        composition(data, parts)
    elif data.layout in {"rank", "percentile"}:
        horizontal(data, parts)
    else:
        timeline(data, parts)
    parts.append(text(48, 544, data.note, 12))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="570" viewBox="0 0 1200 570" '
            'role="img" style="font-family:PingFang SC,Noto Sans CJK SC,sans-serif">'
            f'<title>{escape(title)}</title>{"".join(parts)}</svg>')
