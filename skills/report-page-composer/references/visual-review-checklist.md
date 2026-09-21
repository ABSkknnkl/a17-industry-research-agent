# 渲染后视觉复检清单

复检分两层：**确定性几何审计**（脚本做，可复现、可门禁）与**人眼节奏评审**（人做，判断意图）。不要用肉眼替代脚本，也不要因为脚本通过就跳过肉眼看整本。

## 第 0 步：先跑确定性审计

```bash
playwright-cli run-code --filename scripts/measure_pages.js --raw > metrics.json
python3 scripts/audit_render.py metrics.json \
        --plan page_composition_plan.json --out audit.json
```

退出码 `0` 表示 `critical=0` 且 `major=0`，才允许进入人眼评审。`audit.json` 是可复核产物，必须与 PDF 一同保留。

### 已覆盖的确定性检查项

不要再用肉眼重复判断下列问题；也不要因为肉眼看着“还行”就跳过程序检查。

| issue_code | 判据 | 默认严重度 |
|---|---|---|
| `PAGE_CONTENT_OVERFLOW` | 内容底边 > 安全版心下沿（页脚顶边 − 安全间距） | critical |
| `FOOTER_COLLISION` | 任一文本元素底边越过页脚安全线 | critical |
| `HEADER_COLLISION` | 任一非表格元素顶边进入页眉安全区 | critical |
| `ELEMENT_OVERLAP` | 两个非嵌套文本元素重叠面积 ≥ 18px² 且两向重叠 ≥ 3px | major |
| `CHART_LABEL_COLLISION` | 同一 SVG 内两个 `text` 重叠 | major |
| `MIN_FONT_SIZE` | 最终字号 < 9px（≈6.8pt）；< 7px 升为 critical | major |
| `CJK_NARROW_WRAP` | 中文标签内容宽 ÷ 字号 < 5 字，且折成 ≥ 3 行 | major |
| `TABLE_EMPTY_CELL` | 对外正文的非合并单元格内容为空 | major |
| `CHART_CANVAS_UNDERUSED` | 绘图区面积 ÷ 容器面积 < 0.42 | major |
| `UNEXPLAINED_WHITESPACE` | 有效内容占安全版心 < 65%，且下一页继续**同章节**内容流 | major |
| `PAGE_NUMBER_MISSING` | 非封面/结束页的页脚无“当前页/总页数” | minor |
| `PIPELINE_NAME_IN_CHROME` | 页眉页脚出现 skill 名/管线名/agent 名/内部 ID | major |
| `MACHINE_FIELD_IN_BODY` | 对外阅读层出现机器字段、状态码、证据/计算 ID | major |
| `PRECISION_OVERFLOW` | 正文出现 9 位以上金额、3 位以上小数百分比、5 位以上小数 | major |
| `AXIS_TICK_VERBOSE` | 图内刻度用千分位小数百分比 | minor |
| `DUPLICATE_TEXT` | 相邻页内长段落归一后相似度 ≥ 0.90 | major |
| `ORPHAN_CONTINUATION_REFERENCE` | 本页写“续页见下页”，下一页无“（续）”表题 | critical |
| `CONTINUED_TABLE_WITHOUT_PRECEDENT` | 本页有“（续）”表题，上一页无同号原表 | major |

排期与阈值定义在 `scripts/audit_render.py` 顶部；调整阈值时同步更新本表。

## 整本缩略图（人眼）

- 封面风格是否延续到内页？
- 普通正文页是否重复同一构图超过三页？
- 是否出现上半页拥挤、下半页空白，而下一页继续同一章节？
- 章节起页、图表页、表格页、附录页能否一眼区分？
- 对外正文与内部审计的页数比例是否合理？
- 最后一页是否具有明确结束感？
- 目录、图表目录、页码和文内引用是否真实可用？
- 同一结论、来源、置信度或机器说明是否反复出现？

## 单页（人眼）

- 页面是否只有一个主焦点？
- 一级章节是否在页中与其他一级章节竞争？
- 标题是否孤悬在页底？
- 图题、图表、来源是否作为整体出现？
- 同组图是否共享基线、绘图区、坐标与图例？
- 页码跳转与表号/图号是否与目次一致？
- 空状态是否被大面积卡片放大，而不是紧凑合并？
- 数字列是否右对齐、小数与单位统一，长 URL/机器字段是否挤压核心表格？
- 色彩的语义是否稳定（同一语义跨页同色），红绿是否与中国市场习惯一致？
- 表格里内容完全相同的连续行是否已归并？

## 严重度

- `critical`：裁切、遮挡、缺页、内容丢失、错误页序、页脚被正文压住、续页引用落空。
- `major`：单字竖排/窄列压字、裸续表、图题与图拆散、不可读字号、普通页大面积异常空白、多个一级章节争抢焦点、图形编码明显不适合阅读任务、正文出现机器字段或超精度数值、图表标签碰撞、绘图区利用率过低。
- `minor`：轻微对齐、间距、色彩、局部密度或装饰问题。
- `suggestion`：不影响阅读的审美偏好。

正式交付要求 `critical=0`、`major=0`。只由单一视觉模型提出且无法通过页面截图或几何数据验证的主观意见，不自动阻断。

## 输出格式

评审输出不使用一个笼统美观分。每个问题必须包含 `page`、`bbox`、`issue_code`、`severity`、`confidence`、`evidence`、`fix_action`、`recheck_status`；整本另记录结构节奏、图表系统、文字密度和出版一致性。

`audit_render.py` 已按此结构输出。人眼补充的问题用同一结构手工追加到同一份 `audit.json`，便于统计与复检。
