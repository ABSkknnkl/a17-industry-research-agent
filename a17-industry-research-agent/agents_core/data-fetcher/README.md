# Data Fetcher Agent Foundation

数据获取智能体：通过问财 SkillHub 和可配置的产业链研究路径组织数据、来源与告警。结果仍需核验，不保证数据完整或正确。

## 架构

```text
行业 + 关注点 + 数据要求
          ↓
数据获取 Agent（理解 → 研究要求拆解 → 观察 → 规划）
          ↓
SkillHub（路由 → DAG 编排 → 并发 → 重试）
          ↓
同花顺问财 SkillHub
          ↓
数据融合（统一 → 去重 → 时间/实体对齐 → 冲突保留）
          ↓
结构化研究数据集
```

LLM 可参与研究目标和任务规划；结构化结果按实际数据源和确定性融合逻辑处理。产业链路径还可能使用配置的搜索及原文来源。Agent 不再以“分区非空”作为完成条件，而是用确定性代码逐项验收研究要求、实体、指标、期间和来源。

对于“龙头财务”类关注点，Agent 会先获取候选公司及总市值、营业收入、市场份额或行业排名等客观依据，对候选排序后才允许规划财务查询。核心行业查询失败不能再由板块或指数记录掩盖；失败任务及仍未满足的要求会进入下一轮规划上下文。

## 内置 Skill

项目内部分 Skill 的独立 CLI 脚本位于工作区同级的 `skills包/<技能名>/scripts/`；Skill 文档中的相对示例以对应 Skill 目录为工作目录。项目后端通过 SkillHub 接口执行，不要求手动运行这些脚本；单独复制项目时需确认是否同时带上共享技能包。

项目根目录的 `skills/` 保留了旧项目中现成的问财技能资源。SkillHub 启动时扫描各目录的 `SKILL.md`，从中发现真实技能，不再依赖一份脱离文件的静态清单。

- 技能从当前目录的 `SKILL.md` 发现；实际可调用能力取决于配置与运行环境。
- 从 `skills包` 筛选并收窄了 3 个规划类 Skill：`industry-research-requirements`、`financial-data-quality`、`research-event-calendar`。它们只参与需求拆解和查询规划，不作为数据源。
- `产业链解读`、`竞争格局分析` 为参考资料，不直接伪装成远程 API。
- `akshare-research-data` 未迁入，避免突破“仅问财 SkillHub”的数据边界。

未直接引入原包中的股票研究、宏观利率监控和公司事件驱动分析：这些原始文档包含交易判断或依赖其他 MCP，与当时的数据获取边界冲突；当前产业链研究可按配置使用其他搜索和原文来源。

| Agent 能力名 | 问财 Skill ID | 数据分区 |
| --- | --- | --- |
| `industry_data` | `hithink-industry-query` | industry |
| `financial_data` | `hithink-finance-query` | financials |
| `macro_data` | `hithink-macro-query` | macro |
| `industry_chain` | `hithink-business-query` | industry_chain |
| `report_search` | `report-search` | reports |
| `news_search` | `news-search` | news |
| `company_basic_info` | `hithink-basicinfo-query` | companies |

问财技能是主要取数路径；产业链支持 legacy 和可选的 evidence_v2 路径，可选搜索的可用性依赖配置。

## 安装与配置

需要 Python 3.11 或更高版本。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

程序只读取环境变量，不会读取或写回 `.env`。启动前需将 `.env` 中的值导入当前终端，至少配置：

- `IWENCAI_API_KEY`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

## 使用

```bash
.venv/bin/data-fetcher \
  --industry "低空经济" \
  --focus "产业链" \
  --focus "龙头财务" \
  --require "客观数据及来源" \
  --as-of 2026-09-14
```

独立请求模型默认最多 6 轮、24 个 Skill 任务、600 秒；集成工作流可能覆盖这些值。运行产物写入：

```text
output/runs/<run_id>/
├── request.json
├── events.jsonl
├── raw/<task_id>.json
├── dataset.json
└── result.json
```

库接口：

```python
from data_fetcher import DataFetcherAgent, ResearchRequest

result = await DataFetcherAgent().run(
    ResearchRequest(
        industry="低空经济",
        focus_points=["产业链", "龙头财务"],
        data_requirements=["客观数据及来源"],
    )
)
```

## 验证

```bash
python -m pytest -q
python -m compileall -q data_fetcher
```

项目默认测试排除 `live`；单包运行和其他标记的测试仍应检查其外部依赖及配置。
