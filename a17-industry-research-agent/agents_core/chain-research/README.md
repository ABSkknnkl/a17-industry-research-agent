# chain-research（产业链研究共享包 v2）

A1 产业链研究作业的共享契约与实现，按《产业链图AI可执行最终实施方案_20261030.md》建设。

## 职责边界

- **A1 是产业链信息责任主体**；本包为其研究作业提供模型、存储、provider 与服务。
- 本包**不导入** A2/A3 业务 Agent；下游通过 `ChainKnowledgeBundle`（版本化 JSON）交接。
- 首版技术栈：Pydantic + JSON 快照 + SQLite + 文件缓存。不引入图数据库/微调/GraphRAG。

## 模块

| 模块 | 职责 | 状态 |
|---|---|---|
| `models.py` | 共享模型、谓词词表、引用及状态校验 | T1 |
| `store.py` | SQLite 索引、JSON 快照、文档哈希、revision 与原子落盘 | T2 |
| `providers.py` | 豆包/原文/KB 适配、run 级预算、来源与丢弃诊断 | T3 |
| `service.py` | 动态结构、关系抽取、独立原文核验、候选与已支持关系 | 已接真实链路，完整性仍待金标准验收 |
| `project.py` | 项目现有 LLM 与豆包传输的边界适配 | 不修改持久凭证，不切换备用模型 |
| `view.py` | 只读 SVG 投影与原文证据审阅 HTML | partial 输出；不使用旧企业补录/搬移规则 |

当前工作流通过适配层在相应阶段使用本包；创建任务前设置 `CHAIN_ENGINE=evidence_v2` 可选择 v2。历史交接中提到的 `scratch/run_chain_v2_a123.py` 不在本工作区，不能直接运行。
`scripts/evaluate_chain_v2.py <bundle.json> --write-report` 只核查证据与基本门禁，
不把未做人工标注的精确率或结构召回率伪装成通过。

当前为可运行的生产切片，不代表 T9 或未知行业认证完成；未获支持的关系保留未决，
结构完整性未认证。未来计划、二手报道和公司类别不能自动成为当前已验企业事实。

## 测试

```bash
# 从项目根目录运行
.venv/bin/python -m pytest agents_core/chain-research -q
```

## 比赛版策略与画像

2026-10-30 比赛版修改采用 schema 2.1；旧 2.0 bundle 可按新增字段默认值读取，不重写历史原文。
`profiles.py` 只按规范主题、视图类型与粒度精确匹配，`profile_data/` 为本包新版画像的唯一来源。
目前新增笔记本、白酒两份 **draft 画像**：结构与产品映射已整理，但没有声称经过原始资料或人工审定；
不包含无证据的代表企业名单。旧 chart-generator 画像目录仍服务 legacy 引擎，本次不改写其历史行为。

`membership.py` 对已获支持的产品事实执行产品类别、应用范围、组织角色政策；
accepted/rejected/unknown 与原始断言状态分开。直接模型参与断言不能绕过画像准入，
内建工艺和场景卡不强填企业。`identity.py` 只合并支持原文中明确的中英文括注别名，不猜集团和子公司。
`document_text.py` 提取正文并选择相关段落。`view.py` 编译产品／工艺／场景卡及独立证据详情。

API 请求保存在 `input_data.data_fetch_options`：

```json
{"chain_research_strategy":"profile_guided","chain_profile_id":"notebook"}
```

不提供 profile ID 时自动匹配；`explore` 不加载专属画像。策略会由工作流传到 A1，
实际匹配策略、画像 ID／版本写 manifest，完整画像写 bundle。运行时仍需选择 `CHAIN_ENGINE=evidence_v2`。
新增 `view_model.json` 随 A3 产物保存。增量复核会重新计算归属，不把模型重新核验当成政策准入。
`presentation_candidate` 仅表示达到候选覆盖条件；`presentation_ready` 保持 false，等待真实内容与视觉审阅。

本轮仅执行离线测试，未启动上文真实运行命令，未调用项目 LLM／豆包。
实现限制、设计取舍与下一步见 [DESIGN.md](DESIGN.md)。
