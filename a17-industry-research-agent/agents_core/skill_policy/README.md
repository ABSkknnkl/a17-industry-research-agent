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
2. **用户显式选择的技能** —— 兼容旧中文标签，解析为阶段内已注册 ID，保留用户顺序
3. **模型选中的技能** —— 保持模型给出的顺序
4. **确定性路由补充的技能** —— 追加在末尾

按技能名去重；`limit` 优先裁剪自动选择项，并记录被截断项。强制规范与用户显式项不会因预算静默消失，必要时实际数量超过默认上限。

## 用法

```python
from skill_policy import merge_selection
from skill_policy.requests import resolve_requested_skills

policy_skills = skillhub.select(request, dataset)     # 确定性路由结果
explicit_skills, unavailable = resolve_requested_skills(request.selected_skills, skillhub.catalog)
model_skills = await self._plan_skills(...)           # 模型规划结果

merged = merge_selection(model_skills, policy_skills, requested_skills=explicit_skills, limit=10)
selected = merged.final                               # 并集后的技能列表
```

各层的技能对象类型不同（`AnalysisSkill` / `WritingSkill` / `FusionSkill` / `ChartSkill`），
但都有 `name` 与 `always` 字段，因此可直接传入。若某层字段名不同，用 `name_of` /
`is_always` 传入自定义取值函数即可（见 `tests/test_merge_selection.py`）。

## provenance：不是调试信息，是可观测数据

合并结果会标注每个技能的来源（`model` / `policy` / `both` / `user`），并单列
`added_by_policy`（最终保留、模型漏选且非用户显式指定的规则补充项；被预算裁掉的不算补入）。

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

## 2026-11-02 调用契约

- 分析和写作请求以 `selected_skills` 结构化传入选择；旧中文选项通过 `requests.py` 解析为真实技能 ID，不再把名字拼成一段“已挂载”提示。未知或本阶段无对应项会记录原因。
- 分析层的条件技能信号同时约束模型选择、规则补入及无模型回退；用户显式选择可覆盖信号要求，但仍须经过原有数据、事实和交付校验。
- 写作层按 `_meta.json` 的 `chapters` 加载适用规范，所有该章规则已被确定性路由覆盖，因此省略冗余的逐章模型选技；实际章节生成仍由模型与原有审校流程负责。当前章节规则全量策略保留；未来若技能库扩张为大量可选规则，需要再设计候选预算，不能直接恢复无范围的模型选择。
- `skill_requested`、`skill_loaded`、`skill_skipped`、`skill_failed` 和 `skill_completed` 区分选择、加载和真实执行结果。批量响应必须按完整 skill ID 给出独立、非空结果；缺失结果不能冒充成功，也不复制一份通用响应给多个技能。批量模式仍默认关闭。
- 本模块不会自动执行 `skills包/` 下任意脚本；该目录是方法论资料来源，运行中使用的是各智能体已适配并注册的技能。

官方参考：[Agent Skills 客户端集成](https://agentskills.io/client-implementation/adding-skills-support)强调先披露目录、激活时加载指令、资源按需读取；[技能编写与评估建议](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)建议以代表任务建立评估，再迭代指令。本轮聚焦选择与执行链路，没有重写整个资料库或新增技能框架。
