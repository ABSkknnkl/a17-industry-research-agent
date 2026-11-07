"""pass@k / pass*k 指标实现（EVALUATION_PLAN §6.2）。

``g_pass_at_k`` 采用 pass@k 的超几何无偏估计（Hypergeometric unbiased
estimator）。该估计公式源自 OpenAI Codex 论文《Evaluating Large Language
Models Trained on Code》（Chen et al., 2021），并由 open-compass/GPassK
项目（Apache-2.0）实践推广：

    pass@k = 1 - C(n-c, k) / C(n, k)      （n-c ≥ k 时）

其中 n=采样数、c=正确数、k=抽取数。相比简单比值 c/n，它纠正了小样本
与 n<k 时的偏差，是 §6.2 门禁（PR pass@1=100%、周 pass@3、发版 pass*3）
的计算基础。

``pass_star_k`` 借鉴 claw-eval 的 Pass^k 语义：k 次**独立**运行全部通过
才算通过（不强求无偏，只做布尔判定），用于发版门禁的严格判定。
"""

from __future__ import annotations

import math


def g_pass_at_k(n: int, c: int, k: int) -> float:
    """pass@k 超几何无偏估计。

    Args:
        n: 单个用例的独立采样次数（runs）。
        c: 这些采样中判定通过的次数。
        k: 抽取数（pass@k 中的 k）。

    Returns:
        [0, 1] 区间的通过率估计。
        当 n - c < k 时，数学上必然至少抽到一个正确样本，返回 1.0；
        当 n == 0 时无有效样本，返回 0.0。

    实现采用累积连乘：
        1 - prod_{i=n-c+1..n} (1 - k/i)
    该形式等价于 1 - C(n-c, k)/C(n, k)，且在大 n 下数值更稳。
    """
    if n <= 0:
        return 0.0
    c = max(0, min(c, n))
    k = max(0, k)
    if k == 0:
        return 1.0 if c >= 1 else 0.0
    if n - c < k:
        return 1.0
    # prod_{i=n-c+1..n} (1 - k/i)
    product = 1.0
    for i in range(n - c + 1, n + 1):
        product *= 1.0 - (k / i)
    return float(1.0 - product)


def _comb(n: int, k: int) -> float:
    """组合数 C(n, k)，用于对拍/文档说明（未纳入主估计路径）。"""
    if k < 0 or k > n:
        return 0.0
    k = min(k, n - k)
    return math.comb(n, k)


def pass_star_k(results: list[bool], *, k: int) -> bool:
    """claw-eval 式 Pass^k：k 次独立运行**全部通过**才算通过。

    Args:
        results: 同一条用例 k 次独立运行的布尔结果。
        k: 要求全过的次数（与 ``results`` 长度一致）。
    """
    if len(results) < k:
        raise ValueError(f"pass*k 需要至少 {k} 次运行，实际 {len(results)} 次")
    return all(results[:k])


def score_batch(pass_at_k_inputs: list[tuple[int, int, int]]) -> list[float]:
    """批量计算 g_pass_at_k，供周报聚合使用。"""
    return [g_pass_at_k(n, c, k) for (n, c, k) in pass_at_k_inputs]