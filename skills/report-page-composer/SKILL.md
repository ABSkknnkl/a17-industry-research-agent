---
name: report-page-composer
description: Plan and repair page-level composition for research-report HTML/PDF exports when pagination, continuation tables, Chinese wrapping, chart arrangement, whitespace, or publication quality matters. Do not use it to change financial facts or research conclusions.
---

# Report Page Composer

把报告当成一组经过编辑的“页面”，而不是一串等待浏览器自动分页的网页组件。目标是让每页拥有明确角色、稳定版心、单一视觉焦点和可解释的留白，同时保持所有事实、数字、引用与上游顺序不变。

> 路由说明：本 skill 负责 **分页 HTML / PDF 的页面级出版编排**。若交付重点是连续滚动、响应式、多种小节图文关系、侧栏导航和可检索证据中心，先使用 `$report-html-composer`；用户选择导出 PDF 后，再使用本 skill 做分页、续表与 A4 几何门禁。两者共享内容和证据模型，不得各自复制事实。

## 不可突破的边界

- 只改变呈现：分页、布局、尺寸、图表视觉编码、标题层级、图注形式和附录层级。
- 不新增、改写或推断任何金融事实、数字、结论、引用与证据关系。可删除重复的结构性标签和模板话术，可将低优先级说明下沉到附录；唯一事实必须保留且仍可追溯。
- 不因追求满版而缩小到不可读、裁掉内容、拆散图题/图表/来源，或把正文转成图片。
- 不把内部状态码、机器字段、调试说明当作正文视觉元素；必须保留时放入内部审计附录。
- 不复制参考 PDF 的品牌、商标、受保护素材或具体文案；只借鉴版式原则。

## 体裁一致性（真实券商研报的硬特征）

规则之外的"设计感"会把报告推离体裁。以下几条是真实研报的共有特征，**用设计语言替代它们是本 skill 最容易犯的错**：

- **白底。** 封面与内页都是白底；不使用满版色块封面。封面是"信息密集的首屏"（机构标识、栏目带与日期、主标题、副标题、评级、分析师与联系方式、相关研究、投资要点），不是一张海报——非空文字行数应在 50 以上（真实研报实测 57–110）。
- **正文纯黑。** 正文色 `#000000`，不用深蓝/藏青等"设计色"。
- **强调色只有一个。** 品牌色仅用于标题、图表题注、表头；不并列使用多个强调色，不使用金色/棕色/绿色等非品牌色。
- **图表不放进卡片。** 白底直排，无底色块、无外框；用题注下方一条通栏细线分组。卡片化会切碎版心，把图表降格为"仪表盘组件"。
- **图表题注字号 = 正文字号**，单位写在题注（`图表N：标题（单位：X）`），不散落在单元格与绘图区。
- **图表按品牌色着色，不按数值正负着色。** 正负由条形方向表达；至多保留一个语义高亮色。
- **字号、边距、行距全篇恒定。** 禁止渲染器按"可用空间"逐页自适应字号——那会让同一层级文字在不同页面大小不同，观感是排版抖动。
- **机构标识贯穿。** 页眉左侧保留彩色机构标识位，页眉线为紧贴的双色/双线且从标识右侧起；页脚为法律声明式文本 + 裸页码，距页底不小于 12mm。
- **对外正文不含内部流程语言。** "本节保留研究位置""本图数值与附录证据索引一致""页码在最终分页后回填校验"这类表述在真实研报中命中为零，必须改写或下沉附录。

## 先选择文档类型

根据正文规模和使用场景选择一种基线，不混用骨架：

- `brief_note`：约 6–12 页。首页摘要，正文直接进入图文论证，风险与声明收尾。
- `research_report`：约 12–60 页。目录、图表目录、稳定页眉页脚、分级章节和独立附录。
- `data_dashboard`：横版或宽页。固定面板网格、同页比较优先，不把高密度仪表盘硬塞进 A4 竖版。

## 模板预设（Template Profiles）

在券商研报体裁基准内，系统提供 4 种预设实现视觉多元化。**所有预设严格遵守体裁一致性硬约束**（白底、纯黑正文、单一品牌色、图表无卡片、字号全篇恒定）。预设间差异仅体现在品牌色、封面布局、图表排列偏好和间距密度。

| 预设 | 品牌色 | 封面布局 | 图表偏好 | 间距 | 适用场景 |
|---|---|---|---|---|---|
| `classic_research` | `#0243A4` 深蓝 | 双栏密集 | 均衡 | 均衡 | 标准研报、多章节深度分析 |
| `modern_analysis` | `#0A5C5C` 青色 | 标题优先 | 偏好并列 | 宽裕 | 新兴产业、消费/科技报告 |
| `data_intensive` | `#1B3154` 深藏蓝 | 密集三列 | 偏好单图 | 紧凑 | 财报分析、数据月报 |
| `narrative_flow` | `#7A1F3D` 酒红 | 宽标题 | 单图配文 | 宽裕 | 行业深度叙事、政策分析 |

**选择规则**（确定性，`auto` 模式）：
1. 量化占比 ≥70% 且表格候选 ≥3 → `data_intensive`
2. 定性占比 ≥60% 且图表 ≤4 → `narrative_flow`
3. 图表/数据/解释均衡且章节 ≥5 → `modern_analysis`
4. 其他 → `classic_research`

用户可通过 `template_profile` 参数显式指定预设。**同一份报告只能使用一个预设，全篇统一。**

**图表配色跟随预设**：图表的品牌色、语义色与分类色板首位都由当前预设派生（`svg.ChartPalette.from_profile`），不是写死的。正文装饰与图表必须同源，否则会出现"墨绿正文 + 蓝色图表"—— 见下文硬约束第 4 条。

详细预设定义见 [references/template-profiles.md](references/template-profiles.md)。

**任何排版决策之前，先读 [references/house-style-benchmark.md](references/house-style-benchmark.md)。** 它是从 7 份真实券商/咨询研报（178 页）PDF 对象级实测提炼出的版式基准，给出了字号、边距、色彩、图表容器、封面要素、页眉页脚的目标值与验收条件。**不要凭"设计感"决策；凡本基准有明确取值的维度，一律服从基准。**

若在本工程中工作，先读 [references/project-integration.md](references/project-integration.md)。需要详细排版准则时读 [references/professional-layout-rules.md](references/professional-layout-rules.md)；压缩冗长文案、空状态和重复说明时读 [references/editorial-density-rules.md](references/editorial-density-rules.md)；选图、重绘或组合图表时读 [references/chart-design-rules.md](references/chart-design-rules.md)；需要创建结构化逐页蓝图时读 [references/page-plan-contract.md](references/page-plan-contract.md)；渲染复检时读 [references/visual-review-checklist.md](references/visual-review-checklist.md)；选择模板预设时读 [references/template-profiles.md](references/template-profiles.md)。

### Agent5 编辑模型整合

Agent5（`report_fusion`）的编辑模型上下文（`report_editor_context`）已整合模版库的核心规则提示词，包括：

- **体裁约束**（genre_constraints）：白底、纯黑正文、单一品牌色等 9 条铁律
- **排版规则**（layout_rules）：相邻三页不重复、至少三种构图、有效内容区 65%–92% 等 5 条
- **图表规则**（chart_rules）：单指标用指标卡、长标签用横向条形图等 5 条
- **编辑规则**（editorial_rules）：五级信息层、重复段落归并、数值精度降档等 5 条

编辑模型同时接收当前模板预设信息（品牌色、封面布局、图表偏好、间距、表头风格）和可用预设列表，以便在编排决策中保持预设一致性。

## 工具链

本 skill 自带四个可执行脚本，位于 `scripts/`。**不要重新发明它们**——每次重写词表和测量逻辑，都会重新引入同一批缺陷。

| 脚本 | 作用 | 何时必须运行 |
|---|---|---|
| `text_rules.py` | 净化规则的唯一来源：内部工件名、状态码、内部 ID、数值精度的改写表。导出 `RULES_FINGERPRINT` 供跨模块一致性校验 | 不单独运行；由下列脚本、`report-style-benchmark` 的 shim 与后端 `text_rules_loader` 共同导入。可直接 `python3 text_rules.py` 跑自检（打印指纹 + 幂等性检查） |
| `text_hygiene.py` | 渲染**前**文本门：重复段落、空话模板、机器字段、超精度数值 | 内容清单定稿后、进入页面编排前 |
| `validate_page_plan.py` | 蓝图结构契约校验 | 生成 `page_composition_plan.json` 后 |
| `measure_pages.js` | 渲染后几何测量（配合 playwright-cli 的 `run-code`） | 每次渲染 HTML 之后 |
| `audit_render.py` | 渲染**后**裁决：溢出、页脚重叠、元素重叠、标签碰撞、空单元格、排版留白 | 每次 `measure_pages.js` 之后 |
| `style_benchmark_audit.py` | **体裁审计**：字号是否恒定、正文是否纯黑、强调色是否收敛、图表是否被卡片包裹、页眉是否有机构标识、封面是否白底且信息完整、页脚是否贴边、正文是否混入内部流程语言。带 `--baseline` 可对 6 份纵向真实样本的实测区间做 diff 回归 | 每次导出 PDF 之后；`audit_render.py` 全绿也**不能**跳过这一步 |
| `samples_baseline.json` | **不在本 skill 内**。基线已收敛为全仓库唯一一份：`skills/report-style-benchmark/scripts/samples_baseline.json` | 不需要直接引用；shim 会自动补上 |

> **本 skill 的 `scripts/style_benchmark_audit.py` 是转发壳（shim）**，实现在
> `skills/report-style-benchmark/scripts/style_benchmark_audit.py`，只有一份。
> 保留同名入口是为了让既有引用继续有效；调用方无需改动，`--baseline` 缺省时 shim 会自动补默认路径。
>
> **不要再在本 skill 下放 `samples_baseline.json` 的副本。** 历史上这里有一份独立副本，
> 与 benchmark 版口径不同（全文档扫描 vs audit p2 单页），导致同一份报告 `--baseline`
> 的结论取决于调用了哪一份。副本已于 2026-09-18 删除，双份漂移的细节记在
> `report-style-benchmark/SKILL.md` §阈值校准纪律 #6。
| `export_pdf.js` | 正确的 A4 / 保留背景 PDF 导出 | 交付 PDF 时 |

标准调用序列（本工程用 `python3`，Node 侧用 `playwright-cli`）：

```bash
SK=skills/report-page-composer

# ① 渲染前：净化内容清单，并产出可追溯的合并记录
python3 $SK/scripts/text_hygiene.py inventory.json \
        --write-fixed inventory.fixed.json --out hygiene.json
python3 $SK/scripts/text_hygiene.py inventory.fixed.json   # 必须 clean=True 才继续

# ② 蓝图契约
python3 $SK/scripts/validate_page_plan.py page_composition_plan.json

# ③ 渲染 paged HTML（由本工程的渲染器完成，DOM 钩子见 render_contract）

# ④ 渲染后：测量 + 裁决
playwright-cli goto "http://127.0.0.1:8080/report.html"
playwright-cli run-code --filename $SK/scripts/measure_pages.js  --raw > metrics.json
python3 $SK/scripts/audit_render.py metrics.json \
        --plan page_composition_plan.json --out audit.json

# ⑤ 导出 PDF
playwright-cli goto "http://127.0.0.1:8080/report.html?pdf=/tmp/report.pdf&format=A4"
playwright-cli run-code --filename $SK/scripts/export_pdf.js --raw

# ⑥ 体裁审计（对交付 PDF；需要 pymupdf）
#    本路径是 shim，实现在 report-style-benchmark 下；--baseline 缺省时自动补默认路径。
python3 $SK/scripts/style_benchmark_audit.py /tmp/report.pdf \
        --out style_audit.json
# 退出码 0 = 无 critical/major；1 = 有阻断项；2 = 输入非法
# baseline diff 列出 7 维度（Type3 字体 / 带名字体 / ≥2页正文字号种类 /
# 封面近白占比 / 封面行数 / 页眉 Logo 高 / 页脚底距）上 vs R1-R6 实测区间的对比。
# 6 份真实样本 baseline fails = 0；Agent 5 改制后的交付 PDF 同样是 fails = 0
# （2026-09-17 前的老产物曾为 fails = 7，那批已作废）。

# ⑥b 基线自检（改阈值 / 改基线后必做；不读 PDF）
python3 $SK/scripts/style_benchmark_audit.py --baseline-only
# 退出码 0 要求 fail=0 且 mismatch=0
```

`audit_render.py`、`text_hygiene.py`、`style_benchmark_audit.py` 的退出码：`0` 无阻断项，`1` 有阻断项，`2` 输入非法。**它们用退出码当门禁，不要只读输出。**

### 四条被真实缺陷逼出来的硬约束

1. **不要用 `playwright-cli pdf` 交付。** 它的默认纸张是 US Letter，会忽略 `@page { size: A4 }`，把 A4 报告改成 612×792pt；且默认不保留背景，封面底色、表头底色和图表配色会整片消失。必须用 `export_pdf.js`（`printBackground` + `preferCSSPageSize`）。导出后核对纸张：A4 应为 `595×842pt` / `210×297mm`。
2. **正文净化只有一个入口。** 渲染器必须 `from text_rules import sanitize_public`，不要在渲染器里另写一套 `replace`。三处各写一套词表一定会漂移：审计放过渲染器没清掉的，或误报渲染器已处理的。
   - **后端不复制词表**：`backend/app/reporting/text_rules_loader.py` 按路径加载本文件（fail-open；读不到时只做机器 ID 人性化，并通过 `/health/ready` 的 `report_skill_text_rules_missing` 上报）。HTML 与 Markdown 都走 `text_rules_loader.sanitize_for_render()`。
   - **本文件的 `RULES_FINGERPRINT` 是跨模块一致性的锚点**：它只覆盖词表内容（不含函数实现），因此「渲染器用的词表」与「审计用的词表」是同一份时指纹必然相同。改任何一张表都会让指纹变化 —— 这是机械化的防漂移手段，不是文档约定。
   - **`report-style-benchmark/scripts/text_rules.py` 是转发壳（shim）**，不存第二份。两侧指纹必须逐字相同（`tests/reporting/test_text_rules_parity.py` 断言）。
   - **状态码措辞与 `backend/app/reporting/presentation.py` 的结构化标签必须同词**：同一份报告里 `partial` 不能一处写「部分支持」、另一处写「部分覆盖」。该文件持有 `DIMENSION_LABELS` / `COVERAGE_STATUS_LABELS` / `CHECK_STATUS_LABELS`，本文件的 `STATUS_CODE_MAP` 对齐它们。改任一侧都要同步另一侧，测试会拦。
   - **状态码是 ASCII 标识符，边界用 ASCII lookaround，不要用 `\b`**（CJK 语境下 `\b` 不可靠）。没有边界时 `supported` 会切进 `unsupported`，`growth` 会切进 `growth_rate`。
3. **渲染器必须暴露测量钩子。** 分页容器、页眉、页脚、内容区要有稳定选择器，页面要有角色与章节标记（见 `page-plan-contract.md` 的 `render_contract`）。没有章节标记，`UNEXPLAINED_WHITESPACE` 无法区分“章节正常结束的留白”和“分页失败”，只能靠角色猜测。
4. **图表配色必须与正文装饰同源。** 正文的 h2 / 表头 / 封面条走 `template_profile.brand_color`，图表也必须走同一个值，唯一来源是 `backend/app/reporting/svg.py` 的 `ChartPalette.from_profile(template_profile)`（`ChartPalette.default()` 只作旧存档兜底）。2026-09-18 实测：加固前 `svg.py` 硬编码 `#0b4fa3` 一族、HTML 叠加层再强制映射回 `#0243A4`，于是 `modern_analysis`（墨绿）与 `narrative_flow`（酒红）的正文是彩色、图表却永远是经典研报蓝。
   - **先定 profile，再渲图表。** profile 由 `plan_visual_decision` 决定，而它需要图表列表 —— 所以 `assembler.build_report_view` 必须按这个顺序来。**不要**用空 `svg=""` 占位走两遍：`EmbeddedChart.svg` 是 `min_length=1`，占位会在第一遍就抛 `ValidationError` 把整个生成打断。决策只读 `chart_id` / `display_kind` / 数量，直接传 `ChartSpec` 即可。
   - **Agent 3 烤进 `ChartSpec.option["color"]` 的分类色板会盖掉 `palette.series`。** 渲染层要把历史品牌蓝 `#0b4fa3` 重指到当前品牌色（`svg._series_colors`），但**只重指这一个值**：固定尾段（`#0b78b8`/`#0da9d6`/`#d59a20`/`#9a4d55`）是刻意的分类色，彩印与灰度都要能区分；`colorblind_safe` 主题的 ramp 里没有 `#0b4fa3`，色盲友好性不受影响。
   - **叠加层的 `_svg_fill_normalize` 必须覆盖渲染器输出的每一个文字色。** 漏登记会静默落到中性灰 —— 行业链节点白字 `#fff`（品牌色块上的白字）就这样变成了灰字压品牌色块。未登记时必须记 warning，不许静默。
   - 守卫在 `tests/reporting/test_svg.py`：枚举全部图族的 `<text fill>` 断言都在归一表里、四个 profile 的品牌色跟随且不串色、白字回归、ramp 重指。

## 必须产生的中间结果

在生成 HTML 或 PDF 前先形成 `page_composition_plan.json`。它至少要说明：

- 文档类型、页面尺寸、版心、字体体系和颜色体系；
- `render_contract`：分页容器/页眉/页脚/内容区的选择器，以及角色与章节的 DOM 属性名；
- 每页的 `page_role`、`chapter_id`、网格、预计填充率；
- 每个内容块所在页、宽度跨度、尺寸档位、`reading_level` 和是否可拆；
- 图表的视觉任务、组合方式，以及极值离群时的降级声明；
- 表格的列宽策略、续表规则和横竖版策略；
- 正文版与内部审计版分别包含哪些附录；
- 一级/二级阅读层的文字预算，以及每个内容块是原文展示、摘要展示还是下沉附录；
- `content_dispositions`：没有直接显示的原始内容 ID 及其去重/下沉处理，以及渲染前门产出的合并记录；
- 目录、图表目录、页眉页脚、页码与内部跳转的出版导航规则。

配置字段含义见 [references/page-plan-contract.md](references/page-plan-contract.md)。用 `scripts/validate_page_plan.py` 检查契约。验证通过只表示蓝图结构自洽，**不替代**真实渲染后的几何审计。

## 页面编排流程

### 1. 建立内容清单

记录每个标题、段落、结论、图表、表格、来源与附录块的稳定 ID、预计高度和阅读优先级。先区分：

- 必须连续阅读的正文；
- 可并列比较的图表或指标；
- 可移入附录的审计信息；
- 允许单独成页的目录、章节过渡、风险、声明和结束页。

### 2. 清洗并压缩（先跑文本门，再排版）

先运行 `scripts/text_hygiene.py`，不要跳过直接排版：

```bash
python3 scripts/text_hygiene.py inventory.json --write-fixed inventory.fixed.json
```

它做四件确定性的事，并输出可直接消费的净化清单：

- **重复段落归并**：归一化后 Jaccard 相似度 ≥ 0.90 的长段落判为重复，保留首次完整表达。
- **空话模板归并**：同一“无数据可判”句式（`当前可用证据不足以对 X 形成…本节保留研究位置…`）**全文只保留一次**，其余并入覆盖矩阵。判据是句式下标，不是原文——换个主语仍是同一句空话。
- **机器字段改写**：`missing_inputs` / `period_end` / `available_at` / `scope` / `Agent 4` / 证据 ID / 计算 ID 一律改写为读者可读表述。
- **数值精度降档**：百分比统一 2 位小数；9 位以上金额降为亿元；无单位的 10 位以上裸数一律按金额处理。正文里出现 `-12423798001.78` 或 `5.1848%` 都算缺陷。

合并掉的条目写入 `content_dispositions`，供蓝图追溯。**净化后必须复检一次并确认 `clean=True`**，否则说明词表覆盖不足，需扩展 `text_rules.py` 而不是绕过。

然后把内容分为 `headline`、`lead`、`support`、`detail`、`audit` 五级。首屏只承担结论和必要证据；完整口径、过程说明、机器状态和证据索引下沉。不得因为上游生成了一段文字，就默认它必须在正文中占据同等视觉重量。

金融事实缩写必须通过事实 ID、数值、单位和引用的覆盖校验（见 `editorial-density-rules.md`）。

### 3. 先规划页面角色

每页只能有一个主角色：`cover`、`toc`、`list_of_figures`、`executive_summary`、`chapter_opener`、`narrative`、`chart_page`、`comparison_page`、`table_page`、`appendix`、`disclosure`、`closing`。

每页还要给出 `chapter_id`。渲染后审计用它判断留白是否合法；缺失会让留白检查失去判据。

普通正文页最多出现一个一级章节起点。新章节不得挤在上一章的零碎尾部；若剩余空间无法同时容纳标题、导语和一个有效内容块，则另起页。

### 4. 选择页级网格

按信息任务选择，而不是按组件类型机械选择：

- 文字论证：单栏；仅短结论或短注释可双栏。中文长段落禁止三栏。
- 一项主结论：主图或大指标占 8–12 栅格，解释占 4–12 栅格。
- 两项直接比较：双图、双指标卡或左右对照。
- 三至四项同类比较：小多图或 2×2；统一坐标和图例。
- 长表：整页表格、横版附表、拆成主题子表，或改为卡片列表；不能依靠压窄列宽解决。

内容允许时，标准报告至少出现三种正文构图；相邻三页不得完全重复同一网格和焦点位置。

### 5. 处理中文文字与续表

以下为硬规则：

- 中文标题、表头、标签默认横排；不得因窄列自动形成“一字一行”的假竖排。
- **列宽必须按最长标签计算，不能按比例均分。** 判定标准可量化：内容宽度 ÷ 字号 < 5 个汉字宽度、且折成 3 行以上，即为窄列压字。定列宽时用 `<colgroup>` 显式指定，不要留给浏览器自动分配——自动分配在固定表格布局下会把 20% 的可见宽度交给 padding。
- 表头最多两行，正文标签最多三行。超过限制时依次尝试：扩大列宽、减少列数、拆表、转卡片、转横版附表。
- 不使用 `word-break: break-all` 处理中文标题或表头；短标签优先 `white-space: nowrap`，长标签采用可控短语换行。
- 中文正文左对齐，不用强制两端对齐拉大字距；数字与单位、括号、百分号和正负号保持成组。
- 跨页表格必须重复表头、保持列宽、显示“表 X（续）”，并保留与原表相同的来源上下文。
- 禁止页底只留下表名/表头而无数据行；禁止下一页出现无表名的裸续表。
- **续表引用必须成对**：本页写“续页见下页”，下一页就必须真的有带“（续）”的表题；表题写“（续）”，上一页就必须有同号原表。
- 表格最后一页若只剩少量行，应与前页重新平衡，避免“续表几行+半页空白”。
- **内容相同的连续表格行要成组**（例如 9 条同“建议处理”的异常记录合并为“DQ-ANOM-01 等 9 项”一行），并在表下注明归并关系。

### 6. 编排图表

先写清图表任务，再选择视觉形式：

- 单一数字：指标卡，不使用柱、线或饼。
- 长中文分类或排名：横向条形图。
- 时间趋势：折线或面积图；时间点少于三个时不伪装成趋势。
- 同期比较：并列柱或小多图，坐标和颜色保持一致。
- 构成：类别少且差异明显时用环图；类别多时改为排序条形图。
- 产业关系：流程/产业链图，不用普通类别图代替。

同页图表应选择 `single_hero`、`two_up`、`hero_plus_two`、`two_by_two` 或 `small_multiples`。图题只保留一次；图号和标题在图上方，来源在图下方。分析目的、数据口径和长脚注进入短注或附录，不能在每张图下堆成灰色文字墙。

图表必须占满自己的容器：绘图区不能只占容器中间一小块；轴标签、图例和来源在最终 PDF 尺寸下可读；同组图对齐标题线、绘图区和来源线。

**三类必须提前规避的图表缺陷**（都是渲染后才看得见、规划期就要定好）：

- **发散条形图的标签碰撞**：水平条形 + 负值 + 长中文标签时，负值条会向左延伸到分类标签所在区域，数据标签与分类标签必然重叠。必须给分类标签一个**独占槽位**（固定左栏），并把坐标域按最大绝对值**对称**设置，使条形不侵入槽位。
- **极值离群压扁可比序列**：当最大绝对值 ≥ 次大值的 8 倍时（例：`-7056%` 与 `±106%`），同轴条形会把其余序列压成一条线。必须显式降级为表格/注解表，保留全部原值并说明不可直接横向比较；不要靠“分开画两张图”掩盖。
- **刻度冗长与虚构区间**：刻度用整数量级（`-7000 / -5000 / -3000 / 0`），不要 `-7,622.62%`；全正数据的纵轴不得出现负值区间（否则读者会以为存在负值）。

图表还必须通过排序、零基线、单位、刻度密度、图例位置、标签冲突、颜色语义、缺失值和正负值呈现的校验。详细规则见 [references/chart-design-rules.md](references/chart-design-rules.md)。

### 7. 通过候选页和回溯解决分页

对每个内容段生成至少两个可行页组合，再以代价函数选择：溢出、裁切、内容丢失为无限大代价；裸续表、孤悬标题、可比图拆页、多个一级章节和中途异常留白为高代价；构图连续重复、局部密度不均为中代价。

当当前块放不下时，按“拆可拆段落 → 换网格 → 与前页重平衡 → 候选横版表页 → 另起语义完整页”处理。不允许简单把整块推到下一页却不重算前页。

**分页结论必须由测量决定，不能由估计决定。** 渲染后运行 `measure_pages.js` + `audit_render.py`，用实测的 `fill_ratio` 和 `PAGE_CONTENT_OVERFLOW` 驱动重排。计划里的 `estimated_fill` 只是规划期假设，实测值与之偏离时以实测为准并回填。

### 8. 控制留白与节奏

普通正文页的有效内容区通常保持约 65%–92%。有效内容 = 内容底边 − 版心上沿，分母是**安全版心下沿**（有页脚时取页脚顶边减安全间距），不是内容自身高度——用内容自身高度会永远得到 100%，检查随即失效。

下列页面允许大留白：目录、章节过渡、风险提示、免责声明、品牌结束页。

留白必须能由页面角色或**章节边界**解释。若下一页继续**相同章节**的内容流，而当前页仍有大块空白，应判定为分页失败并重新组合内容。章节在此结束、下一页另起章节，属于合法留白。

不要用以下方式假装修复：缩小所有字号、压缩所有行距、拉伸图形、插入无意义色块或重复正文。

### 9. 分离正文与内部审计

默认产出两层：

- 对外报告：结论、正文、图表、必要来源、风险和免责声明。
- 内部审计附件：数据质量明细、机器状态、未生成图表原因、未解决问题和完整证据索引。

若必须合并成一个 PDF，内部附录从新页开始，使用更低视觉权重，并在目录中明确标为附录。不得让内部审计占据整份短报告的三分之一以上而没有用户明确要求。

**对外正文里不得出现“未解决问题”的原始状态码。** 要把它转写成读者可读的风险表述，明细留附录（例：`Agent 4 章节质量门未通过` → “第七章情景与结论尚未通过内部章节质量门，正文一律以条件性表达呈现”）。

### 10. 渲染—复检—修正

必须检查真实渲染结果，而不只检查 HTML/CSS：

1. 运行 `measure_pages.js` 得到逐页几何数据，再运行 `audit_render.py` 得到结构化问题清单。**这一步是强制的**，不是可选建议。
2. 渲染全部页面的低分辨率缩略图，人工检查整本节奏与重复构图（脚本负责几何，人眼负责意图）。
3. 放大检查封面、目录、所有章节起页、图表页、续表页和最后一页。
4. 交叉校验目录/图表目录页码、图表编号、文内引用、来源和实际页位是否一致。
5. 视觉评审只评价页面关系和可读性，不改写金融事实。每个问题记录页码、`bbox`、`issue_code`、`severity`、`confidence`、`evidence`、`fix_action`、`recheck_status`。
6. 最多自动修正两轮；严重问题仍存在时停止正式交付，保留可审查产物和定位信息。

`audit_render.py` 已覆盖的确定性检查（不要再用肉眼重复判断，也不要因为肉眼看着没问题就跳过）：

`PAGE_CONTENT_OVERFLOW`、`FOOTER_COLLISION`、`HEADER_COLLISION`、`ELEMENT_OVERLAP`、`CHART_LABEL_COLLISION`、`MIN_FONT_SIZE`、`CJK_NARROW_WRAP`、`TABLE_EMPTY_CELL`、`CHART_CANVAS_UNDERUSED`、`UNEXPLAINED_WHITESPACE`、`PAGE_NUMBER_MISSING`、`PIPELINE_NAME_IN_CHROME`、`MACHINE_FIELD_IN_BODY`、`PRECISION_OVERFLOW`、`AXIS_TICK_VERBOSE`、`DUPLICATE_TEXT`、`ORPHAN_CONTINUATION_REFERENCE`、`CONTINUED_TABLE_WITHOUT_PRECEDENT`。

## 渲染器必须遵守的版式约束

- 内容区**不要设标称固定高度**（`height: 236mm` 这类）。固定高度只约束盒子、不约束内容，溢出会静默发生并撞到页脚。高度交给内容决定，溢出交给渲染后测量判定。
- 页脚与正文之间要预留物理隔离：页面 `padding-bottom` 应大于页脚高度 + 安全间距，使正文在物理上无法触达页脚。这是对 `FOOTER_COLLISION` 的结构性防治，不要只靠“内容看起来放得下”。
- 分页容器要有稳定选择器，页面要有 `data-role` 与 `data-chapter`，块级元素要有 `data-bid`，与 `render_contract` 声明一致。
- 屏幕预览与打印共用同一份设计 token，打印开启背景色保留并去除不必要阴影。

## 完成标准

只有同时满足以下条件才称为页面编排完成：

- 渲染前文本门复检 `clean=True`（`text_hygiene.py` 退出码 0）；
- 蓝图契约校验 `valid=true`（`validate_page_plan.py` 退出码 0）；
- 渲染后几何审计 `deliverable=true`，即 `critical=0` 且 `major=0`（`audit_render.py` 退出码 0）；
- **体裁一致性达标**（对交付 PDF 逐项核验，方法见 `house-style-benchmark.md` 第 13 节 + 第 14 节）：
  - 基础 15 项（§13）：Type3 字体对象数为 0 且字体基名非空；逐页正文字号众数完全相同；图表题注字号等于正文字号；正文区颜色仅含 `#000000`；强调色数量为 1；图表包框矩形数为 0；各页左边距极差 ≤0.2mm；页脚距页底 ≥12mm；封面为白底且非空文字行数 ≥50；题注单位标注率 100%；单元格重复单位为 0；内部流程语言命中数为 0；
  - 边角细节 6 项（§13 #16–21，详见基准 §13）：图序号统一为 `图表N` 一条序列；段落全篇 left 或 indent 二选一；粗体字符占比 ≥5%（H1/H2 在 PDF span flags 上要带 B flag）；数字小数位全篇统一；长报告目录使用点线引导；长报告（≥30p）跨页表加 `(续)` 标记；
  - **baseline diff 全部通过**（`style_benchmark_audit.py --baseline`，`--baseline` 缺省时 shim 自动指向唯一基线）—— baseline fails = 0 表示本报告所有可量化指标落在 R1–R6 真实样本区间内。任何 baseline fail 都是判定级别的偏差。
- PDF 为 A4 `210×297mm`、页数与分页容器数一致、背景已保留；
- 每页有明确角色和一个主焦点；普通正文页无无法解释的大块空白；
- 中文标题、表头和图表标签无单字竖排或窄列压字；
- 续表有表名、重复表头、稳定列宽和合理尾页，且续页引用成对；
- 图表类型、尺寸和同页组合与比较任务一致；离群值已降级并留痕；
- 图题、图表、来源不拆散且不重复标题；
- 正文、附录、内部审计具有清楚的视觉层级；对外正文无机器字段、内部 ID、生成管线名与超精度数值；
- 封面、内页、图表、表格和结束页属于同一设计系统；
- 目录、图表编号、页码、来源与文内引用一致可用；
- 严重视觉问题为 0，所有页面均已被实际渲染检查，且 `audit.json` 作为可复核产物保留。
