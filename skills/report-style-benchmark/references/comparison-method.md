# 对照方法论（怎么测、怎么校准、怎么扩基线）

> 本文件是 `report-style-benchmark` 的方法参考：解释每项指标怎么测、阈值怎么来、
> 校准过程踩过哪些坑。写这份文档的目的是让后来者能**复现整个对照链路**，
> 而不是只拿到一份结论表。

## 1. 对照的整体框架

```
真实研报样本（R1–R6，纵向 A4，142 页）
        │ collect_metrics.py
        ▼
samples_extended.json（basic + extended 全量指标）
        │ build_baseline.py（--carry-manual 继承人工复核条目）
        ▼
samples_baseline.json（固化基线：17 项阈值 × 6 样本实测 + min/max/median）
        │  ↑ 全仓库唯一一份；report-page-composer 经 shim 复用同一份
        │
        │ style_benchmark_audit.py --baseline（对任意交付 PDF）
        ▼
体裁审计 + baseline diff（7 维度 verdict）

基线的提取逻辑定义在 baseline_schema.py（THRESHOLD_EXTRACTORS），
由 build_baseline.py 与 style_benchmark_audit.py 共同导入 —— 只有一份，
所以「生成口径」与「校验口径」在结构上不可能漂移。
```

两层审计的分工：
- **体裁审计**（13 项 issue）：判定"这份 PDF 是否像研报"，退出码当门禁。
- **baseline diff**（7 维度）：量化"它在哪些维度偏离了真实样本分布"。

基线自身的两层自检（`--baseline-only`，不读 PDF）：
- **internal**：`thresholds[X]` 声明的 min/max 是否等于 `real_samples` 实测极值。
- **cross**：`real_samples` 是否能由 `samples` 用 `baseline_schema` 的提取函数原样复算。
  第二层专堵「thresholds 自洽但与 samples 口径不一致」——2026-09-17 的副本漂移事故正是这类。
  门禁：`fail=0 且 mismatch=0`。

## 2. 指标测量口径（防误读，每条都是踩坑换来的）

| 指标 | 测量口径 | 为什么这么测 |
|---|---|---|
| 边距 | 每页"最频繁出现的左边界"（mode），非 min | min 会被目录缩进/段首缩进拉小 2–3mm，mode 才是真正的版心左边线 |
| 页脚距底 | 每页"距页底最近的**非空**文字行"取中位 | PDF 常有幽灵空行（全是空格的 pad line）在页底 4mm 处，不过滤会把 8.6mm 测成 4.4mm |
| 页眉 Logo 高 | **p2 单页**、band（顶 14%）内、完全在带内的 rect/image 最大高 | 与全文档扫描法数值不同（9.5 vs 16.6mm），两套算法不可互换；baseline 必须与 audit 同口径 |
| 封面行数 | 非空文字行（`strip()` 后非空） | 空行会把 R3 测成 100 行（实为 57） |
| 封面白占比 | 50dpi 像素采样、每 4 像素取 1、纯白 (255,255,255) 计数 | 与目测的"看起来白"不同：R4 有栏目色块仍算 58.8% 白 |
| 封面白占比（**口径警告**） | 同上，但 `collect_metrics.py` 与 `audit.collect()` 的采样实现不同，同一份 PDF 差约 4–5% | R4：collect_metrics 0.557 / **audit 0.5876**。`baseline_diff` 用 audit 口径，故 baseline 的 min/max 必须是 audit 口径（`caliber: "audit_collect"`）。跨口径比较会放行过淡的封面 |
| 强调色聚类 | RGB 欧氏距离 ≤16 合并同色不同舍入 | `#0243A3` 与 `#0243A4` 是同一个蓝，不合并会虚增数量 |
| 卡片检测 | 仅**浅色调填充**（亮度 0.85–0.99、饱和度 ≤0.28）、面积 20–50%、且不与 image bbox 相交 | 万联 Excel 图表自带浅灰描边，与卡片在几何上不可区分，故放弃描边子类 |
| 行距 | 同字号相邻行基线距 ÷ 字号，取中位 | 不同字号的行不能混算 |
| 粗体占比 | font 名含 "Bold" **或** span flags bit4 | Type0 子集的 Bold 常体现在字体名（`+MicrosoftYaHei-Bold`），flags 位不可靠 |

## 3. 13 项边角细节的实测分布（R1–R6）

| # | 维度 | R1 | R2 | R3 | R4 | R5 | R6 |
|---|---|---|---|---|---|---|---|
| 1 | 段落对齐 dominant | indent | left | left | left | indent | indent |
| 2 | 段间距（×字号中位） | 3.10 | 3.14 | 1.88 | 2.28 | 2.63 | 2.47 |
| 3 | 粗体字符占比 | 11.1% | 0.0% | 27.3% | 2.6% | 11.7% | 12.4% |
| 4 | 数字小数位 dominant | 2 | 2 | 2 | 1 | 2 | 1 |
| 5 | 图序号格式 | 图表N×7 | 图N×38+表N×8 | 图表N×21 | 图表N×46 | 图表N×285 | 图表N×39 |
| 6 | 目录点线引导 | 无目录 | 32 | 14 | 33 | 174 | 33 |
| 7 | 续表命中 | 0 | 0 | 0 | 0 | 0 | 0 |
| 8 | H1 顶部 20% 比率 | 3/3 | 4/4 | 3/3 | 2/2 | 7/7 | 6/6 |
| 9 | 页眉线 top1 色 | #0243A3 | #044477 | 无线 | #933634 | #000000 | #0243A3 |
| 10 | 图占版心高比中位 | 0.179 | 0.145 | 0.206 | 0.197 | 0.188 | 0.230 |
| 11 | 中英文切换 | 否 | 否 | 否 | 否 | 否 | 否 |
| 12 | 附录字号 | 9.0 | 6.5 | 4.4 | 10.6 | 9.0 | 9.0 |
| 13 | 正文主字体 | 雅黑 | SimHei | KaiTi | KaiTi_GB2312 | 雅黑 | 雅黑 |

**两条正文派系**（都合法，全篇必须一致）：
- 国信/国新/万联派：正文 10.4–10.6pt、行距 1.34–1.51×、不缩进
- 爱建策略派（R5/R6）：正文 9.0pt、行距 1.73–1.80×、indent

**爱建系在 8p/15p/70p 三种长度下**：页眉/页脚/品牌色/字体完全一致，只有正文派系按长度切换——同一家机构的体裁稳定性是本基线的核心证据。

## 4. 阈值校准流程（改阈值必走）

1. 改 `style_benchmark_audit.py` 里的常量。
2. 在 6 份真实样本上复跑 audit：**全部 `passable=True`（允许最多 1 条 minor）**。
3. 若某份 fail：说明新阈值切进了真实分布，回滚或放宽。
4. 同步三处：`references/house-style-benchmark.md`、`scripts/samples_baseline.json`（用 build_baseline.py 重建）、`SKILL.md` 的表格。
5. 跑 `--baseline-only` 自检：**`fail=0 且 mismatch=0`**。改阈值本身不会动 baseline，但改提取函数/加字段会——这一步是防漂移的。
6. 在被审报告上复跑，记录 issue 数变化（防止误修复发）。

> 若某条阈值无法由 `samples` 复算（采集脚本还没固化该字段），**不要**把它悄悄写进 baseline：
> 必须加 `provenance="manual_inspection"` + `provenance_note` 说明取值来源，自检会把它标成
> 显式 skip 而不是假装 pass。补上采集字段后应改为数据派生并移除该标注。

### 校准记录（当前版本的分离度）

| 检查 | 阈值 | 真实样本 | 本项目报告（旧版） | 演示版 |
|---|---|---|---|---|
| Type3 | > 0 fail | 全 0 | **2055** | 21（Chromium SVG text 已知） |
| ≥2 页字号种类 | > 2 fail | 全 ≤2 | **3** | **1** |
| 题注−正文 | > 0.8pt fail | ≤0.6 | **1.0** | 0 |
| 正文色 | ≠ 黑 fail | 全黑 | **#1C2733** | 黑 |
| 强调色数 | > 2 fail | ≤2 | **4** | 2（蓝+红） |
| 卡片 | > 0 fail | 全 0 | **13** | 0 |
| 页脚距底 | < 8.5 fail | 8.6–17.73 | **7.9** | 18.8 |
| 封面白比 | < 50% fail | 58.8–75.7 | **28.1** | 89.2 |
| 封面行数 | < 50 fail | 57–110 | **9** | 61 |
| 页眉 Logo 高 | < 6 fail | 8.4–16.1 | **0.3** | 9.0 |
| 内部语言 | > 0 fail | 全 0 | **19** | 0 |

## 5. 为什么几何全绿 ≠ 可交付

本项目曾有一版报告：`audit_render.py` 报 `critical=0 major=0 deliverable=true`，
但人工目测完全不像研报。原因：**几何审计测的是"是否溢出/重叠/压字"，而该报告
的全部缺陷都在体裁层面**——字号抖动不溢出、卡片不重叠、满版封面也不越界。

**载体变了，尺子没换。** 本 skill 的存在就是为了补上"体裁"这把尺子：
`audit_render.py`（几何）与 `style_benchmark_audit.py`（体裁）都必须过，
才叫可交付。

## 6. 已知误报陷阱（复检时优先排查）

1. **像素采样 > 对象层推断**：确认填充色用 `pix.pixel(x, y)` 直接采样，
   比 `find_tables()` / fill 对象更可证伪。本项目曾因此误记三处（详见
   house-style-benchmark.md §15 修订记录）。
2. **pymupdf `find_tables()` 在位图图表页会误检**（把坐标轴刻度当表头）——
   引用"表格样式"证据前必须人工核验。
3. **页底幽灵空行**：全空格的 line 会污染"页脚距底"测量。
4. **目录缩进拉偏边距**：min 左边界 ≠ 版心左边线，用 mode。
5. **横版样本混入基线**：334×188mm 的页高只有 188mm，所有按 297mm 校准的
   阈值全部失真（页脚距底、页眉带、封面白比）。build_baseline.py 会自动剔除
   `is_landscape=True` 的样本。

## 7. 扩充基线样本的完整流程

```bash
SK=skills/report-style-benchmark

# 1. 把新样本 PDF 放进一个干净目录（只放 PDF）

# 2. 全量采集（目录模式，自动命名 S1..Sn；或先手工重命名为 R7、R8…）
python3 $SK/scripts/collect_metrics.py --dir <目录> --out /tmp/ext_new.json

# 3. 合并新旧采集结果（手工或 jq），保证进入 baseline 的样本名在 --samples 里

# 4. 重建 baseline 到临时文件（不直接覆盖正式基线）
#    --carry-manual 继承旧基线里 provenance=manual_inspection 的条目，
#    否则重建会静默丢掉人工复核过的审计覆盖。
python3 $SK/scripts/build_baseline.py \
        --extended /tmp/ext_merged.json \
        --samples R1,R2,R3,R4,R5,R6,R7 \
        --carry-manual $SK/scripts/samples_baseline.json \
        --out /tmp/baseline_new.json

# 5. 基线自检（秒级，不读 PDF）：fail=0 且 mismatch=0
python3 $SK/scripts/style_benchmark_audit.py --baseline-only --baseline /tmp/baseline_new.json

# 6. 回归验证：全部真实样本（旧 6 + 新 N）必须 baseline fails = 0
for f in <全部真实样本>; do
  python3 $SK/scripts/style_benchmark_audit.py "$f" --baseline /tmp/baseline_new.json
done

# 7. 全部通过后才替换正式基线，并同步 house-style-benchmark.md 的区间表
cp /tmp/baseline_new.json $SK/scripts/samples_baseline.json
```
