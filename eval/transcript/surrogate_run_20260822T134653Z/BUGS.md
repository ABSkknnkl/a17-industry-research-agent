# 缺陷统计
- 阻断故障数：1
- 普通缺陷数：0
- 根因分布：
  - 提示词缺陷：1

## Bug 明细
### Bug 1
- 被测对象：five_agent_chain
- 故障等级：blocking
- 复现输入：看下宁德时代财务，顺便对比比亚迪
- 实际现象：partial-chain case stopped with error at data_fetch: core_data_group_unavailable
- 原始快照片段：/Users/Zhuanz1/PycharmProjects/同花顺/eval/transcript/surrogate_run_20260822T134653Z/traces.jsonl
- 根因分类：提示词缺陷
- 修复建议：根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。
- 测试结论：不满足上线标准
