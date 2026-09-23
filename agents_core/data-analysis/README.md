# Data Interpreter Agent

面向 `data-fetcher` 结构化数据集的下游数据解读智能体。它不重新取数，而是对已有事实做指标识别、趋势计算、异常检测、跨来源验证与受证据约束的语义加工，最终交付可直接供内容生成阶段消费的 JSON 报告。

## 架构

```text
data-fetcher/dataset.json
          ↓
输入验收与证据索引（record_id / trace_id / skill_id）
          ↓
确定性分析引擎
  ├─ 关键指标识别与环比/同比变化候选
  ├─ 多期趋势、方向一致率与显式同比/环比信号
  ├─ MAD 稳健离群检测、质量异常与来源冲突
  └─ 同实体/同指标/同期间的跨来源验证
          ↓
分析 SkillHub（自动路由 → 独立并发调用 → 引用校验）
          ↓
语义融合（局部结果去重 → 冲突保留 → 全局摘要）
          ↓
interpretation_report.json
  ├─ executive_summary
  ├─ key_metrics / trends / anomalies
  ├─ cross_validations / insights
  ├─ knowledge_facts（带证据引用的原子知识）
  ├─ content_outline
  └─ evidence_index / data_quality
```

所有语义洞察必须引用输入中存在的 `record_id`。每个被选 Skill 会作为独立分析任务执行并保存局部结果，主智能体随后完成去重和全局融合。模型不能补充外部事实、不能猜测因果，也不能消解上游保留的来源冲突。即使没有配置模型，确定性分析仍可独立运行。

## 项目级分析 Skill

从原始 `skills包` 中筛选并收窄了 16 个方法论 Skill。运行时按研究关注点、实际指标和已填充的数据分区自动路由，默认最多选择 7 个；这些 Skill 只能组织和验证已有证据，不能触发外部取数。

| 项目 Skill | 来源 | 项目内用途 |
| --- | --- | --- |
| `quantitative-validation` | 量化统计方法 | 趋势、异常、样本量和统计限制校验，始终启用 |
| `financial-statement-analysis` | 财务报表深度解读 | 三表勾稽、盈利质量、运营与财务风险候选 |
| `industry-chain-analysis` | 产业链解读 | 上中下游、价值分配、关键节点和风险传导 |
| `competitive-landscape-analysis` | 竞争格局分析 | 可比口径、龙头依据、规模与增长对比 |
| `industry-overview-analysis` | 行业概览 | 行业知识骨架、参与者、趋势与风险 |
| `macro-cycle-analysis` | 宏观周期分析 | 增长、通胀、流动性与政策信号组合 |

按需专题层只在关注点或数据指标命中时加载：

| 项目 Skill | 来源 | 触发用途 |
| --- | --- | --- |
| `company-event-analysis` | 公司事件驱动分析 | 并购、回购、增减持、监管等事件时间线 |
| `earnings-expectation-analysis` | 盈利预测与一致预期分析 | 预测、实际业绩、预期差与修正趋势 |
| `valuation-context-analysis` | 估值模型方法论 | 历史及同业估值语境、多方法一致性 |
| `correlation-analysis` | 相关性与协整分析 | 多序列联动、滚动相关与稳定性 |
| `market-sentiment-analysis` | 市场情绪分析 | 行情、资金、期权与文本情绪交叉验证 |
| `fundamental-factor-analysis` | 基本面因子筛选 | 价值、成长、质量因子横截面对比 |
| `risk-stress-analysis` | 风险分析与压力测试 | 回撤、尾部风险与压力情景 |
| `financial-forensics-analysis` | 上市公司财报体检 | 单公司财务红旗与法证检查 |
| `sector-rotation-analysis` | 行业轮动分析 | 多行业景气、盈利、估值和动量比较 |
| `esg-risk-analysis` | 环境社会治理投资筛选 | ESG 指标、评级分歧和争议事件 |

没有引入“业绩归因分析”，因为其核心是投资组合相对基准收益拆解。原 Skill 中重新取数、制作演示文稿、资产配置或买卖建议等超出本智能体边界的步骤也未迁入；“上市公司财报体检”仅作为命中法证财务需求时启用的专题补充，避免与通用三表分析重复常驻。

## 安装

需要 Python 3.11 或更高版本：

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

如需语义深化，配置与 `data-fetcher` 相同的环境变量：

- `LLM_API_KEY`（也支持 `DEEPSEEK_API_KEY`）
- `LLM_BASE_URL`
- `LLM_MODEL`

## 命令行

```bash
.venv/bin/data-interpreter \
  ../data-fetcher/output/runs/<run_id>/dataset.json \
  --subject "新能源汽车" \
  --focus "产业链" \
  --focus "龙头财务"
```

离线确定性分析：

```bash
.venv/bin/data-interpreter dataset.json --subject "新能源汽车" --deterministic-only
```

运行产物：

```text
output/runs/<analysis_id>/
├── request.json
├── input_dataset.json
├── events.jsonl
├── skills/<skill_task_id>.json
└── interpretation_report.json
```

库接口：

```python
import json
from data_interpreter import AnalysisRequest, DataInterpreterAgent, StructuredResearchDataset

dataset = StructuredResearchDataset.model_validate(json.load(open("dataset.json")))
report = await DataInterpreterAgent().run(
    dataset,
    AnalysisRequest(subject="新能源汽车", focus_points=["产业链", "龙头财务"]),
)
```

Skill 的来源、适用数据分区和收窄说明由包内 `data_interpreter/skills/` 管理，最终报告的 `applied_skills` 会记录本次实际采用的方法论。

## 验证

```bash
python -m pytest -q
python -m compileall -q data_interpreter
```
