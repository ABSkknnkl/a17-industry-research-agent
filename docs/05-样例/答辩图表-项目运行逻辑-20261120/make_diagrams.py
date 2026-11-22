#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A17 答辩图册：用统一 SVG 语言绘制项目运行逻辑图。

输出：svg/00..06*.svg（1600x900），再由 render_png.py 导出 2x PNG。
"""
from __future__ import annotations

from pathlib import Path
import html as _html
import re

ROOT = Path(__file__).resolve().parent
SVG_DIR = ROOT / "svg"
SVG_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1600, 900

# ---------- palette ----------
PAPER = "#F5F0E5"
CARD = "#FFFDF8"
INK = "#1E2421"
INK2 = "#343B36"
MUTED = "#6F6B60"
LINE = "#D8D0BD"
LINE2 = "#C3B9A4"

A1 = {"main": "#2F5D7C", "soft": "#E9F1F5", "line": "#B7CDDB", "dark": "#234A63"}
A2 = {"main": "#2E6B57", "soft": "#E8F2EC", "line": "#B5D2C4", "dark": "#215143"}
A3 = {"main": "#9A6A2F", "soft": "#F7EDDD", "line": "#DFC9A5", "dark": "#7A5220"}
A4 = {"main": "#7A4E63", "soft": "#F4EAEF", "line": "#D9C0CB", "dark": "#5E394B"}
A5 = {"main": "#8C4033", "soft": "#F8E8E3", "line": "#DFBCB4", "dark": "#6D3026"}
PLAT = {"main": "#3D4852", "soft": "#EDF0F2", "line": "#C4CCD2", "dark": "#2B343C"}
HUMAN = {"main": "#C07A2C", "soft": "#FBF1E1", "line": "#E8CDA4", "dark": "#8F571B"}
LOOP = {"main": "#6E5A9E", "soft": "#F0ECF8", "line": "#CDC2E4", "dark": "#53407D"}
WHITE = "#FFFFFF"

SANS = "'PingFang SC','Hiragino Sans GB','Noto Sans SC','Microsoft YaHei',sans-serif"
SERIF = "'Songti SC','Noto Serif SC','STSong','SimSun',serif"


def esc(s: str) -> str:
    return _html.escape(str(s), quote=False)


def char_u(ch: str) -> float:
    if ord(ch) < 128:
        return 0.56
    if ch in "，。、；：（）【】「」“”‘’·—":
        return 0.92
    return 1.0


def text_w(s: str, fs: float) -> float:
    return sum(char_u(c) for c in s) * fs


def wrap_text(text: str, width: float, fs: float) -> list[str]:
    maxu = max(1.0, width / fs)
    lines: list[str] = []
    ascii_word = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./%-")
    for para in str(text).split("\n"):
        cur, curu = "", 0.0
        i = 0
        while i < len(para):
            ch = para[i]
            # keep latin words / file names / metric ids as one token
            if ch in ascii_word:
                j = i
                while j < len(para) and para[j] in ascii_word:
                    j += 1
                token = para[i:j]
                tu = sum(char_u(c) for c in token)
                if cur and curu + tu > maxu:
                    lines.append(cur)
                    cur, curu = "", 0.0
                if tu > maxu and not cur:
                    for c in token:
                        u = char_u(c)
                        if cur and curu + u > maxu:
                            lines.append(cur)
                            cur, curu = "", 0.0
                        cur += c
                        curu += u
                else:
                    cur += token
                    curu += tu
                i = j
                continue
            u = char_u(ch)
            if cur and curu + u > maxu:
                if ch in "，。、；：）】」’”":
                    cur += ch
                    lines.append(cur)
                    cur, curu = "", 0.0
                else:
                    lines.append(cur)
                    cur, curu = ch, u
            else:
                cur += ch
                curu += u
            i += 1
        if cur:
            lines.append(cur)
    return lines or [""]


class SVG:
    def __init__(self):
        self.parts: list[str] = []
        self.defs: list[str] = []
        self._markers: set[str] = set()
        self.defs.append(
            '<filter id="soft" x="-12%" y="-12%" width="124%" height="132%">'
            '<feDropShadow dx="0" dy="2" stdDeviation="5" flood-color="#3A2E1D" flood-opacity="0.07"/>'
            "</filter>"
        )

    def add(self, raw: str):
        self.parts.append(raw)

    def marker(self, color: str) -> str:
        mid = "arw" + color.replace("#", "")
        if mid not in self._markers:
            self._markers.add(mid)
            self.defs.append(
                f'<marker id="{mid}" viewBox="0 0 9 9" refX="8" refY="4.5" '
                f'markerWidth="5.5" markerHeight="5.5" orient="auto">'
                f'<path d="M0,0 L9,4.5 L0,9 Z" fill="{color}"/></marker>'
            )
        return mid

    # ---------- primitives ----------
    def rect(self, x, y, w, h, fill, stroke="none", rx=10, sw=1, dash=None, opacity=1, shadow=False):
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        filt = ' filter="url(#soft)"' if shadow else ""
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{extra} opacity="{opacity}"{filt}/>'
        )

    def circle(self, cx, cy, r, fill, stroke="none", sw=1):
        self.add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, fs=12, color=INK, weight=400, anchor="left", serif=False,
             spacing=None, opacity=1, italic=False):
        font = SERIF if serif else SANS
        anchor = {"right": "end", "left": "start", "center": "middle"}.get(anchor, anchor)
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        it = ' font-style="italic"' if italic else ""
        self.add(
            f'<text x="{x}" y="{y}" font-family="{font}" font-size="{fs}" fill="{color}" '
            f'font-weight="{weight}" text-anchor="{anchor}"{ls}{it} opacity="{opacity}">{esc(s)}</text>'
        )

    def line(self, x1, y1, x2, y2, color=LINE, sw=1.2, dash=None, marker=False, opacity=1):
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{self.marker(color)})"' if marker else ""
        self.add(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="{sw}"{dash_attr}{m} opacity="{opacity}"/>'
        )

    def path(self, d, color, sw=1.6, dash=None, marker=False, opacity=1):
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        m = f' marker-end="url(#{self.marker(color)})"' if marker else ""
        self.add(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" '
            f'{dash_attr}{m} opacity="{opacity}" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    def diamond(self, cx, cy, r, fill, stroke="none", sw=1):
        self.add(
            f'<path d="M{cx},{cy-r} L{cx+r},{cy} L{cx},{cy+r} L{cx-r},{cy} Z" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
        )

    def pill(self, x, y, label, fill, color, fs=9.2, h=17, pad=7, stroke="none", anchor="left"):
        w = text_w(label, fs) + 2 * pad
        if anchor == "right":
            x = x - w
        self.rect(x, y, w, h, fill, stroke, rx=h / 2, sw=0.8)
        self.text(x + w / 2, y + h / 2 + fs * 0.34, label, fs, color, 600, anchor="middle")
        return w

    def body(self, x, y, w, text, fs=10.8, lh=16, color=INK2, max_lines=None, weight=400):
        lines = wrap_text(text, w, fs)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and text_w(last + "…", fs) > w:
                last = last[:-1]
            lines[-1] = last + "…"
        yy = y
        for ln in lines:
            self.text(x, yy, ln, fs, color, weight)
            yy += lh
        return yy

    def svg(self) -> str:
        defs = "<defs>" + "".join(self.defs) + "</defs>"
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" '
            'viewBox="0 0 1600 900">' + defs + "".join(self.parts) + "</svg>"
        )

    def save(self, name: str):
        (SVG_DIR / name).write_text(self.svg(), encoding="utf-8")
        print("saved", name)


# ---------- shared chrome ----------
def canvas(s: SVG):
    s.rect(0, 0, W, H, PAPER, "none", rx=0)
    # paper texture: sparse dots
    for yy in range(28, H, 44):
        for xx in range(28, W, 44):
            s.add(f'<circle cx="{xx}" cy="{yy}" r="0.9" fill="#DCD4C2" opacity="0.55"/>')
    # top hairline
    s.rect(0, 0, W, 4, "#E7DFCE", "none", rx=0)


def header(s: SVG, num: str, eyebrow: str, title: str, subtitle: str, accent: str,
           chips: list[tuple[str, str]] | None = None):
    canvas(s)
    s.rect(64, 40, 6, 58, accent, "none", rx=0)
    s.text(84, 57, eyebrow, 10.2, accent, 700, spacing=1.7)
    s.text(84, 99, title, 32.5, INK, 700, serif=True)
    s.text(84, 128, subtitle, 12.8, MUTED)
    if chips:
        right = 1536
        for label, color in reversed(chips):
            w = s.pill(right, 45, label, CARD, color, fs=9.6, h=21, pad=10,
                       stroke=LINE, anchor="right")
            right -= w + 9
    s.line(64, 146, 1536, 146, LINE, 1.1)


def footer(s: SVG, num: str, total: int = 7):
    s.line(64, 862, 1536, 862, LINE, 1.1)
    s.text(64, 883, "同花顺 A17 · 行业研究报告智能生成与人机协同优化系统", 10.2, MUTED)
    s.text(1536, 883, f"{num} / {total:02d}", 10.2, MUTED, anchor="right")


def section_label(s: SVG, x, y, label, color=MUTED, fs=10.2):
    s.text(x, y, label, fs, color, 700, spacing=1.5)


def panel(s: SVG, x, y, w, h, fill=CARD, stroke=LINE, rx=16, sw=1.1, shadow=True):
    s.rect(x, y, w, h, fill, stroke, rx=rx, sw=sw, shadow=shadow)


def card(s: SVG, x, y, w, h, theme, fill=None, dash=None, sw=1.0):
    s.rect(x, y, w, h, fill or theme["soft"], theme["line"], rx=12, sw=sw, dash=dash)
    s.rect(x + 1, y + 11, 4, h - 22, theme["main"], "none", rx=2)


def step_card(s: SVG, x, y, w, h, n, title, body, theme, tag=None):
    card(s, x, y, w, h, theme, fill=CARD)
    s.circle(x + 23, y + 22, 10.5, theme["main"])
    s.text(x + 23, y + 26, str(n), 10.5, WHITE, 700, anchor="middle")
    s.text(x + 42, y + 26, title, 13.0, INK, 700)
    if tag:
        colors = {
            "LLM": LOOP, "确定性": A2, "规则": PLAT, "回补": HUMAN, "循环": A5,
        }
        th = colors.get(tag, PLAT)
        s.pill(x + w - 10, y + 10, tag, th["soft"], th["dark"], fs=8.4, h=15, pad=7, anchor="right",
               stroke=th["line"])
    s.body(x + 42, y + 44, w - 58, body, fs=10.2, lh=14.2, color=INK2, max_lines=2)


def info_card(s: SVG, x, y, w, h, theme, title, body, kicker=None, tag=None):
    card(s, x, y, w, h, theme, fill=CARD)
    yy = y + 27
    if kicker:
        s.text(x + 18, y + 22, kicker, 9.4, theme["dark"], 700, spacing=1.3)
        yy = y + 40
    s.text(x + 18, yy, title, 13.0, INK, 700)
    if tag:
        s.pill(x + w - 10, y + 12, tag, theme["soft"], theme["dark"], fs=8.3, h=15, pad=7,
               anchor="right", stroke=theme["line"])
    body_y = yy + 15
    max_lines = max(1, int((h - (body_y - y) - 7) / 14.4))
    s.body(x + 18, body_y, w - 34, body, fs=10.0, lh=14.4, color=INK2, max_lines=max_lines)


def agent_card(s: SVG, x, y, w, h, theme, num, title, en, lines, out_tag):
    card(s, x, y, w, h, theme, fill=CARD)
    s.circle(x + 24, y + 27, 12.5, theme["main"])
    s.text(x + 24, y + 31, num, 11.2, WHITE, 700, anchor="middle")
    s.text(x + 46, y + 31, title, 15.2, INK, 700)
    s.text(x + 46, y + 48, en, 8.6, MUTED, 600, spacing=1.2)
    yy = y + 70
    for ln in lines:
        wrapped = wrap_text(ln, w - 34, 10.9)
        for item in wrapped[:2]:
            s.text(x + 18, yy, item, 10.9, INK2)
            yy += 15.4
    s.pill(x + 18, y + h - 24, out_tag, theme["soft"], theme["dark"], fs=8.8, h=17, pad=8,
           stroke=theme["line"])


def collab_card(s: SVG, x, y, w, h, label, title, body, color):
    s.rect(x, y, w, h, CARD, LINE, rx=11, sw=1.0)
    s.rect(x + 1, y + 8, 4, h - 16, color, "none", rx=2)
    s.text(x + 18, y + 22, label, 8.9, color, 700, spacing=1.2)
    s.text(x + 18, y + 44, title, 11.8, INK, 700)
    s.body(x + 18, y + 62, w - 32, body, fs=9.8, lh=13.4, color=INK2, max_lines=2)


def arrow(s: SVG, x1, y1, x2, y2, color, sw=1.8, dash=None):
    s.line(x1, y1, x2, y2, color, sw=sw, dash=dash, marker=True)


# =====================================================================
# 00 总览与框架
# =====================================================================
def page_00():
    s = SVG()
    header(
        s, "00", "A17 / RUNNING LOGIC · 00",
        "先回答一个问题：这个项目到底用了什么框架？",
        "一句话：没有用现成的智能体框架，自己搭了一条有状态、能回滚、每段可审核的五阶段流水线。",
        PLAT["main"],
        chips=[("自研流水线", PLAT["main"]), ("5 个智能体", A1["main"]), ("全链证据", A2["main"])],
    )

    # left panel: framework
    panel(s, 64, 166, 720, 566)
    x = 96
    s.text(x, 202, "THE FRAMEWORK QUESTION", 9.8, HUMAN["dark"], 700, spacing=1.6)
    s.text(x, 244, "没有用 LangGraph / CrewAI / AutoGen。", 20.5, INK, 700, serif=True)
    s.text(x, 274, "用的是：FastAPI + 自研状态机 + 五个独立 Python 包。", 14.0, A1["dark"], 600)
    s.body(x, 300, 656,
           "五个智能体各自是一个包；状态机负责“谁先跑、什么时候停、失败回到哪”。"
           "不引入向量数据库，所有数据以结构化 JSON 和证据字典在阶段间传递。",
           fs=11.2, lh=18, color=INK2, max_lines=3)
    s.line(x, 356, x + 656, 356, LINE, 1)

    rows = [
        ("前端", "Vue 3 + TypeScript + Element Plus + ECharts"),
        ("后端", "FastAPI + Pydantic v2 + httpx（Python 3.11+）"),
        ("编排", "自研 StateMachine + FiveAgentsAdapter"),
        ("模型", "OpenAI 兼容接口；不依赖 LangChain、不用向量库"),
        ("交付", "Playwright 无头浏览器排版 + PyMuPDF 页码校验"),
    ]
    yy = 386
    for label, value in rows:
        s.text(x, yy, label, 10.2, MUTED, 700, spacing=1.4)
        s.text(x + 62, yy, value, 12.0, INK, 500)
        s.line(x, yy + 16, x + 656, yy + 16, "#E7DFCE", 1)
        yy += 46

    # callout
    s.rect(x, 616, 656, 92, HUMAN["soft"], HUMAN["line"], rx=12, sw=1)
    s.text(x + 18, 640, "为什么不用现成框架？", 11.2, HUMAN["dark"], 700)
    s.body(x + 18, 660, 620,
           "金融研报要的是：阶段能停、版本能回、失败能重跑、每个数字能对账。"
           "通用 Agent 框架的隐藏状态和自动重试，反而让这四件事不好控。",
           fs=10.2, lh=14.5, color=INK2, max_lines=3)

    # right panel: five stages
    panel(s, 816, 166, 720, 566)
    s.text(848, 202, "FIVE STAGES, ONE PIPELINE", 9.8, A1["dark"], 700, spacing=1.6)
    s.text(848, 232, "五个工位，一条流水线；相邻两段只通过产物交接。", 13.2, INK, 600)
    s.line(874, 268, 874, 712, LINE2, 1.2)

    stages = [
        (A1, "A1", "数据获取", "DATA FETCH",
         "把问题拆成取数清单，去问财把证据取回来；缺的补，补不到留缺口。7 大领域 + 验收矩阵，先验后交。", "→ dataset.json"),
        (A2, "A2", "数据解读", "INTERPRET",
         "先把 CAGR、杜邦、勾稽算死，再让模型解释；结论逐条挂证据。算不出来就留缺口，不许编。", "→ interpretation_report.json"),
        (A3, "A3", "图表生成", "CHART",
         "先验每个数据点有没有证据，再决定画什么图；缺数回采。补不到就不画，不用示意值。", "→ chart_result.json"),
        (A4, "A4", "章节撰写", "WRITE",
         "7 章 21 节并发写；每段过数字与引用审计，不过就改或删。单章可重跑，不重写全书。", "→ chapter_result.json"),
        (A5, "A5", "报告融合", "FUSION",
         "合稿 + 四维对账 + 三格式导出；有硬伤就锁正式下载。受限草稿 409，签发权在人。", "→ md / html / pdf"),
    ]
    ys = [252, 348, 444, 540, 636]
    for (theme, num, name, en, desc, out), y in zip(stages, ys):
        s.rect(848, y, 656, 88, theme["soft"], theme["line"], rx=11, sw=1)
        s.rect(849, y + 8, 4, 72, theme["main"], "none", rx=2)
        s.circle(874, y + 30, 13, theme["main"])
        s.text(874, y + 34, num, 10.6, WHITE, 700, anchor="middle")
        s.text(898, y + 28, name, 15.2, INK, 700)
        s.text(898, y + 44, en, 8.4, MUTED, 600, spacing=1.3)
        s.body(898, y + 62, 470, desc, fs=10.0, lh=13.5, color=INK2, max_lines=2)
        s.pill(1492, y + 12, out, CARD, theme["dark"], fs=8.2, h=15, pad=6,
               anchor="right", stroke=theme["line"])

    # bottom: three mechanisms
    mech = [
        (PLAT, "状态机", "五段状态 + revision；人工改了数据，后台旧结果不会覆盖新版本。审核、取消、重跑都走同一把任务锁。"),
        (A2, "证据链", "record_id 从 A1 一路带到 PDF 角标；每个数字都能回到原始记录。悬空引用会被拦下，不进交付稿。"),
        (HUMAN, "人机门禁", "每段结束可停、可改、可重跑；系统只判断能不能签，签发权在人。改完必须复验，旧质检与旧 PDF 自动作废。"),
    ]
    xs = [64, 553, 1042]
    for (theme, title, body), x in zip(mech, xs):
        s.rect(x, 752, 462, 94, CARD, LINE, rx=12, sw=1)
        s.rect(x + 1, 761, 4, 76, theme["main"], "none", rx=2)
        s.text(x + 20, 780, title, 12.4, theme["dark"], 700)
        s.body(x + 20, 798, 424, body, fs=10.2, lh=14.2, color=INK2, max_lines=2)

    footer(s, "00")
    s.save("00-总览与框架.svg")


# =====================================================================
# 01 总体框架
# =====================================================================
def page_01():
    s = SVG()
    header(
        s, "01", "A17 / RUNNING LOGIC · 01",
        "总体框架：一个前端、一个状态机、五个工位、三层底座",
        "实线是数据流，橙色虚线是人审，紫色虚线是缺数回补；所有产物落在 data/runs，下一位只读上一位的契约。",
        PLAT["main"],
        chips=[("答辩主线图", PLAT["main"])],
    )

    # custom legend
    lx = 1120
    for label, color, dash in [
        ("数据流", PLAT["main"], None),
        ("人审", HUMAN["main"], "5 3"),
        ("缺数回补", LOOP["main"], "5 3"),
    ]:
        s.line(lx, 61, lx + 24, 61, color, 1.8, dash)
        s.text(lx + 30, 65, label, 9.4, MUTED)
        lx += 30 + text_w(label, 9.4) + 26

    # human bar
    s.rect(64, 158, 1472, 62, HUMAN["soft"], HUMAN["line"], rx=14, sw=1)
    s.circle(96, 189, 14, HUMAN["main"])
    s.text(96, 194, "人", 12.5, WHITE, 700, anchor="middle")
    s.text(120, 185, "研究员（人）", 14.2, INK, 700)
    s.text(120, 202, "发起 → 逐段审核 → 定稿签发", 9.6, MUTED)
    steps = "发起任务   →   审 A1   →   审 A2   →   审 A3   →   审 A4   →   审 A5   →   签发"
    s.text(360, 194, steps, 12.6, HUMAN["dark"], 600)
    s.text(1530, 194, "动作：approve / revise / direct_edit / regenerate", 9.2, MUTED, anchor="right")

    # frontend + api
    s.rect(64, 236, 820, 78, CARD, LINE, rx=13, sw=1)
    s.text(84, 261, "展示层｜Vue 3 + TypeScript", 14.6, INK, 700)
    s.body(84, 281, 780,
           "创建任务 · 五阶段步进器 · 审核工作台（改数据 / 改图 / 改章节）· 报告预览与下载 · 技能大厅",
           fs=10.4, lh=14.2, color=INK2, max_lines=2)
    s.pill(864, 246, "Element Plus", A1["soft"], A1["dark"], fs=8.2, h=15, pad=6, anchor="right", stroke=A1["line"])
    s.pill(864, 268, "ECharts 6", A1["soft"], A1["dark"], fs=8.2, h=15, pad=6, anchor="right", stroke=A1["line"])

    s.rect(920, 236, 616, 78, CARD, LINE, rx=13, sw=1)
    s.text(940, 261, "接口层｜FastAPI /api/v1", 14.6, INK, 700)
    s.body(940, 281, 576,
           "POST /runs 建任务 · POST /reviews 提交审核 · GET /events/stream 实时动线 · GET /artifacts 下载产物",
           fs=10.4, lh=14.2, color=INK2, max_lines=2)

    arrow(s, 884, 275, 920, 275, PLAT["main"], sw=1.4)
    s.text(902, 230, "HTTP / SSE", 8.2, MUTED, anchor="middle")

    # orchestration
    boxes = [
        (64, 500, PLAT, "状态机｜StateMachine",
         "pending → running → waiting_review → completed；CAS 版本校验 + 单任务锁，人工改动不会被后台覆盖。"),
        (584, 400, PLAT, "适配器｜FiveAgentsAdapter",
         "把五个独立 Python 包统一成五个 run_* 方法；参数、产物、事件全部对齐。"),
        (1004, 532, PLAT, "运行时｜EventHub · CallLedger · Storage",
         "SSE 事件推送 / 模型与外呼记账 / data/runs 状态与产物快照。"),
    ]
    for x, w, theme, title, body in boxes:
        s.rect(x, 330, w, 84, theme["soft"], theme["line"], rx=12, sw=1)
        s.text(x + 18, 355, title, 13.2, INK, 700)
        s.body(x + 18, 374, w - 32, body, fs=9.9, lh=13.0, color=INK2, max_lines=2)

    # API -> state machine bus
    s.path("M1228,314 L1228,322 L314,322 L314,330", PLAT["main"], sw=1.5, marker=True)
    s.text(640, 317, "创建 / 审核请求", 8.6, MUTED)
    arrow(s, 564, 372, 584, 372, PLAT["main"], sw=1.4)
    s.text(574, 366, "调度", 8.2, MUTED, anchor="middle")
    # adapter -> agents
    arrow(s, 784, 414, 784, 444, PLAT["main"], sw=1.5)

    # gate strip
    s.rect(64, 420, 1472, 18, HUMAN["soft"], HUMAN["line"], rx=9, sw=0.9)
    s.text(80, 433, "每段结束 → 人工审核门：通过才进下一段；revise / regenerate 只重跑本段", 9.4, HUMAN["dark"], 600)
    s.text(800, 432, "分发给 A1–A5", 8.2, PLAT["dark"], 600)
    s.text(1092, 433, "5 个审核门", 8.6, MUTED, 600)
    for cx in (1180, 1250, 1320, 1390, 1460):
        s.diamond(cx, 429, 5.5, HUMAN["main"])
        s.text(cx, 432, "审", 6.2, WHITE, 700, anchor="middle")

    # agents
    agents = [
        (A1, "A1", "数据获取", "DATA FETCH",
         ["拆 7 大领域 + 验收指标", "问财并发取数、查询松弛", "重述对账、证据封装"], "→ dataset.json"),
        (A2, "A2", "数据解读", "INTERPRETER",
         ["CAGR / 杜邦 / 三表勾稽", "可比矩阵 / 异常 / 敏感性", "模型结论必须挂证据"], "→ interpretation_report.json"),
        (A3, "A3", "图表生成", "CHART",
         ["先盘证据，再选图型", "ECharts option + 离线 SVG", "缺数发 data_demands"], "→ chart_result.json"),
        (A4, "A4", "章节撰写", "WRITER",
         ["7 章 21 节并发", "生成-审计-修复逐段过", "只引用证据池与 ready 图"], "→ chapter_result.json"),
        (A5, "A5", "报告融合", "FUSION",
         ["合稿 + 执行摘要 + 附录", "结构/引用/数值/图表四维审计", "md / html / pdf + 交付门禁"], "→ report.md / html / pdf"),
    ]
    xs = [64, 363, 662, 961, 1260]
    for (theme, num, name, en, lines, tag), x in zip(agents, xs):
        agent_card(s, x, 444, 276, 170, theme, num, name, en, lines, tag)
    for x in (339, 638, 937, 1236):
        arrow(s, x - 5, 529, x + 18, 529, PLAT["main"], sw=1.5, dash="4 3")

    # A3 -> A1 feedback loop
    s.path("M800,614 L800,632 L202,632 L202,614", LOOP["main"], sw=1.6, dash="5 3", marker=True)
    s.text(232, 627, "A3 缺数 → data_demands → A1 补采 → A2 重算 → 回 A3",
           10.0, LOOP["dark"], 600)

    # base panel: shared + external
    s.rect(64, 660, 1472, 140, CARD, LINE, rx=14, sw=1)
    s.text(84, 678, "共享引擎（五个工位共用）", 9.6, PLAT["dark"], 700, spacing=1.2)
    shared = [
        "chain-research 产业链",
        "financial_semantics 口径",
        "skill_policy 技能路由",
        "context_budget 上下文",
        "chart_references 图号",
        "industry_reference 行业库",
    ]
    for i, label in enumerate(shared):
        x = 84 + i * 241
        s.rect(x, 688, 229, 28, PLAT["soft"], PLAT["line"], rx=7, sw=0.8)
        s.text(x + 12, 706, label, 9.6, PLAT["dark"], 600)
    s.text(84, 736, "外部能力与存储", 9.6, PLAT["dark"], 700, spacing=1.2)
    external = [
        "问财 SkillHub｜skills包 160+ 技能",
        "交易所公告 / 年报 PDF",
        "大模型 API（OpenAI 兼容）",
        "本地存储 data/runs",
    ]
    for i, label in enumerate(external):
        x = 84 + i * 362
        s.rect(x, 746, 350, 30, "#F7F3E9", LINE2, rx=7, sw=0.8)
        s.text(x + 12, 765, label, 9.6, INK2, 500)

    # delivery
    s.rect(64, 812, 1472, 38, A5["soft"], A5["line"], rx=10, sw=1)
    s.text(80, 836, "交付门禁：", 10.4, A5["dark"], 700)
    s.text(160, 836,
           "ready → 正式下载（HTTP 200）｜ready_with_limits / blocked → 受限草稿（HTTP 409）｜"
           "产物：report.md · report.html · report.pdf + consistency_report.json + manifest.json",
           9.9, INK2)

    footer(s, "01")
    s.save("01-总体框架.svg")


# =====================================================================
# 02-06 五个智能体：统一模板
# =====================================================================
def stage_page(num, eyebrow, title, subtitle, theme, chips, inputs, outputs, steps, collab, filename):
    s = SVG()
    header(s, num, eyebrow, title, subtitle, theme["main"], chips=chips)

    section_label(s, 64, 166, "输入 INPUT", theme["dark"])
    y = 188
    for title_, body, h, tag in inputs:
        info_card(s, 64, y, 300, h, theme, title_, body, tag=tag)
        y += h + 12

    section_label(s, 1180, 166, "输出 OUTPUT", theme["dark"])
    y = 188
    for title_, body, h, tag in outputs:
        info_card(s, 1180, y, 356, h, theme, title_, body, tag=tag)
        y += h + 12

    # process lane
    s.rect(400, 166, 740, 566, CARD, LINE, rx=16, sw=1.1, shadow=True)
    section_label(s, 420, 190, "关键处理 KEY STEPS", theme["dark"])
    step_h, gap = 68, 8
    step_y = 202
    for i, (step_title, step_body, tag) in enumerate(steps, 1):
        step_card(s, 416, step_y, 708, step_h, i, step_title, step_body, theme, tag)
        if i < len(steps):
            arrow(s, 770, step_y + step_h, 770, step_y + step_h + gap, theme["main"], sw=1.3)
        step_y += step_h + gap

    # input/output arrows
    arrow(s, 364, 300, 400, 300, theme["main"], sw=1.6)
    s.text(382, 292, "输入", 8.4, MUTED, anchor="middle")
    arrow(s, 1140, 300, 1180, 300, theme["main"], sw=1.6)
    s.text(1160, 292, "输出", 8.4, MUTED, anchor="middle")

    # collaboration band
    s.text(64, 748, "协作关系｜谁给我、我给谁、人怎么插手", 9.6, MUTED, 700, spacing=1.2)
    xs = [64, 428, 792, 1156]
    for (label, ctitle, cbody, color), x in zip(collab, xs):
        collab_card(s, x, 758, 350, 86, label, ctitle, cbody, color)

    footer(s, num)
    s.save(filename)


# ---------------- A1 ----------------
def page_02():
    stage_page(
        "02", "STAGE 1 / DATA FETCH",
        "A1 数据获取：先列验收清单，再按清单去问财取数",
        "它不负责“写得好”，只负责：数取得全、来源说得清、缺口留得明。",
        A1,
        chips=[("链路起点", A1["main"]), ("自动补采", HUMAN["main"])],
        inputs=[
            ("研究输入 ResearchInput",
             "行业主题 / 核心问题；市场范围 / 证券类型；\n基准日 as_of / 分析深度；指定公司或技能（可选）；\n锁死研究时点，不用未来数据。", 196, "契约"),
            ("行业画像（可选）",
             "chain_profile 产业链环节；候选公司池；\n行业口径与样本约束；没有画像时走通用行业库。", 170, "可选"),
            ("起点说明",
             "A1 是链路起点，没有上游产物；\n创建页可开关“关键数据自动补采”；补采预算写进运行快照。", 112, "说明"),
        ],
        outputs=[
            ("dataset.json",
             "七域 records + evidence_index；quality_summary / conflicts；每条记录都有 record_id、来源、报告期、哈希。", 170, "主产物"),
            ("产业链结果",
             "industry_chain_segments；industry_chain_topology；上游 / 中游 / 下游与核心公司。", 140, "结构"),
            ("过程审计",
             "raw/*.json 原始返回；events.jsonl 过程事件；result.json 覆盖结论。", 112, "审计"),
            ("缺口标记",
             "data_gap_notice / probe_hint；没取到的明确留白，不用示意值。", 84, "留白"),
        ],
        steps=[
            ("拆解研究意图",
             "把问题拆成 7 大领域：行业 / 公司 / 财务 / 宏观 / 产业链 / 研报 / 新闻；同时生成验收指标。", "LLM"),
            ("生成取数清单",
             "变成 SkillTask 清单：宏观、行业、三表财务、主营业务、公告、券商研报；标准 8 轮 / 24 次，深度 10 轮 / 32 次。", "LLM"),
            ("并发调度问财",
             "多接口并发；失败重试、密钥轮换；长句查不到就查询松弛，退回“核心实体 + 财务指标”。", "规则"),
            ("融合与重述对账",
             "统一单位 / 报告期；多来源冲突检测；交易所公告重述对账，旧值 → 调整后新值，保留页码与哈希。", "确定性"),
            ("逐项覆盖验收",
             "用 requirement_evidence_matrix 检查主体、期间、单位、来源、口径；缺的写进 data_gap_notice。", "规则"),
            ("缺口自动补采",
             "gap_scan 按章节分配预算：每章最多 3 个点、整轮最多 12 次请求、每点最多 4 轮改写；也可人工探针补采。", "回补"),
            ("封装证据 + 抽产业链",
             "每条记录生成 record_id / source / url / as_of / period / sha256；chain-research 抽上游-中游-下游拓扑。", "确定性"),
        ],
        collab=[
            ("上游", "没有上游", "A1 是链路起点；创建页可开关“关键数据自动补采”。", MUTED),
            ("下游", "交给 A2 / A3", "A2 只读 dataset.json；A3 可回传 data_demands。", A2["main"]),
            ("人", "人能改什么", "删噪、补年报、改关键词、复核补采口径。", HUMAN["main"]),
            ("闭环", "缺数闭环", "A3 缺数 → A1 补采 → 新增记录 → A2 重算。", LOOP["main"]),
        ],
        filename="02-A1-数据获取.svg",
    )


# ---------------- A2 ----------------
def page_03():
    stage_page(
        "03", "STAGE 2 / DATA INTERPRET",
        "A2 数据解读：先把数算死，再让模型解释",
        "确定性引擎负责“算得对”，大模型负责“讲得通”；两边都必须指向同一条证据。",
        A2,
        chips=[("确定性 + LLM", A2["main"]), ("可重算", LOOP["main"])],
        inputs=[
            ("dataset.json（来自 A1）",
             "七域记录 / evidence_index；quality_summary / conflicts；\n每条都能回溯 record_id；A2 只读，不改原始证据。", 176, "上游"),
            ("人工反馈",
             "可比公司口径；情景参数；指定重算或修订；\n反馈绑定当前 revision，旧结果作废。", 150, "人审"),
            ("问题契约（可选）",
             "用户五问 → 章节问题；决定解读重点；\n不改变证据池；只影响取舍与排序。", 140, "可选"),
        ],
        outputs=[
            ("interpretation_report.json",
             "key_metrics / trends / anomalies；cross_validations / financial_ratios；comps_matrix / analysis_facts。", 170, "主产物"),
            ("判断与解释",
             "insights / knowledge_facts；每条绑 evidence_record_ids；敏感性三情景矩阵。", 140, "结论"),
            ("产业链",
             "industry_chain_topology；合并 A1 拓扑并绑定证据。", 112, "结构"),
            ("质量",
             "data_quality / data_quality_appendix；缺口、异常、口径说明。", 84, "审计"),
        ],
        steps=[
            ("输入体检",
             "先看缺哪些域、哪些指标不能算；校验主题一致性、期间与单位是否可用。", "规则"),
            ("确定性计算",
             "CAGR（按会计年度、缺年过滤）；杜邦 ROE = 净利率 × 周转率 × 权益乘数；三表勾稽（容差小于 1%）。", "确定性"),
            ("横向对标",
             "可比公司矩阵 P/E、P/B、EV/EBITDA；历史分位判断高估 / 合理 / 低估；先审样本口径再比。", "确定性"),
            ("异常检测",
             "稳健 Z-score + IQR；找毛利率异动、应收账款恶化、债务风险；输出结构化预警。", "确定性"),
            ("情景推演",
             "基准 / 乐观 / 悲观三情景；关键变量敏感性矩阵（原料价格、政策退出等）。", "确定性"),
            ("技能解读",
             "按问题选分析技能（合并后上限 10 个）；输出 insights / knowledge_facts；每条绑 evidence_record_ids。", "LLM"),
            ("语义校验 + 产业链合并",
             "复核数字、单位、期间；合并 A1 的产业链拓扑并绑定证据；生成质量附录与缺口说明。", "规则"),
        ],
        collab=[
            ("上游", "只读 A1", "原始证据不改，只在报告里引用。", A1["main"]),
            ("下游", "给 A3 / A4", "A3 拿“可画的事实”；A4 拿“可写的结论”。", A2["main"]),
            ("人", "能改什么", "改可比公司、情景参数，触发本段重算。", HUMAN["main"]),
            ("回补", "补采之后", "A1 新增记录 → A2 自动重跑，旧结论作废。", LOOP["main"]),
        ],
        filename="03-A2-数据解读.svg",
    )


# ---------------- A3 ----------------
def page_04():
    stage_page(
        "04", "STAGE 3 / CHART GENERATION",
        "A3 图表生成：先问数据点有没有证据，再决定画什么图",
        "图不是画出来的，是数据点 + 证据 + 量纲三者对上了才放行。",
        A3,
        chips=[("证据先行", A3["main"]), ("缺数回补", LOOP["main"])],
        inputs=[
            ("interpretation_report.json",
             "指标 / 趋势 / 对标 / 异常；敏感性 / 产业链拓扑；\n优先采用 A2 已校验的事实。", 176, "上游"),
            ("dataset.json",
             "原始记录 + evidence_index；补点与复核用；缺数回补仍走 A1。", 150, "证据"),
            ("图表偏好",
             "张数（可空，默认规划）；图型 / 主题 light / dark / warm；产业链图强制保留；人工可换图型。", 140, "人审"),
        ],
        outputs=[
            ("chart_result.json",
             "charts[]：chart_id / type / option；render_mode / evidence_ids / status。", 170, "主产物"),
            ("图表文件",
             "charts/CHART-xx.svg；charts/CHART-xx.json；preview.html。", 140, "交付"),
            ("data_demands（可选）",
             "缺哪段期间 / 哪个对标；交给状态机触发补采。", 112, "回补"),
            ("质检",
             "轴 / 系列 / 标签 / 量纲；不合格图降级或剔除。", 84, "审计"),
        ],
        steps=[
            ("可画性盘点",
             "先看每个候选图的数据点够不够：期间齐不齐、单位同不同、有没有证据 ID；不够不进候选。", "规则"),
            ("图表规划",
             "按业务语义选图型：规模增速→双轴组合；竞争→雷达；集中度→环图；产业链→确定性 SVG；默认约 6 张，产业链强制保留。", "LLM"),
            ("数据配方",
             "指标 → series；对齐期间、实体、口径；缺点标记，不用 0 或示意值补。", "确定性"),
            ("量纲守卫",
             "万元 / 亿元不混轴；金额轴与比率轴物理隔离；1.5% 不能当 150%；轴标签统一。", "规则"),
            ("编译与渲染",
             "生成 ECharts option（网页交互）+ 离线 SVG（进 HTML/PDF）；产业链走 chain_render 专用模板。", "确定性"),
            ("图表质检",
             "检查轴、系列、标签、颜色、数值、期间、证据绑定；不合格图降级或剔除，不硬塞。", "规则"),
            ("缺口判定",
             "缺关键期间 / 对标 → 生成 data_demands；状态机触发 A1 补采、A2 重算，再回 A3 重画。", "回补"),
        ],
        collab=[
            ("上游", "A2 + A1", "事实来自 A2，补点回 A1。", A2["main"]),
            ("下游", "A4 / A5", "A4 只用 ready 图；A5 统一编号嵌入。", A4["main"]),
            ("人", "能改什么", "换图型、改标题 / 配色 / 顺序，实时预览。", HUMAN["main"]),
            ("闭环", "缺数回补", "A3 发 data_demands → A1 补 → A2 算 → 回 A3 重画。", LOOP["main"]),
        ],
        filename="04-A3-图表生成.svg",
    )


# ---------------- A4 ----------------
def page_05():
    stage_page(
        "05", "STAGE 4 / CHAPTER WRITING",
        "A4 章节撰写：7 章 21 节，按格子填，不自由发挥",
        "每节先定“这一节要回答什么”，再让模型写；数字必须能复算，引用必须能落地。",
        A4,
        chips=[("7 章并发", A4["main"]), ("21 节", PLAT["main"])],
        inputs=[
            ("interpretation_report.json",
             "唯一“数字池”与证据索引；A2 的事实、比率、对标。", 140, "上游"),
            ("chart_result.json",
             "只取 status=ready 的图；按 chart_id 引用。", 120, "图池"),
            ("标准大纲",
             "7 章 × 3 节 = 21 节；每节带 purpose；\n结构不可改；图表与证据按节挂载。", 120, "骨架"),
            ("人工反馈",
             "单章修改意见 / 全局口径；只重跑指定章节；\n反馈绑定当前 revision。", 100, "人审"),
        ],
        outputs=[
            ("chapter_result.json",
             "chapters[]：7 章 21 节；段落、evidence_ids、chart_ids。", 170, "主产物"),
            ("章节质检",
             "证据覆盖率；未支持断言；fallback_chapter_ids；passed。", 140, "审计"),
            ("问题索引",
             "question_answers；用户五问的对应答案。", 112, "问答"),
            ("告警",
             "缺口、净现比修正、跨章越界证据。", 84, "风险"),
        ],
        steps=[
            ("载入大纲",
             "7 章 × 3 节 = 21 节；每节带 purpose，模型不能改结构。", "规则"),
            ("局部检索",
             "每节只取相关事实、证据、图表；控制上下文预算，避免长文退化。", "规则"),
            ("并发写作",
             "最多 7 章并发；每节按“观点 / 证据 / 分析”三类段落组织；观点段不许夹带无证据数字。", "LLM"),
            ("生成-审计-修复",
             "数字能否在证据里复算？引用 ID 是否存在？不支持就改写或删除；每章有重试上限。", "循环"),
            ("图表与指标卡嵌入",
             "正文只放 chart_id 占位；指标卡 / 可比表按语义位置插入；不自行编图号。", "规则"),
            ("编辑润色",
             "统一术语、口径、开头；跨章冲突不在 A4 硬改，留给 A5 统一对账。", "LLM"),
            ("章节质检",
             "证据覆盖率、未支持断言、兜底章标记、字数 / 结构；不过则标 partial。", "规则"),
        ],
        collab=[
            ("上游", "A2 + A3", "数字只从 A2 来，图只用 ready 图。", A2["main"]),
            ("下游", "交给 A5", "7 章 21 节 + 质检 + 问题清单。", A5["main"]),
            ("人", "单章修改", "只重跑该章，不重写全书。", HUMAN["main"]),
            ("约束", "三条红线", "不自算新数、不引池外证据、不自编图号。", PLAT["main"]),
        ],
        filename="05-A4-章节撰写.svg",
    )


# ---------------- A5 ----------------
def page_06():
    stage_page(
        "06", "STAGE 5 / REPORT FUSION",
        "A5 报告融合：总编 + 质检 + 印刷，三道工序一次做完",
        "先合稿，再做四维对账，最后才决定“能不能正式签发”。",
        A5,
        chips=[("四维审计", A5["main"]), ("交付门禁", HUMAN["main"])],
        inputs=[
            ("chapter_result.json",
             "7 章正文与章节质检；问题清单 / 告警。", 140, "上游"),
            ("chart_result.json",
             "全部 ready 图与图号；证据绑定。", 120, "图池"),
            ("interpretation_report.json",
             "证据索引、财务比率、质量附录。", 120, "证据"),
            ("人工最终修改",
             "标题 / 摘要 / 正文 / 指标卡；改动必须复验；\n旧质检与旧导出立即作废。", 100, "人审"),
        ],
        outputs=[
            ("report.md / html / pdf",
             "Markdown 版本 diff；HTML 金融主题；PDF 出版级分页。", 170, "交付"),
            ("consistency_report.json",
             "四维审计结论；passed / issues / warnings。", 140, "质检"),
            ("fact_audit.json",
             "数值 / 引用审计；证据复算记录。", 112, "审计"),
            ("report_view.json / manifest.json",
             "视图与产物哈希；下载清单。", 84, "清单"),
        ],
        steps=[
            ("合稿装配",
             "封面、目录、执行摘要、7 章正文、4 类附录（统计 / 异常 / 敏感性 / 证据索引）。", "规则"),
            ("编辑融合",
             "统一术语与结论基调；chart 占位换正式图号；执行摘要只引用已审事实。", "LLM"),
            ("四维一致性审计",
             "结构（7 章 21 节齐不齐）、引用（record_id 是否存在）、数值（摘要 / 正文 / 图一致）、图表（规划图全嵌入）。", "规则"),
            ("定点修复",
             "最多 8 轮修段；能修的修，修不好保留缺口并标“受限”，不静默放过。", "循环"),
            ("三格式渲染",
             "Markdown（版本 diff）→ HTML（金融主题 / 交互图）→ PDF（Playwright 分页 + PyMuPDF 页码）。", "确定性"),
            ("交付门禁",
             "全通过 → ready，正式下载 200；硬缺口 → ready_with_limits / blocked，受限草稿 409。", "规则"),
            ("产物清单与失效",
             "manifest + SHA-256；人工改正文，旧质检 / 旧 PDF 立即作废，必须重新融合。", "规则"),
        ],
        collab=[
            ("上游", "三份缺一不可", "A2 证据 + A3 图 + A4 正文。", A2["main"]),
            ("下游", "交付中心 / 人", "正式 200，受限 409；签发权在人。", A5["main"]),
            ("人", "改完必须复验", "改正文 → 旧质检 / 旧 PDF 作废 → 重新融合。", HUMAN["main"]),
            ("回写", "审计不过怎么办", "退回对应章节 / 图表修正，不静默放过。", LOOP["main"]),
        ],
        filename="06-A5-报告融合.svg",
    )


if __name__ == "__main__":
    page_00()
    page_01()
    page_02()
    page_03()
    page_04()
    page_05()
    page_06()
