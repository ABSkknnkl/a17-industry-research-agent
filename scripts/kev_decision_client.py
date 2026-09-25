"""决策模型客户端（TypeSafe System One 契约 / Kev 开源实现兼容）。

设计目标
--------
1. **零侵入**：本文件是新增文件，不依赖也不修改 ``agents_core`` 下的任何模块。
   现有五智能体可以直接 import 使用，也可以完全不使用。
2. **可降级**：``available`` 为 False 时，所有调用方应立即回落到既有的确定性路径
   （如 ``FastSkillRouter``、``metric_guard``、``_validate_tasks``），
   绝不因为决策服务不可用而让流水线挂掉。
3. **批量优先**：一次 HTTP 请求里并行提交多个问题，是这套模型吞吐的关键。
   TypeSafe/Kev 的 ``/v1/systemone`` 原生支持这种用法。

为什么这样设计而不是直接调 SDK
------------------------------
官方 ``typesafe_sdk`` 依赖外网与已开放的区域。本机（中国大陆）不可用，
因此这里直接按 HTTP 契约实现，指向本地 Kev 服务即可：

    uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009

未来若官方 API 开放中国区，只需把 ``base_url`` 换成官方地址，代码零改动。

用法
----
服务端：见 ``output/Jev决策模型落地方案.md`` 的 Step 0。

客户端：

    client = DecisionClient.from_env()
    if client.available:
        resp = await client.decide(
            state=chapter_state_text,
            questions={
                "CH-01": ChoiceQuestion(
                    instructions="本章应加载哪些写作技能？",
                    criteria={name: desc for name, desc in skill_catalog},
                ),
            },
        )

中文域评估（投产前必做）：

    python scripts/kev_decision_client.py --eval samples.jsonl --threshold 0.85

``samples.jsonl`` 每行形如::

    {"state": "……章节内容……", "question": "routing",
     "criteria": ["skill-a", "skill-b", "skill-c"], "label": "skill-b"}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - 仅在缺依赖时触发
    httpx = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# 问题类型（与 TypeSafe 契约一一对应）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ChoiceQuestion:
    """从预定义选项中选择一个。

    Args:
        instructions: 用自然语言描述"要判断什么"，不要在这写推理步骤。
        criteria: 选项名 -> 选项说明（说明可为 None）。选项数上限 255。
    """

    instructions: str
    criteria: Mapping[str, str | None]

    def to_payload(self) -> dict[str, Any]:
        """转换为 System One 契约的 question 对象。"""
        return {
            "type": "choice",
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


@dataclass(frozen=True, slots=True)
class ScoreQuestion:
    """在一组有序刻度上打分。

    Args:
        instructions: 判断目标，例如"这条数据是否足以支撑折线图"。
        criteria: 从低到高排列的刻度描述列表（Kev 兼容实现支持 2~255 级）。
    """

    instructions: str
    criteria: Sequence[str]

    def to_payload(self) -> dict[str, Any]:
        """转换为 System One 契约的 question 对象。"""
        return {
            "type": "score",
            "instructions": self.instructions,
            "criteria": list(self.criteria),
        }


@dataclass(frozen=True, slots=True)
class NoulQuestion:
    """判断一个命题成立的概率，返回 0~1。

    命名来自 "no" + "null"，实际语义是"是为真的概率"。

    Args:
        instructions: 待判断的命题。
        true_hint: 可选的"何时为真"补充说明。
        false_hint: 可选的"何时为假"补充说明。
    """

    instructions: str
    true_hint: str | None = None
    false_hint: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """转换为 System One 契约的 question 对象。"""
        criteria: dict[str, str] = {}
        if self.true_hint:
            criteria["true"] = self.true_hint
        if self.false_hint:
            criteria["false"] = self.false_hint
        return {
            "type": "noul",
            "instructions": self.instructions,
            "criteria": criteria or None,
        }


Question = ChoiceQuestion | ScoreQuestion | NoulQuestion


# --------------------------------------------------------------------------- #
# 响应模型
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Answer:
    """单个问题的结构化回答。"""

    question_id: str
    kind: str
    #: choice 类的胜出选项；其余类型为 None
    choice: str | None = None
    #: noul 类的"为真概率"
    noul: float | None = None
    #: score 类的期望刻度（从 0 开始）
    score: float | None = None
    #: 完整概率分布；noul 类为空
    probabilities: dict[str, float] = field(default_factory=dict)
    #: 0~1 的置信度；noul 类为 None
    confidence: float | None = None

    @property
    def is_confident(self) -> bool:
        """noul 类以到中点的距离衡量确定性，其余用 confidence 字段。"""
        if self.kind == "noul" and self.noul is not None:
            return abs(self.noul - 0.5) > 0.35
        return (self.confidence or 0.0) > 0.0

    def as_dict(self) -> dict[str, Any]:
        """便于写进事件流 / 日志的扁平表示。"""
        return {
            "question_id": self.question_id,
            "kind": self.kind,
            "choice": self.choice,
            "noul": self.noul,
            "score": self.score,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
        }


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #


class DecisionClient:
    """TypeSafe System One 契约的轻量客户端。

    与官方 SDK 的差别只有一处：不内置 base_url，必须显式给（默认指向本地 Kev）。

    Args:
        base_url: 服务地址，本地 Kev 默认 ``http://127.0.0.1:8009``。
        model: 模型标识，Kev 系列用 ``kev-latest``。
        api_key: 本地 Kev 未设 ``KEV_API_KEY`` 时留空即可。
        timeout_seconds: 单次请求超时。决策服务正常应在毫秒级，
            超时即视为不可用并降级。

    Raises:
        RuntimeError: 当调用方显式要求 ``strict=True`` 且 httpx 未安装时。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8009",
        model: str = "kev-latest",
        api_key: str = "",
        timeout_seconds: float = 8.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        #: 探测结果缓存：None 表示尚未探测
        self._probe: bool | None = None

    # -- 构造 ---------------------------------------------------------------- #

    @classmethod
    def from_env(cls) -> "DecisionClient":
        """从环境变量构造。

        环境变量（全部可选，缺失时走降级路径）::

            DECISION_BASE_URL       默认 http://127.0.0.1:8009
            DECISION_MODEL          默认 kev-latest
            DECISION_API_KEY        默认空
            DECISION_TIMEOUT        默认 8
        """
        return cls(
            base_url=os.getenv("DECISION_BASE_URL", "http://127.0.0.1:8009"),
            model=os.getenv("DECISION_MODEL", "kev-latest"),
            api_key=os.getenv("DECISION_API_KEY", ""),
            timeout_seconds=float(os.getenv("DECISION_TIMEOUT", "8")),
        )

    # -- 可用性 -------------------------------------------------------------- #

    @property
    def available(self) -> bool:
        """是否已确认可用（同步判断，不做网络探测）。

        未探测过时返回 False —— 调用方必须先 ``await probe()``。
        这样设计是为了让"服务没起"这件事永远不会变成阻塞。
        """
        return bool(self._probe) and httpx is not None

    async def probe(self) -> bool:
        """探测服务是否就绪，结果缓存。

        Returns:
            服务可用返回 True。任何异常（连接失败、超时、非 2xx）都返回 False，
            不抛出 —— 降级路径必须是无条件的。
        """
        if httpx is None:
            self._probe = False
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url}/v1/models")
                self._probe = response.status_code == 200
        except Exception:
            self._probe = False
        return bool(self._probe)

    # -- 核心调用 ------------------------------------------------------------ #

    async def decide(
        self,
        state: str | Mapping[str, Any] | Sequence[Any],
        questions: Mapping[str, Question],
    ) -> dict[str, Answer]:
        """一次性提交多个问题并取回结构化答案。

        Args:
            state: 被评估的上下文。可以是字符串，也可以是 dict/list
                （Kev 会转成带标签的文本）。**注意**：多个问题共享同一份
                state，问题之间互相不可见。
            questions: 问题 ID -> 问题对象。问题 ID 只用于本地索引，模型看不到。

        Returns:
            问题 ID -> Answer。

        Raises:
            RuntimeError: 服务不可用或请求失败。调用方应当捕获并降级，
                这也是为什么所有接入点都必须包在 try/except 里。
        """
        if httpx is None:
            raise RuntimeError("httpx 未安装，无法调用决策服务")
        if not questions:
            return {}

        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "state": state,
            "model": self.model,
            "questions": {qid: q.to_payload() for qid, q in questions.items()},
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/v1/systemone", headers=headers, json=payload
            )
            response.raise_for_status()
            body = response.json()

        raw_answers = body.get("answers") or {}
        return {
            qid: _parse_answer(qid, raw_answers.get(qid) or {})
            for qid in questions
        }

    # -- 便捷封装 ------------------------------------------------------------ #

    async def choose(
        self, state: str, instructions: str, criteria: Mapping[str, str | None]
    ) -> Answer | None:
        """单问题 Choice 的便捷封装。

        Returns:
            成功返回 Answer；服务不可用或调用失败返回 None（供调用方降级）。
        """
        if not self.available:
            return None
        try:
            answers = await self.decide(
                state, {"q": ChoiceQuestion(instructions, criteria)}
            )
            return answers.get("q")
        except Exception:
            return None

    async def ask(
        self, state: str, instructions: str, true_hint: str | None = None
    ) -> Answer | None:
        """单问题 Noul 的便捷封装，服务不可用时返回 None。"""
        if not self.available:
            return None
        try:
            answers = await self.decide(
                state, {"q": NoulQuestion(instructions, true_hint=true_hint)}
            )
            return answers.get("q")
        except Exception:
            return None


def _parse_answer(question_id: str, raw: Mapping[str, Any]) -> Answer:
    """把服务端返回的单个答案对象转成 :class:`Answer`。

    服务端字段形态参考 Kev 契约：
    ``{"type":"choice","choice":..,"confidence":..,"probabilities":{..}}``
    ``{"type":"noul","noul":0.93}``
    ``{"type":"score","score":1.44,"confidence":..,"probabilities":{..}}``
    """
    kind = str(raw.get("type") or "unknown")
    probabilities = raw.get("probabilities") or {}
    return Answer(
        question_id=question_id,
        kind=kind,
        choice=raw.get("choice"),
        noul=_as_float(raw.get("noul")),
        score=_as_float(raw.get("score")),
        probabilities={str(k): float(v) for k, v in probabilities.items()},
        confidence=_as_float(raw.get("confidence")),
    )


def _as_float(value: Any) -> float | None:
    """尽最大努力转 float，失败返回 None（不抛异常）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 中文域评估（投产前的硬门槛）
# --------------------------------------------------------------------------- #


def expected_calibration_error(
    confidences: Sequence[float], corrects: Sequence[bool], bins: int = 10
) -> float:
    """计算期望校准误差（ECE）。

    校准 ≠ 正确。ECE 衡量的是"模型说 80% 把握的时候，是不是真的有 80% 是对的"。
    这个指标决定了能否用 ``confidence`` 做自动放行/升级人工的门控。

    Args:
        confidences: 每个样本的置信度（0~1）。
        corrects: 每个样本是否预测正确。
        bins: 分箱数，默认 10。

    Returns:
        ECE 值，越小越好；样本为空时返回 0.0。

    Raises:
        ValueError: 两个序列长度不一致时抛出。
    """
    if len(confidences) != len(corrects):
        raise ValueError("confidences 与 corrects 长度必须一致")
    if not confidences:
        return 0.0

    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for confidence, correct in zip(confidences, corrects):
        index = min(bins - 1, max(0, int(confidence * bins)))
        buckets[index].append((confidence, correct))

    total = len(confidences)
    error = 0.0
    for items in buckets.values():
        mean_confidence = sum(c for c, _ in items) / len(items)
        accuracy = sum(1 for _, ok in items if ok) / len(items)
        error += (len(items) / total) * abs(accuracy - mean_confidence)
    return error


async def run_eval(samples_path: Path, threshold: float) -> int:
    """对一份中文标注样本集跑评估。

    样本 JSONL 每行::

        {"state": "...", "question": "routing",
         "instructions": "...", "criteria": ["a","b","c"], "label": "b"}

    Args:
        samples_path: 样本文件路径。
        threshold: 验收线。准确率低于该值返回退出码 2。

    Returns:
        进程退出码：0 通过、1 服务不可用、2 未达验收线。
    """
    samples = [
        json.loads(line)
        for line in samples_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not samples:
        print("样本为空", file=sys.stderr)
        return 1

    client = DecisionClient.from_env()
    if not await client.probe():
        print(
            f"决策服务不可用：{client.base_url}\n"
            "请先按 output/Jev决策模型落地方案.md 的 Step 0 起本地 Kev。",
            file=sys.stderr,
        )
        return 1

    # 全量样本合并成一次请求：这正是这套模型吞吐优势的体现
    questions: dict[str, Question] = {}
    labels: dict[str, str] = {}
    for index, sample in enumerate(samples):
        qid = f"q{index:04d}"
        questions[qid] = ChoiceQuestion(
            instructions=sample.get("instructions") or "请选择最合适的选项。",
            criteria={name: None for name in sample["criteria"]},
        )
        labels[qid] = str(sample["label"])

    # 每条样本的 state 不同，因此按样本分批；同 state 的样本才会共享一次 prefill
    groups: dict[str, list[int]] = defaultdict(list)
    for index, sample in enumerate(samples):
        groups[str(sample["state"])].append(index)

    correct_total = 0
    answered_total = 0
    confidences: list[float] = []
    corrects: list[bool] = []

    for state, indices in groups.items():
        batch = {
            f"q{i:04d}": questions[f"q{i:04d}"] for i in indices
        }
        try:
            answers = await client.decide(state, batch)
        except Exception as exc:  # 评估必须跑完，单批失败不中断
            print(f"批失败（{len(indices)} 条）：{exc}", file=sys.stderr)
            continue
        for qid, answer in answers.items():
            index = int(qid[1:])
            answered_total += 1
            is_correct = answer.choice == labels[qid]
            correct_total += int(is_correct)
            if answer.confidence is not None:
                confidences.append(answer.confidence)
                corrects.append(is_correct)

    if answered_total == 0:
        print("没有拿到任何答案", file=sys.stderr)
        return 1

    accuracy = correct_total / answered_total
    ece = expected_calibration_error(confidences, corrects)

    print("=" * 56)
    print(f"样本数      : {len(samples)}")
    print(f"有效回答    : {answered_total}")
    print(f"准确率      : {accuracy:.4f}")
    print(f"ECE（校准） : {ece:.4f}")
    print(f"验收线      : {threshold:.4f}")
    print(f"结论        : {'通过 ✅' if accuracy >= threshold else '未达标 ❌'}")
    print("=" * 56)

    if accuracy >= threshold:
        return 0
    print(
        "\n建议：先用 --init_from 在自有中文样本上做短微调（学习率 2e-5 起），\n"
        "或将决策服务降级为「提案 + 大模型复议」模式。",
        file=sys.stderr,
    )
    return 2


# --------------------------------------------------------------------------- #
# 自检 / CLI
# --------------------------------------------------------------------------- #


async def _demo(state: str) -> None:
    """冒烟测试：跑一个 Choice + 一个 Noul + 一个 Score。"""
    client = DecisionClient.from_env()
    print(f"探测 {client.base_url} ...")
    if not await client.probe():
        print("不可用 —— 请先起本地 Kev（见方案 Step 0）")
        return

    answers = await client.decide(
        state,
        {
            "chart_type": ChoiceQuestion(
                instructions="这批数据最适合用哪种图表？",
                criteria={
                    "line": "连续时间趋势",
                    "bar": "样本横向对比",
                    "combo": "规模与增速双指标",
                    "radar": "单实体多维能力",
                },
            ),
            "should_suppress": NoulQuestion(
                instructions="该图表是否应被抑制？",
                true_hint="数据不足以支撑所选图型",
                false_hint="数据充分",
            ),
            "data_sufficiency": ScoreQuestion(
                instructions="该图型的数据充分程度",
                criteria=["完全不足", "偏少", "勉强", "充分", "非常充分"],
            ),
        },
    )
    for qid, answer in answers.items():
        print(f"  {qid:18s} -> {json.dumps(answer.as_dict(), ensure_ascii=False)}")


def main(argv: Iterable[str] | None = None) -> int:
    """命令行入口。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser(description="决策模型客户端（Kev / System One 契约）")
    parser.add_argument("--eval", type=Path, help="评估样本 JSONL 路径")
    parser.add_argument(
        "--threshold", type=float, default=0.85, help="验收线（默认 0.85）"
    )
    parser.add_argument("--demo-state", type=str, help="用一段文本跑冒烟测试")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.eval:
        return asyncio.run(run_eval(args.eval, args.threshold))
    if args.demo_state:
        asyncio.run(_demo(args.demo_state))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
