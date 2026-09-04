# Agent 1 意图路由修复 P0 验收总结报告

- 关联方案：[2026-08-31-agent1-routing-fix.md](2026-08-31-agent1-routing-fix.md)

- 验收日期：2026-09-01（北京时间）

- 验收范围：P0（本周，纯代码）——修拆解与查询构造

- 验收方式：真 LLM（`deepseek-v4-flash`）+ 真 SkillHub 端到端回归 + 单元/集成全量回归

- 结论：**P0 全部交付通过，达成方案 P0 验收总标准**

***

## 1. 一句话结论

P0 修复落地后，光伏组件原始任务**待澄清从 9 条降到 2 条**（目标 ≤2），剩余 2 条均为 SkillHub 真实返回缺口的 `user_metric`（出货量、产能利用率），**不属成因 C 类可解析问题**；泛称实体"主要企业"成功展开为具体公司名单；路由遥测四类事件完整落盘且全部可关联 `run_id`；全量测试（439 个用例）不红。

约束遵守：**未新增技能、未接联网搜索、未训练路由模型**，仅按方案做 P0 五项交付。

***

## 2. P0 各子项交付核对

### 2.1 P0-1 裸实体继承兄弟碎片指标（治成因 A）

- **改动**

  - `intent_merger.py` 新增 `_inherit_metrics_from_siblings`：裸实体碎片（有实体、无指标）继承同问题兄弟碎片的指标与候选技能；

  - 能力校验拦截：继承技能必须同时匹配指标类型与实体类型（如 INDUSTRY 实体不能继承 FINANCE 技能）；

  - 无兄弟可继承时保持原样走澄清门，不静默吞掉。

- **验收**：多实体对比问题"隆基绿能、晶科能源、天合光能组件出货量与市场份额对比？"拆解后全部实体获得技能，"XX 暂无对应查询技能"不再出现。

- **测试**：`test_p01_*` 4 个用例通过。

### 2.2 P0-2 分析型碎片识别（治成因 B）

- **改动**

  - `intent_models.py`、`semantic_router.py` 的 `intent_type` 新增 `analysis_only` 枚举，两处 schema 同步；

  - `intent_merger.py` 新增 `_is_analysis_directive`：识别"X 对 Y 的影响/传导/关系/贡献"，将其移出取数子需求、写入 `analysis_notes` 透传下游，不再报"暂无对应查询技能"；

  - 已被路由的碎片即使命中分析正则也保守放行。

- **验收**："碳酸锂价格对组件成本的影响"分析诉求不再进数据路由。

- **测试**：`test_p02_*` 3 个用例通过。

### 2.3 P0-3 泛称实体解析（治成因 C）

- **改动**

  - `planner.py` 新增 `_resolve_generic_entities` + `_NON_COMPANY_ENTITY_TYPES`：泛称（"主要企业/龙头/头部公司"）优先用已知具体公司（brief + 意图抽取，二者任一命中即成功），其次经 `hithink_sector_selector` 取板块成分；皆空标记 `entity_resolution_failed` 走澄清门；

  - 解析结果随 `RetrievalPlan.resolved_entities` 留痕，实际查询绑定展开后的具体公司；

  - `service.py` `_mark_entity_resolution_failures` 与 planner 两层判定保持一致（同一已知公司池），修复了行业实体混入泛称解析的 bug。

- **验收**："主要企业"→ `[隆基绿能， 晶科能源， 天合光能]`（来源 known\_entities），查询构造为具体公司。

- **测试**：`test_p03_*` 8 个用例通过。

### 2.4 P0-4 指标别名扩充

- **改动**：`metric_registry.py` 新增"出货量/产能/产能利用率/市场份额"4 族 MetricSpec 及别名扩充。

- **验收**：`get_metric_spec("出货量").primary_skill is BUSINESS`；`_metric_type("出货量")` 不再返回 `"unknown"`；`_METRIC_TYPE_KEYWORDS` 与注册表对齐，消除两处词表漂移。

- **测试**：`test_p04_*` 4 个用例通过。

### 2.5 P0-5 路由观测埋点（P1 的前提）

- **改动**

  - 新增 `routing_telemetry.py`：JSONL 追加至 `artifacts/routing_telemetry/YYYYMMDD.jsonl`，默认只落文本 SHA-256 前缀，`ROUTING_TELEMETRY_RAW_TEXT=true` 才落原文；任何 IO/序列化失败静默吞掉；

  - 4 个点位接线：decomposition（拆解出口）、route\_decision（路由决策，新增 `layer` 字段区分 `deterministic`/`semantic`）、skill\_call（executor 收口）、clarification（澄清门 / 数据缺口门 / unsupported-metrics 回流）；

  - 补录了 `required_data_unavailable` 路径缺失的 clarification 事件；为确定性路由（P0-4 后主链路指标多走此层）补上点位 2 观测，保证 miss 分析可见。

- **验收**：光伏任务重跑后 4 类记录齐全且每条可关联 `run_id`。

- **测试**：`test_p05_*` 6 个用例通过。

***

## 3. 端到端验收数据（真 LLM + 真 SkillHub）

运行配置：`LLM_MODEL=deepseek-v4-flash`、`LLM_USE_MOCK=False`、`SKILLHUB_USE_MOCK=False`、语义路由开启、拆解器开启。

| 验收项       | 基线与目标               | 实测结果                                                                                                                                       | 判定    |
| --------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ----- |
| 待澄清条数     | 基线 9，目标 ≤2          | **2**                                                                                                                                      | ✅     |
| 剩余待澄清归属   | 应为成因 C 之外的真数据缺口     | `REQ-05 出货量`、`REQ-06 产能利用率`（`user_metric`，SkillHub 实查无数据；`unsupported_metrics` 为空，非泛称解析失败）                                                 | ✅     |
| P0-3 泛称解析 | "主要企业"展开 ≥3 个具体公司   | `隆基绿能 / 晶科能源 / 天合光能`（source=known\_entities）                                                                                               | ✅     |
| P0-5 四类遥测 | 4 类记录完整、关联 `run_id` | `decomposition=14`、`route_decision=5`（全部 `layer=deterministic`）、`skill_call=84`、`clarification=5`，共 108 条，全部 `run_id=run-p0-acceptance-pv` | ✅     |
| 证据与覆盖率    | —                   | 149 条证据；`supported=7`，`missing=2`                                                                                                          | 已披露缺口 |
| 阶段收口      | —                   | `waiting_review` / `required_data_unavailable` + 决策门（已取数据保留，交由用户裁决）                                                                        | ✅     |

验收结果工件：`artifacts/probe_p0_e2e_result.json`；遥测日志：`artifacts/routing_telemetry/20260831.jsonl`。

> 说明：阶段以 `required_data_unavailable` 收口属**预期行为**——用户裁决门在真数据缺口处停下、不补造数值、保留已取数据，由用户决定"确认风险并继续"或"修改后重查"，且缺口必须披露。

***

## 4. 测试与回归

| 测试集                                                      | 结果                    |
| -------------------------------------------------------- | --------------------- |
| P0 专项 `tests/agents/data_fetcher/test_p0_routing_fix.py` | **25/25 通过**          |
| 全量 `tests/agents` + `tests/integrations`                 | **439 个用例，exit 0 全绿** |

验收完成后已按方案要求清理探针脚本 `probe_p0_e2e.py`。

***

## 5. 遗留事项与 P1 前瞻

- **P0 遗留（非阻断）**：2 条 `user_metric`（出货量、产能利用率）真数据缺口需在报告"研究边界"披露，不能补造。

- **P1 触发**：本方案 §4——P0-5 已起跑埋点，需\*\*积累 ≥2 周真实路由日志（或 ≥500 条有效记录）\*\*后立项：离线评测 harness（分层准确率 / 错配率 / miss 率 / 混淆矩阵）、并行仲裁层、词表外置、分技能阈值校准、澄清门分级文案。

- **暂时不做（红线）**：模型训练、联网搜索插件。按 §5 决策树，P1 数据未达标才评估训练，且训练管线是长期负债，当前不启动。

***

## 6. 变更文件清单（P0）

| 文件                                                         | 改动                                                                                   |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `backend/app/agents/data_fetcher/intent_merger.py`         | `_inherit_metrics_from_siblings`、`_is_analysis_directive`、`_METRIC_TYPE_KEYWORDS` 对齐 |
| `backend/app/agents/data_fetcher/semantic_router.py`       | `intent_type` 增 `analysis_only`、`_DECOMPOSER_SYSTEM_PROMPT` 拆解规则 5/6                 |
| `backend/app/agents/data_fetcher/intent_models.py`         | `intent_type` 枚举增 `analysis_only`                                                    |
| `backend/app/agents/data_fetcher/metric_registry.py`       | 4 族 MetricSpec + 别名扩充                                                                |
| `backend/app/agents/data_fetcher/planner.py`               | `_resolve_generic_entities`、`_NON_COMPANY_ENTITY_TYPES`、`resolved_entities` 留痕       |
| `backend/app/agents/data_fetcher/service.py`               | 泛称解析接线、`_mark_entity_resolution_failures`、遥测 4 点位（含补录）                               |
| `backend/app/agents/data_fetcher/routing_telemetry.py`     | 新增：4 类 JSONL 埋点                                                                      |
| `backend/tests/agents/data_fetcher/test_p0_routing_fix.py` | 新增：P0-1\~P0-5 共 25 个用例                                                               |

