# 缺陷统计
- 阻断故障数：29
- 普通缺陷数：0
- 根因分布：
  - 提示词缺陷：26
  - 工具Schema/MCP工具缺陷：3

## Bug 明细
### Bug 1
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：储能未来三年市场空间大概有多大
- 实际现象：intercept stage mismatch: expected=data_interpret actual=data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 2
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：锂电池行业CR3、CR5市场占有率变化
- 实际现象：positive case ended as WAITING_REVIEW
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 3
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：比亚迪营收同比、归母净利同比
- 实际现象：positive case ended as WAITING_REVIEW
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 4
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：药明康德存货周转率、应收周转率
- 实际现象：completed with report artifacts
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 5
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：缺期初存货时算存货周转率
- 实际现象：intercept stage mismatch: expected=data_interpret actual=report_fusion
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 6
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：净利润=0时算净利率
- 实际现象：intercept stage mismatch: expected=data_interpret actual=report_fusion
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 7
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：营收=元、成本=万元算毛利率
- 实际现象：intercept stage mismatch: expected=data_interpret actual=report_fusion
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 8
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：仅2家样本算CR5
- 实际现象：intercept stage mismatch: expected=data_interpret actual=data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 9
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：华安新能源的毛利率
- 实际现象：intercept stage mismatch: expected=data_fetch actual=report_fusion
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 10
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：蓝天电池科技近四年财报
- 实际现象：intercept error mismatch: expected=['required_data_unavailable'] actual=intent_clarification_required
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 11
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：用2025年报和2026一季报算同比
- 实际现象：intercept stage mismatch: expected=data_interpret actual=data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 12
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：标的全部字段缺失
- 实际现象：intercept error mismatch: expected=['required_data_unavailable'] actual=intent_clarification_required
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 13
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：宁德时代近四年营收、归母净利润、毛利率、各项费用率并梳理主营业务结构
- 实际现象：partial-chain case completed target stage data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 14
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：对比宁德时代与比亚迪的营业收入和毛利率
- 实际现象：partial-chain case stopped legitimately at data_fetch: required_data_unavailable
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 15
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：梳理比亚迪近半年业绩预告与增发事件
- 实际现象：partial-chain case completed target stage data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 16
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：请查询宁德时代2025年营业收入
- 实际现象：partial-chain case completed target stage data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 17
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：查询宁德时代2023年到2025年的归母净利润
- 实际现象：partial-chain case completed target stage data_fetch
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 18
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（基准）CR3集中度
- 实际现象：partial-chain case never reached stage data_interpret
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 19
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（基准）CR5集中度
- 实际现象：partial-chain case never reached stage data_interpret
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 20
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（基准）归母净利同比
- 实际现象：partial-chain case never reached stage data_interpret
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 21
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（溯源）证据缺失致断链
- 实际现象：partial-chain case never reached stage chapter_write
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 22
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（溯源）证据篡改致断链
- 实际现象：partial-chain case never reached stage chapter_write
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 23
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（溯源）数值无溯源
- 实际现象：partial-chain case never reached stage chapter_write
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 24
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（溯源）证据ID越权引用
- 实际现象：partial-chain case never reached stage chapter_write
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 25
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（溯源）证据链跨章断链
- 实际现象：partial-chain case never reached stage chapter_write
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 26
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（溯源）数值claim无证据池
- 实际现象：partial-chain case never reached stage chapter_write
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 27
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）同数据集默认单图
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 28
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）用户多图豁免
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准

### Bug 29
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：（图表）产业链图唯一
- 实际现象：partial-chain case never reached stage chart_generate
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T125125Z/traces.jsonl
- 根因分类：工具Schema/MCP工具缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准
