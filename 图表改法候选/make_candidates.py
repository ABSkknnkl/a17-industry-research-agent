# -*- coding: utf-8 -*-
"""Candidate chart redesigns for A17 report review. Standalone SVGs, report palette."""
from pathlib import Path
import math
from bs4 import BeautifulSoup

OUT = Path('/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/图表改法候选')
HTML = Path('/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/A17_新能源汽车行业研究报告_5问版_旧模板重构_20261117.html')

INK = '#12201D'; MUTED = '#53635F'; FAINT = '#8A9995'; GRID = '#E4EBE8'
DARK = '#0B4F4A'; TEAL = '#2F7D72'; GOLD = '#B8872F'; BLUE = '#1D6F8C'; MINT = '#7FA79F'
LIGHT = '#F3F7F5'; WHITE = '#FFFFFF'; RED = '#A33A2B'
COMPANY = {'比亚迪': DARK, '长安汽车': TEAL, '赛力斯': GOLD, '宁德时代': BLUE, '亿纬锂能': MINT}

def esc(s):
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

def t(x, y, s, size=12, color=MUTED, weight=400, anchor='start', op=1):
    a = f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}"'
    if weight != 400: a += f' font-weight="{weight}"'
    if anchor != 'start': a += f' text-anchor="{anchor}"'
    if op != 1: a += f' fill-opacity="{op}"'
    return a + f'>{esc(s)}</text>'

def r(x, y, w, h, rx=0, fill=WHITE, stroke=None, sw=1, op=1, dash=None):
    a = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'
    if op != 1: a += f' fill-opacity="{op}"'
    if stroke: a += f' stroke="{stroke}" stroke-width="{sw}"'
    if dash: a += f' stroke-dasharray="{dash}"'
    return a + '/>'

def ln(x1, y1, x2, y2, color=GRID, sw=1, dash=None, op=1):
    a = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"'
    if dash: a += f' stroke-dasharray="{dash}"'
    if op != 1: a += f' stroke-opacity="{op}"'
    return a + '/>'

def circ(x, y, r0=5, fill=DARK, stroke=None, sw=1):
    a = f'<circle cx="{x}" cy="{y}" r="{r0}" fill="{fill}"'
    if stroke: a += f' stroke="{stroke}" stroke-width="{sw}"'
    return a + '/>'

def bg(w, h):
    return r(0, 0, w, h, 0, WHITE)

def header(w, tag, title, subtitle):
    out = []
    out.append(t(40, 28, tag, 10, FAINT, 600))
    out.append(t(40, 56, title, 21, INK, 700))
    out.append(t(40, 78, subtitle, 11.5, MUTED))
    return ''.join(out)

def source(s, h):
    return t(40, h-18, s, 9.5, FAINT)

def y_axis(x, y0, y1, ticks, maxv, label, fmt='{:.0f}', label_dy=-8):
    out = []
    for v in ticks:
        yy = y1 - (v/maxv)*(y1-y0)
        out.append(ln(x, yy, x+6, yy, GRID, 0.8))
        out.append(t(x-8, yy+3, fmt.format(v), 9.5, FAINT, 400, 'end'))
    out.append(ln(x, y0, x, y1, GRID, 1))
    if label:
        out.append(t(x-8, y0+label_dy, label, 9.5, FAINT, 400, 'end'))
    return ''.join(out)

def svg_doc(w, h, parts):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'style="font-family:PingFang SC, Noto Sans CJK SC, sans-serif;">{bg(w,h)}{"".join(parts)}</svg>')

def write(name, svg):
    (OUT/name).write_text(svg, encoding='utf-8')
    print('written', name, len(svg))

# ---------------- A2: fig9 small multiples ----------------
def a2():
    W, H = 1200, 560
    p = [header(W, 'A2 · 替换图 9', '三张指标小倍数：把雷达拆成三个可单轴比较的面',
                '毛利率 / 加权 ROE / 资产负债率（2025，三家整车样本；三面板各自刻度）')]
    metrics = [
        ('毛利率', 35, [('比亚迪', 17.74), ('长安汽车', 15.54), ('赛力斯', 29.14)], '%'),
        ('加权 ROE', 30, [('比亚迪', 15.31), ('长安汽车', 5.30), ('赛力斯', 23.53)], '%'),
        ('资产负债率', 100, [('比亚迪', 70.74), ('长安汽车', 59.61), ('赛力斯', 70.91)], '%'),
    ]
    for i, (title, maxv, vals, unit) in enumerate(metrics):
        x = 40 + i*386
        w = 350
        p.append(r(x, 112, w, 360, 8, '#FFFFFF', '#D8E2DE', 0.9))
        p.append(t(x+14, 138, title, 14, INK, 700))
        p.append(t(x+w-14, 138, unit, 10, FAINT, 400, 'end'))
        # rows
        for j, (name, v) in enumerate(vals):
            yy = 170 + j*63
            p.append(t(x+14, yy+13, name, 11.5, MUTED, 600))
            p.append(r(x+86, yy, w-150, 18, 3, '#E8EFEC'))
            p.append(r(x+86, yy, max(2, (w-150)*v/maxv), 18, 3, COMPANY[name]))
            p.append(t(x+86+(w-150)*v/maxv+7, yy+13, f'{v:.2f}%', 10.5, INK, 700))
        # axis
        p.append(ln(x+86, 350, x+w-20, 350, GRID, 1))
        for j, v in enumerate([0, maxv/2, maxv]):
            xx = x+86 + (w-150)*v/maxv
            p.append(ln(xx, 350, xx, 356, GRID, 0.8))
            p.append(t(xx, 370, f'{v:g}', 9, FAINT, 400, 'middle'))
        p.append(t(x+14, 404, '越低越好' if title=='资产负债率' else '同一指标内比较', 10, FAINT))
    p.append(source('数据：同花顺问财 2025 年报；合并口径；三家均为研究样本。三面板刻度不同，不能跨面板比面积。', H))
    write('A2_图9_三指标小倍数.svg', svg_doc(W, H, p))

# ---------------- A3: fig7 stacked ----------------
def a3():
    W, H = 1200, 520
    p = [header(W, 'A3 · 替换图 7', '收入结构与毛利结构：两条 100% 堆叠条',
                '比亚迪 2025 年；收入按分产品表，毛利按分产品收入×分部毛利率测算')]
    # legend
    lx = 760
    for i, (lab, col) in enumerate([('汽车及相关产品', DARK), ('手机部件及组装等', TEAL), ('其他', GOLD)]):
        p.append(r(lx+i*140, 100, 10, 10, 2, col))
        p.append(t(lx+i*140+16, 109, lab, 9.5, MUTED))
    x0, bw = 180, 860
    rows = [
        ('收入结构', 8039.65, [('汽车及相关产品', 80.68, DARK), ('手机部件及组装等', 19.31, TEAL), ('其他', 0.01, GOLD)]),
        ('毛利结构（测算）', 1426.87, [('汽车及相关产品', 93.15, DARK), ('手机部件及组装等', 6.84, TEAL), ('其他', 0.01, GOLD)]),
    ]
    for k, (lab, total, segs) in enumerate(rows):
        y = 160 + k*150
        p.append(t(40, y-12, lab, 12, INK, 700))
        p.append(t(40, y+8, f'合计 {total:,.2f} 亿元', 10.5, MUTED))
        x = x0
        for name, share, col in segs:
            w = max(1.2, bw*share/100)
            p.append(r(x, y, w, 52, 2, col))
            if share > 12:
                p.append(t(x+8, y+31, f'{share:.2f}%', 12, WHITE if col != GOLD else INK, 700))
            x += w
        if k == 1:
            p.append(t(x0+bw*0.9315+4, y-8, '手机 6.84%', 9.2, TEAL, 700))
        # callout for other
        p.append(ln(x0+bw, y+24, 1070, y+24, GOLD, 1, '3,2'))
        p.append(t(1074, y+18, '其他 0.01%', 9.5, GOLD, 700))
        p.append(t(1074, y+33, '0.83 亿元' if k == 0 else '0.15 亿元', 9, FAINT))
    p.append(t(40, 470, '注：0.01% 用引线标注，不以扇区面积判断；毛利占比为测算值，不是年报披露的利润构成。', 9.5, FAINT))
    p.append(source('数据：比亚迪 2025 年报第 29 页；仅“分类标准=产品”行；金额单位亿元；毛利=收入×分部毛利率。', H))
    write('A3_图7_收入与毛利结构.svg', svg_doc(W, H, p))

# ---------------- A4: fig8 sorted bars ----------------
def a4():
    W, H = 1200, 560
    p = [header(W, 'A4 · 替换图 8', '五家样本收入份额：排序条形 + CR3 括号',
                '2025 年样本总收入口径；不是全市场销量份额，也不是汽车业务集中度')]
    data = [('比亚迪', 49.68), ('宁德时代', 26.18), ('赛力斯', 10.20), ('长安汽车', 10.13), ('亿纬锂能', 3.80)]
    x0, maxw, maxv = 230, 700, 50
    top = 132
    for i, (name, v) in enumerate(data):
        y = top + i*66
        p.append(t(40, y+25, name, 11.5, INK, 700))
        p.append(r(x0, y, maxw, 30, 4, '#E8EFEC'))
        p.append(r(x0, y, maxw*v/maxv, 30, 4, COMPANY[name]))
        p.append(t(x0+maxw*v/maxv+8, y+21, f'{v:.2f}%', 10.5, INK, 700))
    # CR3 bracket over first 3 rows
    y1, y2 = top-8, top+3*66-14
    p.append(ln(208, y1, 208, y2, GOLD, 2))
    p.append(ln(202, y1, 214, y1, GOLD, 2))
    p.append(ln(202, y2, 214, y2, GOLD, 2))
    p.append(t(196, y1-8, 'CR3 86.07%', 10.5, GOLD, 700, 'end'))
    p.append(t(40, 500, '样本合计 16,181.90 亿元；HHI 0.3375。比亚迪收入含手机部件及组装等 19.31%，不是纯汽车收入。', 9.5, FAINT))
    p.append(source('数据：同花顺问财 2025 年营业收入；仅五家样本；分母为五家收入合计。', H))
    write('A4_图8_样本份额排序.svg', svg_doc(W, H, p))

# ---------------- A1: fig6 point plot ----------------
def a1():
    W, H = 1200, 620
    p = [header(W, 'A1 · 替换图 6', '两组经营现金流：公司点 + 组均值',
                '2025 年；两面板纵轴独立，不能跨面板比点高；组均值见上方卡片')]
    cards = [
        (40, '电池组均值', '703.56 亿元', '宁德 + 亿纬，算术平均', BLUE),
        (640, '整车组均值', '299.62 亿元', '比亚迪 + 长安 + 赛力斯，算术平均', DARK),
    ]
    for x, lab, val, sub, col in cards:
        p.append(r(x, 100, 520, 82, 8, '#F7FAF9', '#D8E2DE', 0.9))
        p.append(t(x+16, 122, lab, 11, MUTED, 600))
        p.append(t(x+16, 153, val, 20, col, 800))
        p.append(t(x+16, 170, sub, 9.5, FAINT))
    p.append(t(580, 148, '2.35×', 18, GOLD, 800, 'middle'))
    # panels
    panels = [
        (40, 235, 520, 300, '电池组：两家公司', 1500, [0,500,1000,1500], 703.56,
         [('宁德时代', 1332.20, 190), ('亿纬锂能', 74.92, 390)], '宁德占电池组 OCF 94.67%'),
        (640, 235, 520, 300, '整车组：三家公司', 650, [0,200,400,600], 299.62,
         [('比亚迪', 591.36, 150), ('长安汽车', 18.36, 310), ('赛力斯', 289.14, 450)], '比亚迪占整车组 OCF 65.79%'),
    ]
    for x, y, w, h, title, maxv, ticks, mean, pts, note in panels:
        p.append(r(x, y, w, h, 8, '#FFFFFF', '#D8E2DE', 0.9))
        p.append(t(x+16, y+24, title, 12, INK, 700))
        # plot area
        plot_x, plot_y, plot_b = x+72, y+45, y+h-45
        p.append(y_axis(plot_x, plot_y, plot_b, ticks, maxv, '亿元'))
        # mean line
        my = plot_b - (mean/maxv)*(plot_b-plot_y)
        p.append(ln(plot_x, my, x+w-20, my, GOLD, 1.3, '5,3'))
        p.append(t(x+80, my-7, f'均值 {mean:.2f}', 9.5, GOLD, 700))
        for name, v, dx in pts:
            xx = x + dx
            yy = plot_b - (v/maxv)*(plot_b-plot_y)
            p.append(circ(xx, yy, 6, COMPANY[name]))
            label_y = yy - 12 if yy > y+70 else yy + 20
            p.append(t(xx, label_y, f'{v:,.2f}', 9.5, INK, 700, 'middle'))
            p.append(t(xx, plot_b+18, name, 9, MUTED, 400, 'middle'))
        p.append(t(x+16, y+h-12, note, 9.5, FAINT))
    p.append(source('数据：同花顺问财 2025 年度合并报表；单位亿元；组内算术平均；点=公司值，虚线=组均值。', H))
    write('A1_图6_现金流分布.svg', svg_doc(W, H, p))

if __name__ == '__main__':
    a1(); a2(); a3(); a4()
    print('done')

# ---------------- B1: fig1/2 three-panel ----------------
def b1():
    W, H = 1200, 760
    p = [header(W, 'B1 · 替换图 1 + 图 2', '销量、出口与出口占比：拆成三个面板',
                '2021—2025；同比用标签表示，不再做双轴；2021 年缺少上年基数，同比留空')]
    years = ['2021', '2022', '2023', '2024', '2025']
    sales = [352.1, 688.7, 949.5, 1286.6, 1649.0]
    syoy = [None, 95.60, 37.87, 35.50, 28.17]
    exp = [34.88, 67.50, 115.26, 127.44, 258.43]
    eyoy = [None, 93.52, 70.76, 10.57, 102.79]
    share = [9.91, 9.80, 12.14, 9.90, 15.67]
    # two panels
    panels = [
        (40, 105, 540, 320, '销量（万辆）', sales, syoy, 1800, [0, 600, 1200, 1800]),
        (620, 105, 540, 320, '出口量（万辆）', exp, eyoy, 300, [0, 100, 200, 300]),
    ]
    for x, y, w, h, title, vals, yoys, maxv, ticks in panels:
        p.append(r(x, y, w, h, 8, '#FFFFFF', '#D8E2DE', 0.9))
        p.append(t(x+16, y+24, title, 13, INK, 700))
        px, py, pb = x+64, y+48, y+h-52
        p.append(y_axis(px, py, pb, ticks, maxv, '万辆'))
        bw, step = 42, 90
        for i, v in enumerate(vals):
            xx = px + 38 + i*step
            bh = (v/maxv)*(pb-py)
            p.append(r(xx, pb-bh, bw, bh, 3, DARK))
            p.append(t(xx+bw/2, pb-bh-8, f'{v:,.1f}', 10, INK, 700, 'middle'))
            p.append(t(xx+bw/2, pb+18, years[i], 9.5, MUTED, 400, 'middle'))
            yoy = yoys[i]
            p.append(t(xx+bw/2, pb+36, '—' if yoy is None else f'{yoy:+.2f}%', 9, GOLD if yoy is not None else FAINT, 600, 'middle'))
    # bottom share panel
    p.append(r(40, 470, 1120, 220, 8, '#FFFFFF', '#D8E2DE', 0.9))
    p.append(t(56, 494, '出口占销量比重（%）', 13, INK, 700))
    px, py, pb = 100, 515, 650
    p.append(y_axis(px, py, pb, [0, 10, 20], 20, '%'))
    step = (1040-40)/4
    pts = []
    for i, v in enumerate(share):
        xx = px + 40 + i*step
        yy = pb - (v/20)*(pb-py)
        pts.append((xx, yy))
    pts_str = ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)
    area = f'{pts[0][0]:.1f},{pb} ' + pts_str + f' {pts[-1][0]:.1f},{pb}'
    p.append(f'<polygon points="{area}" fill="{TEAL}" fill-opacity="0.10"/>')
    p.append(f'<polyline points="{pts_str}" fill="none" stroke="{TEAL}" stroke-width="2.2"/>')
    for i, (xx, yy) in enumerate(pts):
        p.append(circ(xx, yy, 4, TEAL))
        p.append(t(xx, yy-10, f'{share[i]:.2f}%', 9.5, INK, 700, 'middle'))
        p.append(t(xx, pb+18, years[i], 9.5, MUTED, 400, 'middle'))
    p.append(t(56, 705, '出口占销量由 2021 年 9.91% 升至 2025 年 15.67%；中间 2024 年回落至 9.90%，不是单边抬升。', 9.5, FAINT))
    p.append(source('数据：同花顺问财行业数据；年度累计值；出口占比=出口量/销量；单位 %。', H))
    write('B1_图1-2_销量出口占比.svg', svg_doc(W, H, p))

# ---------------- B2: fig11/13 absolute values ----------------
def b2():
    W, H = 1200, 760
    p = [header(W, 'B2 · 替换图 11 + 图 13', '绝对值柱：营收与经营现金流（2023—2025）',
                '同一张图看规模与变化；不用指数，避免把 8,039 亿和 18 亿画成同一高度')]
    rev = {
        '比亚迪': [6023.15, 7771.02, 8039.65],
        '长安汽车': [1512.98, 1597.33, 1640.00],
        '赛力斯': [358.42, 1451.76, 1650.54],
    }
    ocf = {
        '比亚迪': [1697.25, 1334.54, 591.36],
        '长安汽车': [198.61, 48.49, 18.36],
        '赛力斯': [63.98, 225.15, 289.14],
    }
    years = ['2023', '2024', '2025']
    # revenue panel
    p.append(r(40, 105, 1120, 300, 8, '#FFFFFF', '#D8E2DE', 0.9))
    p.append(t(56, 129, '营业收入（亿元）', 13, INK, 700))
    px, py, pb = 110, 150, 365
    maxv = 8500
    p.append(y_axis(px, py, pb, [0, 3000, 6000, 8500], maxv, '', label_dy=-16))
    centers = {'比亚迪': 210, '长安汽车': 560, '赛力斯': 910}
    for c, cx in centers.items():
        p.append(t(cx+60, py-8, c, 10.5, MUTED, 600, 'middle'))
        for j, v in enumerate(rev[c]):
            xx = cx + j*58
            bh = (v/maxv)*(pb-py)
            p.append(r(xx, pb-bh, 40, bh, 3, COMPANY[c], op=[0.45, 0.72, 1][j]))
            p.append(t(xx+20, pb-bh-7, f'{v:,.0f}', 9.2, INK, 700, 'middle'))
            p.append(t(xx+20, pb+18, years[j], 8.5, FAINT, 400, 'middle'))
    p.append(t(56, 418, '比亚迪 2025 年营收 8,039.65 亿元，约为长安/赛力斯的 4.9 倍；指数图会抹掉这个规模差。', 9.5, FAINT))
    # OCF panel
    p.append(r(40, 430, 1120, 260, 8, '#FFFFFF', '#D8E2DE', 0.9))
    p.append(t(56, 454, '经营现金流（亿元）', 13, INK, 700))
    px, py, pb = 110, 474, 650
    maxv = 1800
    p.append(y_axis(px, py, pb, [0, 600, 1200, 1800], maxv, '', label_dy=-16))
    for c, cx in centers.items():
        p.append(t(cx+60, py-8, c, 10.5, MUTED, 600, 'middle'))
        for j, v in enumerate(ocf[c]):
            xx = cx + j*58
            bh = (v/maxv)*(pb-py)
            p.append(r(xx, pb-bh, 40, bh, 3, COMPANY[c], op=[0.45, 0.72, 1][j]))
            p.append(t(xx+20, pb-bh-7, f'{v:,.0f}', 9.2, INK, 700, 'middle'))
            p.append(t(xx+20, pb+18, years[j], 8.5, FAINT, 400, 'middle'))
    p.append(t(56, 704, '浅→深：2023→2025；绝对金额见表 16。经营现金流不用指数，才能看出比亚迪从 1,697 亿降至 591 亿。', 9.5, FAINT))
    p.append(source('数据：同花顺问财年度合并报表；单位亿元；三家均为研究样本。', H))
    write('B2_图11-13_绝对值.svg', svg_doc(W, H, p))

# ---------------- B3: fig14/15 PB history + current ----------------
def _pb_series():
    soup = BeautifulSoup(HTML.read_text(), 'html.parser')
    fig = soup.find('figure', id='fig15')
    polys = []
    for poly in fig.find('svg').find_all('polyline'):
        pts = poly.get('points', '')
        if len(pts) > 100:
            arr = [tuple(map(float, q.split(','))) for q in pts.split()]
            if len(arr) == 60:
                vals = [(325-y)/233*20 for x, y in arr]
                polys.append(vals)
    return polys

def b3():
    W, H = 1200, 620
    p = [header(W, 'B3 · 合并图 14 + 图 15', 'PB 历史曲线 + 当前点 + 自身分位',
                '2021—2025 每月最后一个交易日；三面板纵轴独立；当前点=2025-12-31')]
    series = _pb_series()
    names = ['比亚迪', '长安汽车', '赛力斯']
    maxs = [13, 3.2, 20]
    pcts = ['1.67%', '3.33%', '30.00%']
    currents = [3.6288, 1.5243, 7.5788]
    for i, (name, vals, maxv, pct, cur) in enumerate(zip(names, series, maxs, pcts, currents)):
        x, w, y, h = 40 + i*386, 350, 120, 380
        p.append(r(x, y, w, h, 8, '#FFFFFF', '#D8E2DE', 0.9))
        p.append(t(x+14, y+24, name, 13.5, INK, 700))
        p.append(t(x+w-14, y+24, f'当前 {cur:.2f} · {pct}分位', 9.2, COMPANY[name], 700, 'end'))
        px, py, pb = x+52, y+50, y+h-60
        p.append(y_axis(px, py, pb, [0, maxv/2, maxv], maxv, '倍', fmt='{:.1f}'))
        pts = []
        for j, v in enumerate(vals):
            xx = px + j*(w-70)/59
            yy = pb - (v/maxv)*(pb-py)
            pts.append((xx, yy))
        p.append(f'<polyline points="{" ".join(f"{xx:.1f},{yy:.1f}" for xx,yy in pts)}" fill="none" stroke="{COMPANY[name]}" stroke-width="2"/>')
        p.append(circ(pts[-1][0], pts[-1][1], 6, COMPANY[name]))
        for lab, idx in [('2021-01', 0), ('2023-01', 24), ('2025-12', 59)]:
            xx = px + idx*(w-70)/59
            p.append(t(xx, pb+20, lab, 8.5, FAINT, 400, 'middle'))
    p.append(source('数据：同花顺问财日度 PB，取 2021—2025 每月最后一个交易日，n=60；当前值计入；分位=历史月末 PB≤当前值/60。', H))
    write('B3_图14-15_PB历史分位.svg', svg_doc(W, H, p))

# ---------------- C1: fig3 step line ----------------
def _pen_series():
    soup = BeautifulSoup(HTML.read_text(), 'html.parser')
    fig = soup.find('figure', id='fig3')
    for poly in fig.find('svg').find_all('polyline'):
        pts = poly.get('points', '')
        if len(pts) > 100:
            arr = [tuple(map(float, q.split(','))) for q in pts.split()]
            if len(arr) == 59:
                return [(405-y)/313*65 for x, y in arr]
    return []

def c1():
    W, H = 1200, 560
    p = [header(W, 'C1 · 可选升级图 3', '渗透率：月度曲线 + 年度均值台阶',
                '2021-02—2025-12；年度均值让“五个台阶”肉眼可见；2021 仅 11 个月')]
    vals = _pen_series()
    x0, y0, w, h = 100, 115, 1060, 350
    pb = y0+h
    p.append(y_axis(x0, y0, pb, [0,13,26,39,52,65], 65, '%'))
    # reference lines
    for v, lab in [(20,'20%'),(40,'40%'),(60,'60%')]:
        yy = pb - v/65*h
        p.append(ln(x0, yy, x0+w, yy, GRID, 0.9, '5,4'))
        p.append(t(x0+4, yy-5, lab, 8.5, FAINT))
    # drawdown shade 2024-08 -> 2025-01 indices 42..47
    xs = [x0 + i*w/(len(vals)-1) for i in range(len(vals))]
    p.append(r(xs[42], y0, xs[47]-xs[42], h, 0, GOLD, None, 1, 0.08))
    # annual mean steps
    means = [(0,10,15.39),(11,22,27.55),(23,34,35.07),(35,46,46.85),(47,58,53.53)]
    for a,b,v in means:
        yy = pb - v/65*h
        p.append(ln(xs[a], yy, xs[b], yy, GOLD, 2, '6,3'))
        p.append(t((xs[a]+xs[b])/2, yy-6, f'{v:.2f}', 9, GOLD, 700, 'middle'))
    # monthly line
    pts = [(xs[i], pb - vals[i]/65*h) for i in range(len(vals))]
    p.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y in pts)}" fill="none" stroke="{DARK}" stroke-width="2.4"/>')
    # labels
    for i, lab in [(0,'8.1%'),(10,'22.6%'),(23,'25.7%'),(35,'32.8%'),(47,'41.5%'),(58,'59.1%')]:
        yy = pb - vals[i]/65*h
        p.append(circ(xs[i], yy, 4, DARK))
        p.append(t(xs[i], yy-10, lab, 9, INK, 700, 'middle'))
    # max drawdown annotation
    p.append(t(xs[45], y0+26, '最大回撤 2024-08→2025-01：−12.4pct', 9.5, RED, 700, 'middle'))
    # x labels
    for lab, idx in [('2021-02',0),('2022-01',11),('2023-01',23),('2024-01',35),('2025-01',47),('2025-12',58)]:
        p.append(t(xs[idx], pb+22, lab, 8.5, FAINT, 400, 'middle'))
    p.append(t(40, 505, '虚线=年度均值；阴影=最大回撤区间；20/40/60% 为参考线。2021 年均值仅覆盖 2—12 月，不能与 12 个月年份直接比。', 9.5, FAINT))
    p.append(source('数据：同花顺问财月度零售渗透率；59 个完整月度点；单位 %。', H))
    write('C1_图3_渗透率台阶.svg', svg_doc(W, H, p))

# ---------------- C2: fig4 simplified projection ----------------
def c2():
    W, H = 1200, 520
    p = [header(W, 'C2 · 仅答辩投影版（不替换报告主图）', '产业链简化版：三层 + 五家样本位置',
                '只保留“上游—中游—下游”与 5 家样本；箭头仅表示业务流向，不代表供货关系')]
    cols = [
        (40, '上游：资源与材料', BLUE, '#EFF6FF', ['矿产资源','正负极材料','隔膜 / 电解液','设备 / 零部件']),
        (430, '中游：电池与整车', '#0E7490', '#ECFEFF', None),
        (820, '下游：使用、服务与回收', PURPLE if False else '#6D4AA6', '#F5F3FF', ['私人消费','运营车队','充换电 / 售后','回收 / 梯次']),
    ]
    for x, title, col, fill, chips in cols:
        p.append(r(x, 105, 340, 300, 9, fill, col, 1.2, 0.45))
        p.append(r(x, 105, 340, 30, 14, fill, col, 1.2))
        p.append(t(x+170, 125, title, 13, col, 700, 'middle'))
        if chips:
            for i, chip in enumerate(chips):
                xx = x+14 + (i%2)*155
                yy = 155 + (i//2)*100
                p.append(r(xx, yy, 145, 72, 6, WHITE, '#CBD5E1', 0.9))
                p.append(t(xx+72, yy+30, chip, 11.5, INK, 700, 'middle'))
                p.append(t(xx+72, yy+50, '结构位', 9, FAINT, 400, 'middle'))
        else:
            p.append(r(x+14, 150, 312, 95, 7, WHITE, '#0E7490', 1.1))
            p.append(t(x+26, 173, '动力电池', 12, INK, 700))
            p.append(t(x+26, 201, '宁德时代', 10.5, BLUE, 600))
            p.append(t(x+26, 219, '亿纬锂能', 10.5, MINT, 600))
            p.append(t(x+26, 237, '样本 2 家', 8.8, FAINT))
            p.append(r(x+14, 260, 312, 125, 7, WHITE, '#0E7490', 1.1))
            p.append(t(x+26, 283, '整车制造', 12, INK, 700))
            for i, name in enumerate(['比亚迪','长安汽车','赛力斯']):
                p.append(r(x+26, 298+i*26, 288, 21, 4, '#F7FAF9', '#D8E2DE', 0.7))
                p.append(t(x+40, 313+i*26, name, 10.2, INK, 600))
            p.append(t(x+26, 383, '样本 3 家', 8.8, FAINT))
    # arrows
    for x1, x2 in [(380,430),(770,820)]:
        p.append(ln(x1, 255, x2-8, 255, '#64748B', 2.5, '6,4'))
        p.append(f'<polygon points="{x2-8},250 {x2},255 {x2-8},260" fill="#64748B"/>')
    p.append(t(405, 240, '业务流向', 8.8, FAINT, 400, 'middle'))
    p.append(t(745, 240, '业务流向', 8.8, FAINT, 400, 'middle'))
    p.append(t(40, 438, '图例：虚线箭头=业务流向，不是供货关系；上游只画环节、下游只画场景；五家样本只在中游点名。', 9.5, FAINT))
    p.append(source('结构依据：项目 A3 已审产业链分层；样本：比亚迪、长安、赛力斯、宁德时代、亿纬锂能。', H))
    write('C2_图4_答辩简化.svg', svg_doc(W, H, p))

def c3():
    W, H = 1200, 540
    p = [header(W, 'C3 · 可选升级图 5', '毛利率点图：紧凑双面板 + 组内差',
                '样本只有 5 家，不要把点摊满全宽；两组各一块面板，均值线只作参照')]
    panels = [
        (40, '电池组（2 家）', BLUE, [('宁德时代', 26.27, 170), ('亿纬锂能', 16.17, 370)],
         21.22, '组内差 10.10pct（26.27 vs 16.17）'),
        (620, '整车组（3 家）', DARK, [('比亚迪', 17.74, 150), ('长安汽车', 15.54, 280), ('赛力斯', 29.14, 410)],
         20.81, '组内差 13.60pct（29.14 vs 15.54）'),
    ]
    for x, title, col, pts, mean, diff in panels:
        w, y, h = 540, 115, 345
        p.append(r(x, y, w, h, 8, '#FFFFFF', '#D8E2DE', 0.9))
        p.append(t(x+16, y+26, title, 13, col, 700))
        px, py, pb = x+62, y+55, y+h-75
        p.append(y_axis(px, py, pb, [0, 10, 20, 30, 35], 35, '%'))
        # range band: fill the whitespace with information
        vmin = min(v for _, v, _ in pts); vmax = max(v for _, v, _ in pts)
        ytop = pb - vmax/35*(pb-py); ybot = pb - vmin/35*(pb-py)
        p.append(r(px, ytop, x+w-20-px, ybot-ytop, 0, col, None, 1, 0.06))
        p.append(t(x+w-18, y+26, f'区间 {vmin:.2f}–{vmax:.2f}', 8.8, FAINT, 400, 'end'))
        # mean line
        my = pb - mean/35*(pb-py)
        p.append(ln(px, my, x+w-20, my, GOLD, 1.4, '5,3'))
        p.append(t(px+4, my-6, f'均值 {mean:.2f}%', 9.2, GOLD, 700))
        # points
        for name, v, dx in pts:
            xx = x + dx
            yy = pb - v/35*(pb-py)
            p.append(circ(xx, yy, 7, COMPANY[name]))
            p.append(t(xx, yy-13, f'{v:.2f}%', 9.8, INK, 700, 'middle'))
            p.append(t(xx, pb+18, name, 9.2, MUTED, 500, 'middle'))
        p.append(t(x+16, y+h-18, diff, 9.2, FAINT))
    p.append(t(40, 505, '两组均值 21.22% / 20.81% 几乎一样，所以这张图只看组内分布，不看组间均值高低。', 9.3, FAINT))
    p.append(source('数据：同花顺问财 2025 年报；毛利率为合并口径；电池组=宁德时代、亿纬锂能；整车组=比亚迪、长安汽车、赛力斯。', H))
    write('C3_图5_毛利率点图.svg', svg_doc(W, H, p))

if __name__ == '__main__':
    b1(); b2(); b3(); c1(); c2(); c3()
    print('B/C done')
