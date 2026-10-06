# skill_policy：技能选择的并集融合器

## 这个模块解决什么问题

五个智能体各自有一份**确定性技能路由**（`skillhub.select`），它依据技能 `_meta.json` 里的
`domains` / `keywords` / `chapters` / `always` 等元数据打分，好处是**该用的技能不会漏**。

大模型的**自主规划**则能发现规则没覆盖到的场景——比如某份数据里出现了冷门分析视角，
它可能选择了一个关键词匹配不到、但确实合适的技能。

改造之前，两者的关系是**互斥替代**：

```
LLM 可用  → 用 LLM 选的技能（失败才回落到规则）
LLM 不可用 → 用规则选的技能
```

这等于每次运行都丢掉另一半信息：模型漏选的技能没人补，规则识别得出但模型没想到的组合也进不来。

本模块把两者合并为**并集**：模型选的保留，规则认为该有的补齐。

## 合并优先级

1. **强制技能**（`always=True`）—— 无论来自哪一侧都必留，且在截断时优先保留
2. **模型选中的技能** —— 保持模型给出的顺序
3. **确定性路由补充的技能** —— 追加在末尾

按技能名去重；超过 `limit` 时从末尾截断，被截断的名称记录在结果里。

## 用法

```python
from skill_policy import merge_selection

policy_skills = skillhub.select(request, dataset)     # 确定性路由结果
model_skills = await self._plan_skills(...)           # 模型规划结果

merged = merge_selection(model_skills, policy_skills, limit=10)
selected = merged.final                               # 并集后的技能列表
```

各层的技能对象类型不同（`AnalysisSkill` / `WritingSkill` / `FusionSkill` / `ChartSkill`），
但都有 `name` 与 `always` 字段，因此可直接传入。若某层字段名不同，用 `name_of` /
`is_always` 传入自定义取值函数即可（见 `tests/test_merge_selection.py`）。

## provenance：不是调试信息，是可观测数据

合并结果会标注每个技能的来源（`model` / `policy` / `both`），并单列
`added_by_policy`（模型漏选、被规则补上的技能）。

一轮真实运行下来可以统计：
- 模型漏选率有多高（`rescued_count` 与总数的比值）
- 哪些技能反复被规则补上 —— 这些正是提示词需要补充说明的候选

这比"感觉模型选得还行"要可操作得多。

## 补入准入：不是所有规则技能都值得补

实测发现的问题：某次运行用户只问了「动力电池行业近5年市场规模、增速」，规则却补进了
`esg-risk-analysis`（ESG 风险）—— 因为判定信号时是在**全部数据文本**里搜关键词，
而动力电池行业的新闻里出现"环境""治理"是常事，于是被误判成"有 ESG 信号"。

结果是这个技能白跑：它产出了内容，但最终没有进入报告正文。

因此补入前增加一道**准入裁剪**，分两类处理：

| 类别 | 判定方式 | 例子 |
|---|---|---|
| **通用技能** | `always=True`、显式登记在 `UNIVERSAL_SKILL_NAMES`、或 `requires_signal` 为假 → 无条件补入 | 财报分析、估值与基本面对比、量化校验、竞争格局、产业链 |
| **条件技能** | `requires_signal=True` → **仅当用户意图里出现其触发信号时**才补入 | ESG 风险（需提到 ESG/环境/治理/碳排放/可持续）、地缘风险（需提到关税/制裁/出口管制/国产替代） |

判定用的意图文本是 **用户输入**（主题 + 关注点），而**不是数据全文** —— 这是本次修正的关键。

实测效果（解读层 20 个技能）：

| 意图 | 准入 | 裁掉 |
|---|---|---|
| 「动力电池行业近5年市场规模、增速」 | 7 | 13（含 ESG） |
| 「动力电池行业的ESG治理与碳排放情况」 | 8 | 12（ESG **准入**） |

**配置入口**（在本模块顶部）：

```python
UNIVERSAL_SKILL_NAMES = frozenset({
    "financial-statement-analysis",   # 财报分析：所有研报都要看财务
    "tech-hype-vs-fundamentals",      # 估值与基本面对比
    "quantitative-validation",        # 量化校验
})

CONDITIONAL_EXTRA_SIGNALS = {
    "esg-risk-analysis": ("ESG", "环境", "社会责任", "治理", "碳", "排放", "能耗", "可持续", "绿色"),
    "geopolitical-risk-analysis": ("地缘", "关税", "制裁", "出口管制", "脱钩", "供应链", "国产替代", "贸易战", "出海"),
}
```

要点：
- 显式通用清单里的技能**即便 `requires_signal` 为真也照常补入**（如财报分析本身带信号门槛）；
- 未在 `CONDITIONAL_EXTRA_SIGNALS` 登记的条件技能，只用其自身 `_meta.json` 的 `keywords` 判定；
- **不传 `intent_text` 时不裁剪**，行为与加此功能前完全一致（向后兼容，不会误杀）。

## 已接入的位置

| 层 | 文件 | 说明 |
|---|---|---|
| 数据解读 | `data-analysis/data_interpreter/agent.py` | `_plan_skills` 内合并 |
| 章节写作 | `chapter-writer/chapter_writer/agent.py` | `_plan_chapter_skills` 内合并 |
| 报告融合 | `report-fusion/report_fusion/agent.py` | `_plan_editorial_skills` 内合并 |
| 图表生成 | `chart-generator/chart_generator/agent.py` | 成功路径内联合并（该层技能形态是 dict 列表，故未走统一融合器） |

**数据获取层不适用**：它的 `skillhub.py` 是**技能执行器**（执行模型规划出的查询任务），
本身不做技能选择，因此不存在"两套选择需要合并"的问题。

## 运行依赖

模块位于 `agents_core/skill_policy/`，需要 `agents_core` 在导入路径上：

- 后端运行：`backend/app/core/setup_env.py` 已注入
- pytest：根 `pytest.ini` 的 `pythonpath` 已包含 `agents_core`
- 单包独立运行：各 agent 文件内有路径回推兜底（捕获 `ModuleNotFoundError` 后按包位置补路径）

> 注意：各包的 `pyproject.toml` 里有自己的 `[tool.pytest.ini_options]`，
> 单包跑测试时 pytest 会以该文件为 rootdir，根 `pytest.ini` 的 `pythonpath` 不生效——
> 这正是需要导入兜底的原因。
