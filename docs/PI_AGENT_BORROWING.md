# 给 Codex：本项目如何借鉴 Pi Agent（说明）

> 读者：Codex / 其他 AI 编码助手  
> 仓库：`ABSkknnkl/a17-industry-research-agent`  
> 日期：2026-09-11  
> 相关文件：`THIRD_PARTY_NOTICES.md`、`backend/app/runtime/`、`AGENTS.md`

---

## 1. 先记住三句话

1. **没有安装 Pi，也没有复制 Pi 的 TypeScript 源码。**
2. **只借鉴了 Pi 的「单 Agent 运行时治理」思路**，用 Python + LangGraph 在 `backend/app/runtime/` 重写。
3. **五阶段总流程仍是 LangGraph 固定编排**，不要用 Pi 或自由 Agent Loop 替换生产主链。

对外表述（答辩/文档可用）：

> 参考 [earendil-works/pi](https://github.com/earendil-works/pi)（原 badlogic/pi-mono，MIT）的 agent-loop 治理模型，在本项目 LangGraph 流水线上独立实现运行时护栏；未引入 Pi 包依赖。

---

## 2. Pi 是什么（与本项目的边界）

Pi 是一个极简 Agent 运行时/编码 Agent 框架：

| Pi 包 | 作用 |
| --- | --- |
| `@earendil-works/pi-ai` | 多厂商统一 LLM API |
| `@earendil-works/pi-agent-core` | Agent 循环、工具调用、状态 |
| `@earendil-works/pi-coding-agent` | 交互式编码 CLI |
| `@earendil-works/pi-tui` | 终端 UI |

**本项目需要的不是「一个编码 CLI」**，而是：工具怎么调、调用前后怎么拦、超时/预算怎么算、失败怎么回灌模型、事件怎么脱敏。  
这些是 Pi 的 **Agent Core** 治理层思想，对应本项目的：

```text
backend/app/runtime/
├── __init__.py        # 声明「inspired by Pi harness」
├── models.py          # RuntimePolicy / RuntimeState / RuntimeEvent
├── guard.py           # 回合/阶段前后钩子 + 预算拦截（Pi-style）
├── tool_gateway.py    # 工具全生命周期（following Pi tool-call lifecycle）
└── model_gateway.py   # LLM 调用记账装饰器
```

声明出处：`THIRD_PARTY_NOTICES.md` → `## Pi Agent Harness`。

---

## 3. 借鉴了什么（对照表）

| Pi 机制（概念） | 本项目落地 | 位置 |
| --- | --- | --- |
| 回合停止检查 / shouldStop | 阶段前检查取消、deadline、总次数、单阶段重试 | `guard.py::RuntimeSession.before_stage` |
| 工具参数校验 | Pydantic `args_model.model_validate` | `tool_gateway.py` |
| beforeToolCall | before hooks，可 block | `tool_gateway.py` |
| afterToolCall | after hooks，可替换结果 | `tool_gateway.py` |
| 超时 | `asyncio.timeout(policy.tool_timeout_seconds)` | `tool_gateway.py` |
| 错误作为结构化工具结果回灌 | `ToolResult(is_error, error_code, retryable)` | `tool_gateway.py` |
| 生命周期事件 | stage/model/tool 的 started/completed/failed | `models.py` + `guard.py` |
| 运行预算 | 限制 model/tool 次数、阶段次数、总时限 | `RuntimePolicy` / `RuntimeState` |
| LLM 调用接入循环记账 | `RuntimeAware*Model` 装饰器 | `model_gateway.py` |

### 3.1 工具调用标准顺序（与 Pi 对齐）

```text
ToolGateway.execute(call)
  1. session.before_tool_call  → 预算不够则返回结构化错误
  2. 查找工具                 → tool_not_found
  3. 参数校验                 → tool_arguments_invalid
  4. before_hooks             → tool_call_blocked
  5. asyncio.timeout 内执行   → tool_timeout / tool_execution_failed
  6. after_hooks              → 可替换结果；hook 失败 → after_tool_hook_failed
  7. 结果长度截断             → truncated 标记
  8. session.after_tool_call  → 写脱敏事件
```

Codex 改 `tool_gateway.py` 时 **必须保持这个顺序**，不要把 hook 挪到校验之前或去掉错误回灌。

### 3.2 金融项目相对 Pi 多做的事

| 增强 | 说明 |
| --- | --- |
| 事件脱敏 | `RuntimeEvent` **禁止**写入 prompt、工具入参、模型正文、供应商异常原文 |
| 预算进 checkpoint | `RuntimeState` 随 LangGraph 状态持久化，可恢复 |
| 统一入口 | SkillHub 全部技能经同一 `ToolGateway`，继承超时/预算/审计 |

---

## 4. 有什么用（对赛题/产品的价值）

| 能力 | 用处 |
| --- | --- |
| 工具参数校验 + before hook | 拦危险/不合法调用，金融查询不乱打 |
| 超时 + 次数预算 | 单次任务不会无限烧 API / 卡死演示 |
| 错误结构化回灌 | Agent1/2 能按 `error_code/retryable` 决定重试或停审，而不是进程崩溃 |
| 结果截断 | 控制上下文和费用；权威数据仍在业务库，不靠塞进 prompt |
| 脱敏事件 | 支持审计与（后续）前端进度，且不泄密 |
| LLM 记账 | 模型调用次数可控，防止无限循环生成 |

**没有这套东西时**：LLM 或工具一失控，就是超时、重复调用、把密钥写进日志、演示翻车。  
**有这套东西时**：每次运行有边界、有轨迹、失败可解释。

---

## 5. 不要做什么（Codex 红线）

1. **不要** `npm install` / `pip install` Pi，不要 import 不存在的 `@earendil-works/*`。  
2. **不要** 把五阶段 `data_fetch → … → report_fusion` 改成一个自由 while 模型循环。  
3. **不要** 用 Pi RPC/SDK 替换生产主链（若试验，只允许隔离 sidecar，见调研 P2）。  
4. **不要** 在事件/日志里加回 prompt 原文、工具完整参数、密钥。  
5. **不要** 去掉 `RuntimeBudgetExceeded` 或放宽 `RuntimePolicy` 上限来「让测试过」。  
6. **不要** 让模型绕过 `ToolGateway` 直连 HTTP。  
7. 修改 `THIRD_PARTY_NOTICES.md` 时，保留 Pi 条目；若扩大借鉴范围，补写实际范围。

---

## 6. 你改代码时怎么判断「还算 Pi 风格借鉴」

**符合借鉴（保持）：**

- 生命周期 before/after 对称  
- 失败必须变成结构化结果回到调用方/模型，而不是未捕获异常炸栈  
- 预算与超时在 gateway/session 层，不散落在每个业务函数里硬编码  

**偏离借鉴（不要引入）：**

- 自由决定工作流阶段顺序  
- 无限工具循环「自愈」  
- 把 Pi 本地 JSONL session 当成业务数据库  

---

## 7. 相关测试（改 runtime 必看）

- `backend/tests/runtime/test_tool_gateway.py`：校验、hook、超时、预算  
- `backend/tests/runtime/test_model_gateway.py`：模型调用上限  

行为变更时优先改测试，再改实现。

---

## 8. 与「Pi 调研建议」文档的关系

外部调研文《pi-agent调研建议.md》进一步建议：不换框架；优先做 SSE、五阶段演示审核、上下文投影、Skill 按需加载；Pi 仅可做隔离试验。  
**Codex 实施时**：业务功能优先；`app/runtime/` 的 Pi 式治理是底座，除非用户明确要求，不要重构掉。

---

## 9. 一页速查

```text
问题：项目用了 Pi 吗？
答：没用包。在 app/runtime/ 按 Pi agent-loop 思路用 Python 重写了工具治理与预算。

问题：借鉴点？
答：停止检查、参数校验、before/after hook、超时、错误回灌、生命周期事件、调用预算。

问题：有什么用？
答：防失控、可审计、失败可回灌；服务五阶段确定性编排，不替代它。

问题：Codex 能改什么？
答：能增强 runtime，但必须保持 gateway 顺序、脱敏、预算，不引入 Pi 依赖、不改总流程为自由循环。
```
