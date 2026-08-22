# 缺陷统计
- 阻断故障数：6
- 普通缺陷数：0
- 根因分布：
  - 工具Schema/MCP工具缺陷：5
  - 提示词缺陷：1

## Bug 明细
### Bug 1
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）图表数值与计算一致
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T133959Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 2
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）无数据不绘图
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T133959Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 3
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）趋势数据用折线
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T133959Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 4
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）结构占比用饼图
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T133959Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 5
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）维度对比用柱状
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T133959Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 6
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：宁德时代毛利率
- 实际现象：partial-chain case stopped with error at data_fetch: core_data_group_unavailable
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T133959Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准
