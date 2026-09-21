---
name: report-style-benchmark
description: 把生成的研报 PDF 与真实券商研报做体裁级对照审计。当需要判断一份 PDF 报告"看起来像不像真实券商研报"、需要对齐版式基准（字体嵌入/字号恒定/颜色收敛/封面要素/页眉页脚/图表容器）、需要校准或扩展基准样本、或几何审计全绿但仍怀疑交付质量时使用。不用于检查金融事实正确性。
---

# Report Style Benchmark（研报体裁基准对照）

一份报告即使几何审计全绿（无溢出、无重叠、无碰撞），仍可能**整体不像一份券商研报**——字体被转曲线、封面做成发布会海报、图表套卡片、字号跨页抖动。这些是"体裁"问题，不是几何问题。本 skill 用 6 份真实券商研报（142 页）的实测分布作为基线，对交付 PDF 做确定性裁决。

## 与 report-page-composer 的分工

| | report-page-composer | 本 skill |
|---|---|---|
| 职责 | 生成/修复页面编排（分页、续表、留白） | **对照真实研报裁决体裁一致性** |
| 时机 | 渲染前 + 渲染后 | **每次导出 PDF 后**（即使前者全绿也不能跳过） |
| 尺子 | 几何（溢出/重叠/压字） | 体裁（像不像研报） |

## 不可突破的边界

- **只读不写**：本 skill 的脚本只读取 PDF 并输出 JSON/报告，不修改任何交付物。
- **不改阈值不改基线，除非先跑回归**：任何阈值调整后必须先在 6 份真实样本上复跑，确认仍全部 `passable=True`，否则回滚。
- **不复制参考 PDF 的品牌、商标、受保护素材**：只做指标级对照。
- **横版报告不入基线**：334×188mm 等横版体裁与纵向 A4 不在同一对照空间（R7 吉图横版仅作样本存在性备注）。

## 何时触发

用户说了下面任何一句话，就走本 skill：

- "帮我看看这报告像不像真的研报" / "对比一下真实研报"
- "审计一下这份 PDF 的版式" / "检查体裁一致性"
- "为什么几何审计全绿还是不对劲"
- "调一下审计阈值" / "加一份新的基准样本"
- 报告导出 PDF 后的例行门禁

## 工具链（scripts/）

| 脚本 | 作用 | 何时运行 |
|---|---|---|
| `style_benchmark_audit.py` | **体裁审计**：13 项确定性检查 + baseline diff（7 维度 vs R1–R6 实测区间）。`--baseline-only` 不读 PDF 只做基线自检；`--verify-samples <目录>` 从真实 PDF 重新推导 audit 口径实测值并做三层校验 | 每次导出 PDF 后 |
| `baseline_schema.py` | **基线模式定义**：阈值名 → 样本提取函数 + 脚本默认阈值说明。被 `build_baseline.py` 与 `style_benchmark_audit.py` 共同导入，是提取逻辑的唯一来源 | 不单独运行；改阈值/加字段时改这里 |
| `collect_metrics.py` | **指标采集**：对单份或多份 PDF 采集 basic + extended 全量指标（含 13 项边角细节） | 扩充基线 / 深入诊断时 |
| `build_baseline.py` | **基线重建**：把采集结果转成新的 samples_baseline.json | 扩充基线样本时 |
| `samples_baseline.json` | 6 份纵向真实样本的固化基线（爱建 8p/15p/70p、国信 14p、国新 9p、万联 13p）。**全仓库唯一一份**，`report-page-composer` 通过 shim 复用同一份 | 被前三个脚本消费 |
| `text_rules.py` | **转发壳（shim）**：本 skill 的体裁审计需要判定「正文是否混入内部流程语言」，用的词表与 `report-page-composer/scripts/text_rules.py` 必须完全一致，故此处只转发、不存副本 | 不单独运行；由 `style_benchmark_audit.py` 导入 |

> **为什么 `baseline_schema.py` 必须独立存在**：生成端与校验端曾各持一份「阈值名 → 取哪个字段」的隐式知识，漂移后会出现「生成按 A 口径写入、校验按 B 口径复算」的**假通过**。2026-09-17 的 baseline 双份漂移就是这一类事故（详见 §阈值校准纪律 #6）。提取逻辑收敛成一份后，这类漂移在结构上不再可能。
>
> **`text_rules.py` 为什么也是 shim**：同一类事故在词表上又发生了一次（2026-09-18）。这里曾有一份「精简自」composer 版的过时副本，导致审计与渲染器对「什么算内部流程语言」判断不同 —— 审计放过渲染器没清掉的，或误报渲染器已处理的。现在只有 composer 那份是真源，两侧比对 `RULES_FINGERPRINT` 即可确认一致。**改词表只改 composer 那份。**

### 标准调用序列

```bash
SK=skills/report-style-benchmark

# ⓿ 基线自检（改阈值/改基线后必做；不读 PDF，秒级）
python3 $SK/scripts/style_benchmark_audit.py --baseline-only \
        --baseline $SK/scripts/samples_baseline.json
# 退出码 0 要求 fail=0 且 mismatch=0。mismatch = thresholds 与声明口径下的复算值不一致。

# ⓿b 口径与自洽应用校验（需要真实样本 PDF 目录；样本不在仓库内，故显式指定）
python3 $SK/scripts/style_benchmark_audit.py \
        --verify-samples /path/to/真实研报目录 \
        --baseline $SK/scripts/samples_baseline.json
# 三层：internal（阈值内部自洽）· cross（与声明口径一致）· self_applicability（不输给自己的样本）
# 这是唯一能验证「阈值确实来自 audit 自身算法」的手段。改阈值后建议加上。

# ① 体裁审计（对交付 PDF；需要 pymupdf）
python3 $SK/scripts/style_benchmark_audit.py report.pdf \
        --baseline $SK/scripts/samples_baseline.json \
        --out style_audit.json
# 退出码 0 = 无 critical/major；1 = 有阻断项；2 = 输入非法

# ② 深入诊断（可选）：采集全量指标
python3 $SK/scripts/collect_metrics.py --dir <真实研报目录> --out samples_extended.json
python3 $SK/scripts/collect_metrics.py --pdf report.pdf --out mine_extended.json

# ③ 扩充基线（可选）：把新样本纳入基线
python3 $SK/scripts/build_baseline.py \
        --extended samples_extended.json \
        --carry-manual $SK/scripts/samples_baseline.json \
        --out $SK/scripts/samples_baseline.json
# --carry-manual 会把旧基线里 provenance=manual_inspection 的条目原样继承，
# 避免重建时静默丢掉人工复核过的审计覆盖。
# 之后必须依次跑 ⓿ 和 ①，两者都过才能确认替换。
```

## 审计的 13 项检查（style_benchmark_audit.py）

| issue_code | 严重度 | 触发条件 | 真实研报实测 |
|---|---|---|---|
| `TYPE3_FONT_EMBEDDED` | critical | Type3 字体对象 > 0 | 全部 0 |
| `FONT_NOT_EMBEDDED` | major | 无带基名嵌入字体 | 全部 14–228 个 |
| `BODY_SIZE_UNSTABLE` | major | 出现在 ≥2 页的正文字号种类 > 2 | 全部 ≤2 |
| `CAPTION_SIZE_MISMATCH` | major | \|题注−正文\| > 0.8pt | 全部 ≤0.6 |
| `BODY_COLOR_NOT_BLACK` | major | 正文最高频色 ≠ #000000 | 全部 #000000 |
| `ACCENT_COLOR_TOO_MANY` | major | 聚类后强调色 > 2 | 全部 ≤2 |
| `CHART_WRAPPED_IN_CARD` | major | 浅色调大面积矩形 > 0 | 全部 0 |
| `FOOTER_TOO_CLOSE_TO_EDGE` | major | 页脚距底中位 < 8.5mm | 8.6–17.73 |
| `COVER_NOT_WHITE` | major | 封面近白像素 < 50% | 58.8%–75.7% |
| `COVER_TOO_SPARSE` | major | 封面非空文字行 < 50 | 57–110 |
| `HEADER_NO_INSTITUTION_MARK` | major | 页眉带内最大图形高 < 6mm | 8.4–16.1mm |
| `CAPTION_MISSING_UNIT` | info | 22 条题注 0 条带单位 | 通常有 |
| `UNIT_REPEATED_IN_CELLS` | info | 「数值+金额单位」绑定 ≥ 20 处 | — |
| `INTERNAL_PROCESS_LANGUAGE` | major | 内部流程语言命中 > 0 | 全部 0 |

另有 `FOOTER_GAP_TIGHT`（minor，页脚距底 < 12mm 但 ≥ 8.5mm）。

## baseline diff 的 7 个维度

跑 `--baseline` 时输出本报告实测值 vs R1–R6 区间的逐项 verdict：

- Type3 字体对象数（max=0）· 带名字体对象数（min=14）
- ≥2 页正文字号种类（max=2）· 封面近白像素比（min=0.5876）
- 封面非空文字行数（min=57）· 页眉 Logo 高（min=8.4mm）· 页脚距底中位（min=8.6mm）

> 这 7 个维度的 min/max 必须来自 **audit 自身的算法**（`caliber: "audit_collect"`），
> 因为 `baseline_diff()` 拿 `collect()` 的实测值去比它们。它们存在 `audit_samples` 块里，
> 由 `--verify-samples <样本目录>` 从真实 PDF 重新推导。
> 其余维度用 `collect_metrics.py` 口径（`caliber: "collect_metrics"`），由 `samples` 块复算。
> 两套口径数值不可互换——2026-09-18 修正过一次跨口径比较，详见 §阈值校准纪律 #7。

**6 份真实样本 baseline fails = 0 是门禁的自我验证**；被审报告的 baseline fails 数就是它与真实研报分布的偏离维度数。

## 阈值校准纪律（重要，违反必翻车）

1. **每条阈值都来自真实样本实测分布，并留出分离度**——不要拍脑袋改。
2. **改阈值前先跑回归**：修改常量后在 6 份真实样本上复跑，必须全部 `passable=True`。
3. **口径必须与算法一致**：baseline 里的实测值必须来自**同一个算法**。本 skill 的 `HEADER_MARK_H_MM_MIN` 用的是 audit 的 p2 单页测法（R1/R5/R6=9.5mm），不是全文档扫描法（16.6mm）——两套算法数值不可互换。
4. **口径统一的三个产物**：`references/house-style-benchmark.md`、`scripts/samples_baseline.json`、`SKILL.md` 的数字必须一致。改一处必须同步三处。
5. **横版不入基线**。加样本前先确认是纵向 A4（210×297±1mm）。
6. **baseline 必须自洽，且只能有一份**——两道门禁：
   - **唯一性**：全仓库只有 `report-style-benchmark/scripts/samples_baseline.json` 一份。`report-page-composer` 通过 `scripts/style_benchmark_audit.py` 这个 shim 转发到本 skill，不得再存副本。副本会立刻产生口径分裂（同一份报告，`--baseline` 的结论取决于你调用了哪一份）。
   - **自洽性**：`thresholds_with_baseline[X].real_samples` 必须能由 `samples` 用 `baseline_schema.THRESHOLD_EXTRACTORS` **原样复算**。不能复算的条目必须显式标注 `provenance="manual_inspection"` + 说明。门禁命令：`style_benchmark_audit.py --baseline-only` 必须 `fail=0 且 mismatch=0`。

   > **历史事故（2026-09-17，务必引以为戒）**：曾存在两份 baseline。composer 版用 `collect_extended.py` 的全文档扫描口径写 `samples`（`header_mark_h_mm` = 16.6），却把手写的 audit p2 单页口径写进 `thresholds.real_samples`（9.5）。同一文件里两套口径互相矛盾，而当时的自检**只看 thresholds 内部是否自洽**，于是 16 项全 ✓ 却仍然是错的。同一份文件的 `ACCENT_COLOR_COUNT_MAX` 还残留着「手写 `[1,1]` vs 数据派生 `[0,1]`」的老问题——即本表 #1 记录的那次事故，在 composer 版里从未真正修复。
   >
   > 修复方式：`baseline_selfcheck()` 增加第二层交叉复算（`samples` ↔ `thresholds`），副本文件删除，composer 改为 shim。
7. **口径必须逐条声明**（`caliber` 字段）——baseline 里存在两套测量实现，数值不可互换：
   - `caliber: "collect_metrics"`（默认）：`real_samples` 由 `samples` 块复算（`baseline_schema.THRESHOLD_EXTRACTORS`）。
   - `caliber: "audit_collect"`：`real_samples` 由 `audit_samples` 块复算，而该块只能由 `--verify-samples <样本目录>` 从真实 PDF 推导。

   `baseline_diff()` 消费的 7 个维度**必须**是 `audit_collect`。

   > **历史事故（2026-09-18）**：这 7 个维度的 min/max 原先取自 `collect_metrics.py::analyze_basics()`，
   > 而 `baseline_diff()` 拿 `collect()` 的实测值去比它们——正是本表 #3 禁止的跨口径比较。
   > 影响最大的是 `COVER_WHITE_RATIO_MIN`：collect_metrics 口径下界 0.557，audit 口径下界 0.5876，
   > 前者偏宽松约 5%，会放行过淡的封面。修正后 `--verify-samples` 逐维度一致。
   >
   > **同时暴露的舍入陷阱**：`audit_samples` 必须存全精度。R4 的 `cover_white_ratio` 真实值是
   > `0.5875850340136054`，若按 4 位小数存成 `0.5876`，`observed >= rmin` 立刻判 fail——
   > 基线会**输给它自己收录的样本**。精度只在展示层处理。
   >
   > 为堵住这类问题，`--verify-samples` 增加第三层 `self_applicability`：用与 `baseline_diff()`
   > 相同的判定逻辑跑一遍全部真实样本，`fail` 必须为 0。前两层（internal / cross）都验证不了它——
   > 阈值比实测更紧时，内部仍然完全自洽。

## 采集指标（collect_metrics.py）

basic：页面尺寸/边距/字号跨页分布/正文色/强调色/行距/封面近白比/封面行数/页眉 Logo 高/页脚距底/字体嵌入。

extended（13 项边角细节）：段落对齐 / 段间距 / 粗体字符占比 / 数字小数位 / 图序号格式 / 目录引导符 / 续表 / H1 换页 / 页眉线色 / 图表占版心比 / 中英文切换 / 附录字号 / 续表标记。

## 完成标准（一份报告通过本 skill 的门禁）

- `style_benchmark_audit.py` 退出码 0：`critical=0 且 major=0`
- `--baseline` 下 **baseline fails = 0**（全部 7 维度落在 R1–R6 区间内）
- 对外正文 0 内部流程语言、0 单元格重复单位、题注单位标注齐全

## 已知限制（不要误报为缺陷）

- **Chromium 渲染 SVG `<text>` 必然产生 ~20 个 Type3**：这是 headless print 的固有行为，真实研报走 Word/Excel/Adobe 通道才 0 Type3。对 Chromium 链路可考虑放宽阈值至 ≤30，但**放宽前必须先跑基线回归**，且要在 PR/说明里写明放宽理由。
- **页边距一致性未自动化**：真实研报正文栏与图表栏宽度常不同，跨页比最小左边界必然误报。脚本只输出 `left_margin_mm_per_page` 供人看，是否漂移由人复核。
- **万联式 Excel 灰边框与卡片不可区分**：卡片检测只认浅色调填充（亮度 0.85–0.99、饱和度 ≤0.28），放弃描边子类。

## 扩充基线的方法

1. 把新样本 PDF 放进一个目录
2. `collect_metrics.py --dir <目录> --out extended.json`
3. `build_baseline.py --extended extended.json --out samples_baseline.json.new`
4. **对全部真实样本（旧 6 份 + 新增）复跑 audit**，全部 `passable=True` 才能替换 `.new` 为正式基线
5. 同步更新 `references/house-style-benchmark.md` 里的实测区间表

## 自检（本 skill 自身的回归测试）

开发或修改本 skill 的脚本/阈值后，按下表逐项复测。**任何一项不符合预期值就视为回归，必须先修再交付。**

| # | 命令（`$SK` = 本 skill 根目录） | 期望 |
|---|---|---|
| 1 | 对 6 份纵向真实样本各跑 `style_benchmark_audit.py <pdf> --baseline $SK/scripts/samples_baseline.json` | 全部 `passable=True`、`baseline fails: 0`、退出码 0 |
| 2 | 对已知不合格报告（设计稿风格）跑同命令 | `passable=False`、`baseline fails: 7`、退出码 1 |
| 3 | 对演示版（`演示-基准对版.pdf`）跑同命令 | `major=0`、`baseline fails: 1`（仅 Type3，Chromium 已知限制） |
| 4 | `collect_metrics.py --pdf <任一样本> --out /tmp/t.json` | 正常产出，`basic` 含 `header_mark_h_mm` 且 ∈ [8.4, 16.1] |
| 5 | `collect_metrics.py --dir <样本目录>` + 改名 R1–R7 + `build_baseline.py --carry-manual <旧基线>` 重建 | 与 `scripts/samples_baseline.json` 的 16 项数据派生阈值 min/max **完全一致**（不再有 ACCENT min 差 1 的例外——该例外是 composer 版手写值造成的，已随副本删除） |
| 6 | `style_benchmark_audit.py /nonexistent.pdf` | 退出码 2 |
| 7 | SKILL.md frontmatter | `name: report-style-benchmark` 且 description 完整；正文引用的脚本/文档全部存在于 skill 目录 |
| 8 | `style_benchmark_audit.py --baseline-only --baseline $SK/scripts/samples_baseline.json` | `fail=0`、`mismatch=0`、退出码 0（17 项：16 pass + 1 条 `manual_provenance` 显式跳过） |
| 9 | `style_benchmark_audit.py --baseline-only`（不给 `--baseline`） | 退出码 2，提示需要 `--baseline` |
| 10 | `skills/report-page-composer/scripts/style_benchmark_audit.py --baseline-only`（shim） | 与 #8 输出**逐字一致**、退出码 0。shim 应自动补默认 baseline |
| 11 | 全仓库检索 `find skills -name samples_baseline.json` | **只有 1 个命中**（`skills/report-style-benchmark/scripts/`）。多一个就是副本回流 |
| 12 | `style_benchmark_audit.py --verify-samples <真实样本目录> --baseline $SK/scripts/samples_baseline.json` | `mismatch=0` 且 `self_apply_fail_count=0`、退出码 0。**这是唯一能验证口径正确性的一层**；改阈值后必跑 |
| 13 | `style_benchmark_audit.py --verify-samples <目录> --write-audit-samples --baseline <临时基线>` | `audit_samples` 块被写入，且 7 个维度被标记 `caliber: "audit_collect"` |

> 阈值纪律：任何阈值修改都要重跑 #1（6 份真实样本必须仍全过），并同步 `references/house-style-benchmark.md` §14 的校准表。

## 参考

- [references/house-style-benchmark.md](references/house-style-benchmark.md) —— 完整基准规范（15 节，含 18 项维度对照、21 项验收清单、阈值校准证据）
- [references/comparison-method.md](references/comparison-method.md) —— 对照方法论（怎么测、怎么校准、13 项边角细节的实测分布）
