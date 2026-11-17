# -*- coding: utf-8 -*-
"""Insert A1-A4 + C1 candidate charts into the user's text-revised report.
Keeps the 15-figure numbering; only chart-specific notes/captions are updated.
"""
from pathlib import Path
from bs4 import BeautifulSoup

BASE = Path('/Users/Zhuanz1/Downloads/同花顺赛题-T3交接')
SRC = BASE / 'A17_新能源汽车行业研究报告_5问版_文字修订_20261117.html'
OUT = BASE / 'A17_新能源汽车行业研究报告_5问版_图表替换_20261117.html'
CAND = BASE / '图表改法候选'

FIG = {
    'fig3': ('C1_图3_渗透率台阶.svg', '图 3　国内新能源乘用车零售渗透率（2021-02—2025-12）',
             '59 个月度点；年度均值 15.39% / 27.55% / 35.07% / 46.85% / 53.53%；2021 年仅覆盖 2—12 月；阴影为 2024-08→2025-01 最大回撤区间，−12.4pct；虚线为 20%/40%/60% 参考线与年度均值阶梯线。；来源：同花顺问财月度零售渗透率；单位 %；最大回撤按百分点差计算。'),
    'fig6': ('A1_图6_现金流分布.svg', '图 6　两组经营现金流：公司点 + 组均值（2025）',
             '电池组均值 703.56 亿元、整车组均值 299.62 亿元；宁德 1,332.20、亿纬 74.92；比亚迪 591.36、长安 18.36、赛力斯 289.14；点=公司值，虚线=组均值；两面板纵轴独立，不跨面板比高度。；来源：同花顺问财财务数据；单位亿元；合并报表；2025 年度；组内算术平均。'),
    'fig7': ('A3_图7_收入与毛利结构.svg', '图 7　比亚迪 2025 年收入结构与毛利结构',
             '收入 8,039.65 亿元：汽车 80.68%、手机 19.31%、其他 0.01%；毛利 1,426.87 亿元（测算）：汽车 93.15%、手机 6.84%、其他 0.01%；0.01% 用引线标注，不以面积判断；毛利占比为测算值，不是年报披露的利润构成。；来源：比亚迪 2025 年报 PDF 第 29 页；仅取“分类标准=产品”行；金额单位亿元。'),
    'fig8': ('A4_图8_样本份额排序.svg', '图 8　五家样本公司收入份额（2025，排序条形）',
             '比亚迪 49.68%、宁德时代 26.18%、赛力斯 10.20%、长安汽车 10.13%、亿纬锂能 3.80%；CR3 86.07%、HHI 0.3375；样本合计 16,181.90 亿元；这是样本总收入口径，不是全市场销量份额；比亚迪收入含手机部件 19.31%，不是纯汽车收入。；来源：同花顺问财 2025 年营业收入；仅五家样本；分母为五家收入合计。'),
    'fig9': ('A2_图9_三指标小倍数.svg', '图 9　三家整车 2025 年盈利能力、股东回报与杠杆（三指标小倍数）',
             '毛利率 / 加权 ROE / 资产负债率；三面板各自刻度：毛利率 0—35%、ROE 0—30%、资产负债率 0—100%；不能跨面板比面积；杠杆越低越好。；来源：同花顺问财 2025 年报数据；合并口径；单位 %；三家均为研究样本。'),
}

TITLES = {
    'fig3': '图 3　零售渗透率与年度均值（2021-02—2025-12）',
    'fig6': '图 6　两组经营现金流：公司点 + 组均值（2025）',
    'fig7': '图 7　比亚迪 2025 年收入与毛利结构',
    'fig9': '图 9　三家整车 2025 年盈利能力、ROE 与杠杆（小倍数）',
}

def load_svg(name, aria):
    text = (CAND / name).read_text(encoding='utf-8')
    soup = BeautifulSoup(text, 'html.parser')
    svg = soup.find('svg')
    # drop the candidate-card tag line
    for tx in list(svg.find_all('text')):
        t = tx.get_text(strip=True)
        if t.startswith(('A1 ·', 'A2 ·', 'A3 ·', 'A4 ·', 'C1 ·')):
            tx.decompose()
    # report-style titles (avoid meta labels like "替换图 9" / "把雷达拆成")
    for tx in svg.find_all('text'):
        t = tx.get_text(strip=True)
        if t == '三张指标小倍数：把雷达拆成三个可单轴比较的面':
            tx.string = '三家整车 2025 年盈利能力、股东回报与杠杆'
        elif t.startswith('毛利率 / 加权 ROE / 资产负债率（2025，三家整车样本'):
            tx.string = '毛利率 / 加权 ROE / 资产负债率；三家整车样本，2025 年合并口径；三面板各自刻度'
        elif t == '收入结构与毛利结构：两条 100% 堆叠条':
            tx.string = '比亚迪 2025 年收入结构与毛利结构'
        elif t.startswith('比亚迪 2025 年；收入按分产品表'):
            tx.string = '两条 100% 堆叠条；收入按分产品表，毛利按分产品收入×分部毛利率测算'
        elif t == '五家样本收入份额：排序条形 + CR3 括号':
            tx.string = '五家样本收入份额与 CR3（2025）'
        elif t.startswith('2025 年样本总收入口径；不是全市场销量份额'):
            tx.string = '样本总收入口径；不是全市场销量份额，也不是汽车业务集中度'
    svg['role'] = 'img'
    svg['aria-label'] = aria
    return svg

def main():
    soup = BeautifulSoup(SRC.read_text(encoding='utf-8'), 'html.parser')
    for fid, (name, cap_title, cap_body) in FIG.items():
        fig = soup.find('figure', id=fid)
        assert fig is not None, fid
        wrap = fig.find('div', class_='chart-svg-wrap')
        assert wrap is not None, fid
        new_svg = load_svg(name, cap_title)
        wrap.clear()
        wrap.append(new_svg)
        cap = fig.find('figcaption')
        assert cap is not None, fid
        cap.clear()
        p = soup.new_tag('p')
        b = soup.new_tag('b'); b.string = cap_title
        p.append(b)
        p.append('；' + cap_body)
        cap.append(p)

    # chart-specific wording -> small multiples / stacked bar / annual-mean step
    repl = [
        ('五家公司不能用一张“越大越好”的表排名：电池与整车的商业模式不同，收入规模、毛利率、ROE 与杠杆的含义也不同。下面这张表把“规模、盈利、回报、杠杆、现金流”分开列，雷达图只用于三家整车样本。',
         '五家公司不能用一张“越大越好”的表排名：电池与整车的商业模式不同，收入规模、毛利率、ROE 与杠杆的含义也不同。下面这张表把“规模、盈利、回报、杠杆、现金流”分开列，小倍数图只用于三家整车样本。'),
        ('注：雷达三轴刻度不同，不能按面积大小直接排名；杠杆轴越高越差。',
         '注：三面板各自刻度，不能跨面板比面积；杠杆越低越好。'),
        ('雷达图读法', '小倍数图读法'),
        ('三轴刻度分别为毛利率 0—35%、ROE 0—30%、资产负债率 0—100%。杠杆轴“越高越差”，因此雷达面积大不等于综合更强。正确读法是逐轴比较，再结合表 13 的绝对数值。 指标含义：毛利率=毛利/营业收入；加权ROE=归母净利润/加权平均净资产；资产负债率=总负债/总资产。',
         '三面板刻度分别为毛利率 0—35%、ROE 0—30%、资产负债率 0—100%。杠杆面板“越低越好”，因此不能跨面板比面积。正确读法是同一指标内比较，再结合表 13 的绝对数值。 指标含义：毛利率=毛利/营业收入；加权ROE=归母净利润/加权平均净资产；资产负债率=总负债/总资产。'),
        ('Q3 的完整答案由 4.2 雷达、5.1 增长/盈利、5.2 现金流、5.3 估值共同构成。',
         'Q3 的完整答案由 4.2 盈利能力小倍数、5.1 增长/盈利、5.2 现金流、5.3 估值共同构成。'),
        ('按年报中同一张分产品收入表生成饼图，每个扇区标注收入金额和占比；核对类别互斥，且合计与该表披露总额一致。',
         '按年报中同一张分产品收入表生成 100% 堆叠结构图，每段标注收入金额和占比；核对类别互斥，且合计与该表披露总额一致。'),
        ('图中扇区按真实比例绘制；“其他”仅占 0.01%，扇区极小，标签已做防重叠处理，金额与占比同时以图例和表 11 复核。',
         '图中 0.01% 用引线标注，不以扇区面积判断；金额与占比同时以图例和表 11 复核。'),
        ('核心结论：汽车及相关产品占收入 80.68%、贡献利润 93.15%；手机部件占 19.31%、毛利率仅 6.29%。',
         '核心结论：汽车及相关产品占收入 80.68%、贡献测算毛利额 93.15%；手机部件占 19.31%、毛利率仅 6.29%。'),
        ('注：阴影为 2024-08→2025-01；虚线为 20%/40%/60% 参考线；回撤按百分点差计算。',
         '注：阴影为 2024-08→2025-01；虚线为 20%/40%/60% 参考线与年度均值阶梯线；回撤按百分点差计算。'),
    ]
    for old, new in repl:
        for el in soup.find_all(string=lambda s: s and old in s):
            el.replace_with(el.replace(old, new))

    # TOC titles for figures whose type changed
    for fid, title in TITLES.items():
        a = soup.select_one(f'.toc a[href="#{fid}"]')
        if a:
            span = a.find('span', class_='t')
            if span:
                span.string = title

    OUT.write_text(str(soup), encoding='utf-8')
    print('written', OUT)
    print('figures', len(soup.find_all('figure')), 'toc', len(soup.select('.toc li')))

if __name__ == '__main__':
    main()
