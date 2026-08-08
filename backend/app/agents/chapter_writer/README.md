# Chapter Writer

后端 B 负责。Agent 4将通过质量门的Agent 2结构化分析转换为固定7章21节的行业研究报告草稿，不负责重新检索数据、生成图表或输出投资建议。

## 已实现能力

- 固定`2026.1`版大纲，严格输出`CH-01`至`CH-07`，每章3节。
- 只消费Agent 2的`AnalysisResult`；输入缺失、契约无效或质量门未通过时返回`waiting_review`。
- Agent 3未完成时，把`chart_candidates`转为`planned`图表请求；Agent 3完成后，只允许引用已生成、有`artifact_id`且证据属于当前章节的图表。
- Prompt以只读资源加载，固定版本`1.0.0`和SHA-256；运行时为每章构建最小证据上下文。
- 内部LangGraph顺序执行`generate → audit → revise/accept → finalize`，每章最多自动修订2次，不会无界循环。
- 质量门校验章节标题、claim/evidence引用、数值出处、图表就绪状态、聚合ID及金融内容红线。
- 图表可为空；达到修订上限后仍返回完整草稿并附质量风险。模型、解析或章节持久化异常时，只使用Agent 2已验证的claim/evidence生成确定性7章21节兜底稿，缺证据处明确标记。
- 支持整章重新生成以及指定小节修订；小节修订保留未选中小节，必须基于上一版完整结果。
- 已接入顶层五阶段Workflow；默认不在`chapter_write`暂停，但仍支持将本阶段显式加入`review_stages`以及`approve/revise/regenerate/cancel`。

## 上下游交接

Agent 2必须输出可通过`AnalysisResult.model_validate()`且`quality.passed=true`的数据。Agent 3真实实现后，在`StageResult.data.charts`中输出`ChartReference[]`；字段契约见`app/schemas/chart.py`。

Agent 5从`StageResult.data`读取`ChapterWritingResult`，应按以下优先级处理：

1. `quality.passed=false`或`collaboration_requests`非空时，以`draft_with_warnings`继续组装并展示风险，不得把风险草稿标记为正式无风险报告。
2. 以`chapters[].sections[].paragraphs[].text`为正文，保留claim/evidence关联，不得只拼接`summary`。
3. 只渲染`chart_ids`引用的已就绪图表；`chart_requests`是待Agent 3完成的请求，不是可展示产物。
4. 输出契约以`contracts/schemas/chapter-writing-result.schema.json`为跨端唯一来源。

## 运行模式

默认`LLM_USE_MOCK=true`，使用`MockChapterWritingModel`便于无密钥开发。切换真实模型时，`OpenAICompatibleChapterModel`与Agent 2共用OpenAI兼容环境变量，但使用独立的`ChapterWritingModel`业务协议和`ChapterDraft`结构化输出。
