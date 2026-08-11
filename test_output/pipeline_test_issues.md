# 问财SkillHub流水线测试问题报告

**测试日期**: 2026-08-11  
**Run ID**: 2ae5aca2-2045-4fe6-b52b-17e93701a9fc  
**测试目标**: 用NVIDIA FY2026真实财报数据跑通Agent 2-5，生成HTML报告  
**最终状态**: 流水线成功完成，HTML/Markdown/PDF报告均已生成（草稿版）

---

## 一、流水线执行概览

| 阶段 | 状态 | 错误 | 产出 |
|------|------|------|------|
| data_fetch (Agent 1) | completed | 无 | 20条evidence + 20个chart_dataset |
| data_interpret (Agent 2) | completed | 无 | 9条claims, 3个scenarios, 3个chart_candidates |
| chart_generate (Agent 3) | completed | no_matching_dataset | 0个图表（3个候选全被抑制） |
| chapter_write (Agent 4) | completed | StructuredOutputError | 7章（兜底生成） |
| report_fusion (Agent 5) | completed | 无 | HTML/Markdown/PDF/Manifest |

---

## 二、各Agent详情

### 2.1 Agent 2 (data_interpret) — 成功

- 模型: deepseek-v4-flash
- 质量检查: passed, evidence_coverage=0.7
- 产出: 9条claims（3个fact, 3个inference, 3个scenario），3个情景，3个chart_candidates
- 数据质量问题: 3个（DQ-MISSING-QUARTERLY, DQ-CONFLICT-GM, DQ-NOT-COMPARABLE-COMPETITORS）
- 维度覆盖问题: competition=partial, macro_policy=insufficient, industry_chain=insufficient, risk=partial

### 2.2 Agent 3 (chart_generate) — 图表全部被抑制

**问题**: 3个图表候选全部被抑制，原因 `no_matching_dataset`

| 图表 | 需要的evidence_ids | 问题 |
|------|-------------------|------|
| 英伟达FY2025-FY2026营收与净利润对比 | E-FY25-REV, E-FY26-REV, E-FY25-NI, E-FY26-NI | 无匹配数据集 |
| 英伟达FY2026 Q4各业务收入构成 | E-FY26Q4-DC, E-FY26Q4-GAMING, E-FY26Q4-PROVIZ, E-FY26Q4-AUTO | 无匹配数据集 |
| 英伟达GAAP毛利率变化趋势 | E-FY25-GM, E-FY26-GM, E-FY26Q4-GM | 无匹配数据集 |

**根因**: Agent 1 (data_fetch) 的 mock 实现为每个 evidence 创建了独立的 dataset（DS-MOCK-*），但 dataset 的 evidence_ids 列表只包含单个 evidence_id。Agent 3 的 chart_generate 需要将多个 evidence_id 映射到同一个 dataset 来绘制对比图表，但当前 dataset 结构不支持多 evidence 合并到一个图表。

**影响**: 报告无图表，为纯文本报告。

### 2.3 Agent 4 (chapter_write) — 兜底生成

**问题**: 所有7章均使用确定性兜底（fallback）生成，原因:
```
StructuredOutputError: semantic_validation_failed
validation_error_count=1
validation_paths=['sections.2.paragraphs.0']
validation_types=['value_error']
```

**根因**: DeepSeek-V4-Flash 模型在生成章节内容时，无法产出符合 `Chapter` Pydantic 模型严格结构要求的数据。`sections[2].paragraphs[0]` 的字段验证失败，导致全部7章回退到最小化兜底内容。

**影响**: 
- 章节内容重复度高，所有章节都复用相同的几条 claim
- 每个章节的 section 2 第3节（sections[2]）生成失败，可能存在结构性缺陷
- 章节质量门未通过（quality.passed=false）

### 2.4 Agent 5 (report_fusion) — 成功（草稿版）

- 报告格式: HTML (35KB), Markdown (24KB), PDF (1.2MB)
- 交付状态: ready_with_limits
- 发布模式: draft_with_warnings
- 正式版合格: false（因 Agent 3/4 质量门未通过）
- 未解决风险: 11个

---

## 三、环境问题

### 3.1 502 Bad Gateway

**现象**: curl 和 httpx 请求 localhost:8000 返回 502

**根因**: 系统环境变量 `http_proxy=http://127.0.0.1:7890` 导致所有 HTTP 请求被代理拦截。代理服务器无法转发到 localhost，返回 502。

**解决方法**: 
- curl: 使用 `--noproxy '*'` 参数
- Python httpx: 设置环境变量 `no_proxy=localhost,127.0.0.1`

### 3.2 服务启动失败

**现象**: `uvicorn main:app` 报 "Could not import module 'main'"

**根因**: main.py 位于 `app/main.py`，正确的模块路径是 `app.main:app`

### 3.3 测试脚本 HTTP 状态码判断错误

**现象**: 测试脚本输出 "ERROR creating run (201)"，但实际创建成功

**根因**: API 创建 run 返回 201 (Created)，测试脚本只检查 `status_code != 200`，误报为错误。

---

## 四、核心问题总结

1. **DeepSeek-V4-Flash 结构化输出能力不足**: Agent 4 的章节生成无法通过 Pydantic 严格验证，导致全部回退到兜底模式。这是本次测试最严重的问题。

2. **Mock DataFetcher 的 dataset 结构限制**: Agent 1 的 mock 实现为每个 evidence 创建独立 dataset，不支持多 evidence 合并到同一图表。导致 Agent 3 无法生成对比图表。

3. **HTTP 代理干扰**: 本地开发环境存在 HTTP 代理，导致所有 localhost 请求被拦截。需要在代码或环境中显式绕过代理。

4. **报告虽为草稿但完整**: 尽管 Agent 3/4 存在质量问题，Agent 5 仍成功组装了完整的7章21节报告，包含执行摘要、情景分析、风险清单等关键内容。

---

## 五、建议修复方向

1. **Agent 4 模型切换**: 将 chapter_write 阶段的模型切换为结构化输出能力更强的模型（如 GPT-4o），或使用 DeepSeek 的 JSON mode 替代 structured output。

2. **Agent 3 dataset 匹配逻辑**: 修改 chart_generate 的 dataset 匹配逻辑，支持跨多个 dataset 合并数据点来生成对比图表。

3. **Agent 1 mock 改进**: 让 mock DataFetcher 生成能支持多 evidence 合并的 dataset 结构。

4. **代理配置**: 在项目配置或启动脚本中设置 `no_proxy=localhost,127.0.0.1`。