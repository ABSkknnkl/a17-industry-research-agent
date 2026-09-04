# 项目长期记忆：同花顺问财 SkillHub

## 评审器（ReadabilityLinter）规则演进

评审器 = 确定性 Linter（锚）+ LLM 软分（补充）。`backend/app/agents/chapter_writer/readability_linter.py`，当前 10 条规则：

| 规则 | 判据 | 维度 | 严重度 |
| --- | --- | --- | --- |
| R1 | 双主语/句式杂糅（7 组正则） | 通顺度 | must_fix |
| R2 | 小句（两个标点之间）> 30 字 | 通顺度 | suggest |
| R3 | 自夸词表（本报告深入等 4 词） | 客观性 | must_fix |
| R4 | 单句术语词表 ≥3 | 通俗度 | suggest |
| R5 | 裸标签拼接（。XX：） | 连贯性 | suggest |
| R6 | 字段/占位符泄漏（@值/@id/未提供/证据编号相关证据/['…']） | 连贯性 | must_fix |
| R7 | 内部质检信息泄漏（shift异常检测/基线区间/CRITICAL） | 客观性 | must_fix |
| R8 | 假靶子/空泛强调（值得强调的是/值得注意的是/毋庸置疑/显而易见） | 客观性 | must_fix |
| R9 | 空泛结论（未来可期/前景广阔/意义重大/持续向好等） | 客观性 | suggest |
| R10 | 自问自答老师腔 + 空泛连接词堆叠（此外/综上所述 ≥2） | 客观性/连贯性 | suggest |

**关键设计约束（踩坑教训）**：
- 句长判断必须**按标点切分**（`_CLAUSE_SPLIT` 覆盖全部标点），不是按"句号到句号"数整句。真实研报 87% 小句 ≤30 字，阈值 30。
- 「大幅增长」「显著提升」这类词**带量化数据时是有效表达**（如"同比大幅增长12.6%"），不能进确定性词表，留给 LLM 软判。
- R6/R7/R8/R9/R10 是**数据链路泄漏/AI味检测**，与 prompt.md 写作规则无一一对应，是纯检测器。
- prompt.md 版本：写作规则 15 =「两个标点之间的片段不超过30字」，与 Linter 对齐。改 prompt 必须重算 SHA256 并更新 prompt_loader.py + test_prompt_asset.py 版本断言。

**红队样本集**：`tests/agents/chapter_writer/redteam_readability_samples.py`，负样本 RT-01~16 + 正样本 POS-01~19。正例来自真实研报 PDF（带 source），负例含真实坏报告。

## 评审器语料注入方法（从真实研报 PDF）

PDF 的正确用法是「人工标注校准集 + few-shot 样例」，不是喂训练。流程：pymupdf 抽取 → 按标点切分 → 剔除双主语/自夸/裸标签 → 精选「专业但通顺」句进 POSITIVE_SAMPLES。

## 已知上游根因（未修，评审器只能拦不能修）

- A2 数据解读层字段清洗缺失：`宏观@值为X未提供`、`证据编号相关证据` 等原始 KV 直接进 claims。
- A1 数据采集 routing 抓错数据：标题"动力电池"，正文全是社融数据（主题错乱）。
