---
name: report-html-composer
description: Compose a professional, evidence-traceable industry research report as browser-first HTML. Use for Agent 5 report layout, narrative-led or chart-led composition, responsive Chinese typography, source indexing, and final HTML quality gates. Never use it to invent or rewrite financial facts.
---

# Report HTML Composer

把 HTML 当作报告主产品。这个 Skill 提供的是设计判断框架，不是要求模型把内容硬塞进一张固定模板。

## 工作方式

1. 先读 [core-contract.md](references/core-contract.md)，锁定不可改变的事实、结构和证据边界。
2. 根据内容选择一种主方向：少图、长文、结构化对照为主时读 [narrative-led.md](references/narrative-led.md)；多图、趋势、波动和比较为主时读 [chart-led.md](references/chart-led.md)。
3. 读 [component-grammar.md](references/component-grammar.md)，为每个小节选择构图，不按章节套同一张版。
4. 读 [evidence-center.md](references/evidence-center.md)，建立正文引用与完整来源索引。
5. 生成后按 [quality-gate.md](references/quality-gate.md) 做结构、响应式和浏览器检查。

运行时必须加载 [design-brief.json](references/design-brief.json) 与 [layout-catalog.json](references/layout-catalog.json)。前者交给编辑模型做判断，后者约束可执行布局与安全阈值；后端不得维护另一份复制规则。

## 不可突破的边界

- 不新增、改写、删除、合并或推断金融事实、数字、结论、引用和不确定性。
- 不为了填版重复文字、截断正文、伪造图表或隐藏缺失信息。
- 不随机换色或随机左右翻转来冒充多样性；变化必须来自内容结构。
- 单数据点只能是指标卡或正文重点，不得画成柱、线、饼图。
- 中文保持横排；窄屏必须回退单栏。
- 当前交付目标只验收 HTML。PDF/Markdown 不得反向限制 HTML 构图。

## 输出

HTML 内嵌 `html-composition-plan`，记录报告方向、Skill 指纹、每个小节的稳定公开键、构图、阅读顺序、内容宽度、输入规模、决策来源和理由。`section_key` 只是确定性的公开连接键，不是匿名化或安全哈希。

报告级 `report_mode` 不是装饰标签：图表达到数据密集阈值时必须采用 `chart_led`，并让有图小节的主要构图真实包含图表；文字型报告则保持舒适行长。章级样式只控制章节语义与装饰，不得把小节构图改写成另一套 DOM。所有非压缩小节必须共用 `html-section-body / html-section-copy / html-section-visual` 骨架。

用以下命令做轻量校验：

```bash
python3 skills/report-html-composer/scripts/validate_html_plan.py
python3 skills/report-html-composer/scripts/validate_html_plan.py path/to/html_composition_plan.json
```

合成实验脚本只代表确定性参考计划，必须标记 `decision_source=deterministic`；只有真实调用编辑模型并通过校验的结果才能标记为 `model`。

实现接入点见 [project-integration.md](references/project-integration.md)，资料取舍见 [provenance.md](references/provenance.md)。
