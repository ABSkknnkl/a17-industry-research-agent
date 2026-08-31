"""红队可读性样本集：评审器上线门禁与提示词变更回归基线。

负样本覆盖五个维度（堆瘆/病句/术语堆瘆/自夸/假合规真废话）；正样本保证专业但通顺的表达不被误判。
linter_expected 为 None 的样本属于确定性规则判不了的维度（如 RT-05 语义断裂），
必须由 LLM 软分评审器接管。
"""

NEGATIVE_SAMPLES = [
    {
        "id": "RT-01",
        "dimension": "堆瘆",
        "text": (
            "该行业受到政策影响使其产能出现下降，而其产能利用率又受到需求影响从而出现波动，其景气度因此发生边际变化。"
        ),
        "linter_expected": "R1_DOUBLE_SUBJECT",
    },
    {
        "id": "RT-02",
        "dimension": "病句",
        "text": "由于光伏产业链利润池向中游迁移使其议价权增强。",
        "linter_expected": "R1_DOUBLE_SUBJECT",
    },
    {
        "id": "RT-03",
        "dimension": "术语堆瘆",
        "text": (
            "估值锚、利润池迁移、景气度、咽喉节点与护城河共同塑造了该行业的长期格局。"
        ),
        "linter_expected": "R4_JARGON_STACK",
    },
    {
        "id": "RT-04",
        "dimension": "自夸",
        "text": (
            "本报告深入剖析了该行业的底层逻辑，严谨地得出了前瞻性结论。"
        ),
        "linter_expected": "R3_SELF_PRAISE",
    },
    {
        "id": "RT-05",
        "dimension": "假合规真废话",
        "text": "行业规模保持增长。样本覆盖范围有限。政策导向保持稳定。",
        "linter_expected": None,
    },
]

POSITIVE_SAMPLES = [
    {
        "id": "POS-01",
        "dimension": "专业但通顺",
        "text": "样本企业营业收入同比增长12%，统计口径与上年保持一致。",
    },
    {
        "id": "POS-02",
        "dimension": "术语已解释",
        "text": "行业估值锚定在盈利能力上；盈利能力指企业创建净利润的水平。",
    },
    {
        "id": "POS-03",
        "dimension": "边界清晰",
        "text": "中游环节的议价权随供需变化而增强，该结论的适用边界见研究限制部分。",
    },
]
