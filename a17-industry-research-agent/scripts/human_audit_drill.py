#!/usr/bin/env python3
"""人机协同实操演练脚本（留证用）。

在真实环境上完整走一遍「生成 → 审核 → 反馈 → 优化」链路：在四个审核门上
各提交一次人工干预动作，全程保存状态快照、版本历史、反馈历史与事件流，
产出可核对的留证包，供《系统测试说明文档》使用。

用法::

    # 查看演练计划（不调用任何接口）
    ./.venv/bin/python scripts/human_audit_drill.py --topic 半导体设备 --dry-run

    # 正式执行（真实调用数据源与模型，约 20-30 分钟）
    ./.venv/bin/python scripts/human_audit_drill.py --topic 半导体设备 --project-id audit-drill

产出目录：``data/runs/<run_id>/drill_evidence/``
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - 环境问题直接提示
    print("缺少依赖 httpx，请先在项目虚拟环境中安装：pip install httpx", file=sys.stderr)
    raise

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "data" / "runs"

# 审核门顺序（report_fusion 由后端状态机统一处理，不进 review_stages）
REVIEW_STAGES: list[str] = [
    "data_fetch",
    "data_interpret",
    "chart_generate",
    "chapter_write",
]

STAGE_LABELS: dict[str, str] = {
    "data_fetch": "阶段一 · 数据获取",
    "data_interpret": "阶段二 · 数据解读",
    "chart_generate": "阶段三 · 图表生成",
    "chapter_write": "阶段四 · 章节生成",
    "report_fusion": "阶段五 · 报告融合",
}


@dataclass
class DrillStep:
    """一次人工干预动作的留证记录。"""

    stage: str
    action: str
    comment: str
    revision_before: int | None
    revision_after: int | None
    submitted_at: str
    status_code: int | None = None
    error: str | None = None
    snapshot_file: str | None = None

    def to_row(self) -> str:
        rv = (
            f"{self.revision_before} → {self.revision_after}"
            if self.revision_before is not None and self.revision_after is not None
            else "—"
        )
        state = "成功" if self.error is None else f"失败({self.error})"
        return f"| {STAGE_LABELS.get(self.stage, self.stage)} | {self.action} | {rv} | {self.submitted_at} | {state} |"


@dataclass
class DrillPlan:
    """每个审核门要执行的动作（可用 --only 裁剪）。"""

    steps: list[dict[str, Any]] = field(default_factory=list)


def build_actions(topic: str, with_edited_data: bool) -> list[dict[str, Any]]:
    """构造各审核门的干预动作。

    Args:
        topic: 行业主题，用于生成贴合主题的补充取数语句。
        with_edited_data: 是否携带结构化编辑内容（阶段一范围关键词重取）。
            关闭时仅以修订意见驱动重跑，兼容性最好。

    Returns:
        按审核门顺序排列的动作列表。
    """
    return [
        {
            "stage": "data_fetch",
            "action": "revise",
            "comment": f"补充检索关键词「国产替代」并按新条件重取{topic}数据。",
            "edited_data": (
                {"action_type": "scope_keywords_refetch", "keywords": ["国产替代"]}
                if with_edited_data
                else None
            ),
        },
        {
            "stage": "data_interpret",
            "action": "revise",
            "comment": "补充专家背景：本报告面向机构投资者，需重点关注国产替代进度与海外厂商竞争格局。",
            "edited_data": None,
        },
        {
            "stage": "chart_generate",
            "action": "approve",
            "comment": "图表类型、单位与数值已核对无误，通过。",
            "edited_data": None,
        },
        {
            "stage": "chapter_write",
            "action": "revise",
            "comment": "第 3 章增加前道环节国产化率的时间序列对比；第 5 章毛利率分析补充同业对比。",
            "edited_data": None,
        },
        {
            "stage": "report_fusion",
            "action": "approve",
            "comment": "摘要突出国产替代主线，风险章节补充出口管制敏感性分析后定稿。",
            "edited_data": None,
        },
    ]


def build_gate_actions(
    topic: str, with_edited_data: bool
) -> dict[str, list[dict[str, Any]]]:
    """构造「阶段 → 动作序列」编排表。

    审核门语义（关键）：提交修订类动作后，系统会重跑当前阶段并**再次停在同一审核门**，
    必须再提交一次通过动作才会推进到下一阶段。因此每个需要干预的阶段都要编排
    「干预动作 → 通过动作」两个动作。

    Args:
        topic: 行业主题，用于生成贴合主题的干预意见。
        with_edited_data: 阶段一是否携带结构化范围关键词编辑内容。

    Returns:
        阶段名 → 该阶段待执行动作序列的映射。
    """
    approve = "核对无误，通过。"
    return {
        "data_fetch": [
            {
                "stage": "data_fetch",
                "action": "revise",
                "comment": f"补充检索关键词「国产替代」并按新条件重取{topic}数据。",
                "edited_data": (
                    {"action_type": "scope_keywords_refetch", "keywords": ["国产替代"]}
                    if with_edited_data
                    else None
                ),
            },
            {
                "stage": "data_fetch",
                "action": "approve",
                "comment": f"新检索条件下的{topic}数据范围与关键词核对无误，通过。",
                "edited_data": None,
            },
        ],
        "data_interpret": [
            {
                "stage": "data_interpret",
                "action": "revise",
                "comment": "补充专家背景：本报告面向机构投资者，需重点关注国产替代进度与海外厂商竞争格局。",
                "edited_data": None,
            },
            {
                "stage": "data_interpret",
                "action": "approve",
                "comment": "解读结论与专家背景一致，通过。",
                "edited_data": None,
            },
        ],
        "chart_generate": [
            {
                "stage": "chart_generate",
                "action": "approve",
                "comment": "图表类型、单位与数值已核对无误，" + approve,
                "edited_data": None,
            }
        ],
        "chapter_write": [
            {
                "stage": "chapter_write",
                "action": "revise",
                "comment": "第 3 章增加前道环节国产化率的时间序列对比；第 5 章毛利率分析补充同业对比。",
                "edited_data": None,
            },
            {
                "stage": "chapter_write",
                "action": "approve",
                "comment": "章节修订已落实，7 章 21 节结构完整，通过。",
                "edited_data": None,
            },
        ],
        "report_fusion": [
            {
                "stage": "report_fusion",
                "action": "approve",
                "comment": "摘要突出国产替代主线，风险章节补充出口管制敏感性分析后定稿。",
                "edited_data": None,
            }
        ],
    }


class DrillClient:
    """演练客户端：封装运行创建、状态轮询、审核提交与证据导出。"""

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s)
        self._root = base_url.rsplit("/api", 1)[0]
        self.run_id: str | None = None
        self.evidence_dir: Path | None = None
        self.records: list[DrillStep] = []

    async def __aenter__(self) -> "DrillClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        """检查后端健康状态。"""
        async with httpx.AsyncClient(timeout=10.0) as probe:
            resp = await probe.get(f"{self._root}/health")
            resp.raise_for_status()
            return resp.json()

    def _write(self, name: str, payload: Any) -> str:
        """把留证内容写入证据目录（目录未建时自动创建）。"""
        assert self.evidence_dir is not None
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return path.name

    async def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """创建带审核门的运行。"""
        resp = await self._client.post("/runs", json=payload)
        resp.raise_for_status()
        state = resp.json()
        self.run_id = state["run_id"]
        self.evidence_dir = RUNS_DIR / self.run_id / "drill_evidence"
        self._write("00_create_response.json", state)
        return state

    async def get_state(self) -> dict[str, Any]:
        """读取运行状态。"""
        assert self.run_id, "尚未创建运行"
        resp = await self._client.get(f"/runs/{self.run_id}")
        resp.raise_for_status()
        return resp.json()

    async def submit_review(self, action: dict[str, Any]) -> DrillStep:
        """提交一次人工审核动作（携带版本号实现乐观锁）。"""
        assert self.run_id, "尚未创建运行"
        state = await self.get_state()
        rev_before = state.get("revision")
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "stage": action["stage"],
            "action": action["action"],
            "expected_revision": rev_before,
            "comment": action["comment"],
        }
        if action.get("edited_data"):
            payload["edited_data"] = action["edited_data"]

        step = DrillStep(
            stage=action["stage"],
            action=action["action"],
            comment=action["comment"],
            revision_before=rev_before,
            revision_after=None,
            submitted_at=datetime.now().isoformat(timespec="seconds"),
        )

        resp = await self._client.post(f"/runs/{self.run_id}/reviews", json=payload)
        step.status_code = resp.status_code
        if resp.status_code >= 400:
            step.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            print(f"    [!] 提交失败：{step.error}")
            return step

        body = resp.json()
        step.revision_after = body.get("revision")
        if self.evidence_dir is not None:
            idx = len(self.records) + 1
            name = f"{idx:02d}_after_{action['stage']}_{action['action']}.json"
            self._write(name, body)
            step.snapshot_file = name
        print(
            f"    [✓] {STAGE_LABELS.get(action['stage'], action['stage'])} "
            f"动作={action['action']} 版本 rev{rev_before} → rev{body.get('revision')}"
        )
        return step

    async def export_evidence(self) -> None:
        """导出版本历史、反馈历史与事件流。"""
        assert self.run_id, "尚未创建运行"
        for name, path in (
            ("90_revisions.json", f"/runs/{self.run_id}/revisions"),
            ("91_feedback_history.json", f"/runs/{self.run_id}/feedback-history"),
            ("92_events.json", f"/runs/{self.run_id}/events?limit=500"),
        ):
            try:
                resp = await self._client.get(path)
                resp.raise_for_status()
                self._write(name, resp.json())
            except httpx.HTTPError as exc:  # 非致命：留证尽力而为
                print(f"    [!] 导出 {name} 失败：{exc}")

    def write_summary(self, state: dict[str, Any], elapsed_s: float) -> Path | None:
        """生成留证摘要（Markdown 表格形式，便于直接引用）。"""
        if self.evidence_dir is None or not self.evidence_dir.exists():
            return None
        lines = [
            "# 人机协同实操留证摘要",
            "",
            f"- 运行标识：`{self.run_id}`",
            f"- 终态：**{state.get('status')}**（当前阶段 {state.get('current_stage')}）",
            f"- 最终版本号：r{state.get('revision')}",
            f"- 总耗时：{elapsed_s / 60:.1f} 分钟",
            f"- 人工干预次数：{len(self.records)}",
            "",
            "## 人工干预时间线",
            "",
            "| 审核门 | 动作 | 版本变化 | 提交时间 | 结果 |",
            "|---|---|---|---|---|",
        ]
        lines.extend(step.to_row() for step in self.records)
        lines += [
            "",
            "## 五阶段终态",
            "",
            "| 阶段 | 状态 | 版本 |",
            "|---|---|---|",
        ]
        for name, result in (state.get("stage_results") or {}).items():
            lines.append(
                f"| {STAGE_LABELS.get(name, name)} | {result.get('status')} | r{result.get('revision')} |"
            )
        lines += [
            "",
            "## 证据文件",
            "",
        ]
        for p in sorted(self.evidence_dir.iterdir()):
            lines.append(f"- `{p.name}`")
        lines.append("")
        path = self.evidence_dir / "drill_summary.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


async def advance_through_gates(
    client: DrillClient,
    gate_actions: dict[str, list[dict[str, Any]]],
    total_timeout_s: float,
) -> str:
    """按「阶段 → 动作序列」编排推进整条流水线。

    审核门语义决定了编排规则：提交修订类动作后，系统重跑当前阶段并**再次停在
    同一审核门**，需再提交一次通过动作才推进到下一阶段；因此每个阶段的动作
    以「干预 → 通过」成对出现。

    Args:
        client: 演练客户端。
        gate_actions: 阶段名 → 该阶段待执行动作序列。
        total_timeout_s: 整体超时秒数。

    Returns:
        结束原因：``completed``（跑完）、``timeout``（超时）、``terminal``（异常终态）。

    Raises:
        RuntimeError: 运行进入失败类终态。
    """
    cursor: dict[str, int] = {stage: 0 for stage in gate_actions}
    elapsed = 0.0
    tick = 5.0
    last_line = ""

    while elapsed < total_timeout_s:
        state = await client.get_state()
        status = str(state.get("status"))
        current = str(state.get("current_stage") or "")
        line = f"状态={status} 当前阶段={current}"
        if line != last_line:
            print(f"    … {line}（{elapsed / 60:.1f} 分钟）")
            last_line = line

        if status == "completed":
            return "completed"
        if status in {"failed", "cancelled", "blocked", "partial"}:
            raise RuntimeError(f"运行进入 {status} 终态，演练中止")

        if status == "waiting_review":
            queue = gate_actions.get(current)
            if queue and cursor[current] < len(queue):
                action = queue[cursor[current]]
                cursor[current] += 1
            else:
                # 该阶段编排已用尽却仍停在审核门：提交通过动作兜底推进
                action = {
                    "stage": current,
                    "action": "approve",
                    "comment": "阶段内容核对无误，通过。",
                    "edited_data": None,
                }
            print(
                f"    → 提交：{STAGE_LABELS.get(current, current)} · {action['action']}"
                f"｜{action['comment'][:34]}…"
            )
            client.records.append(await client.submit_review(action))

        await asyncio.sleep(tick)
        elapsed += tick
    return "timeout"


async def run_drill(args: argparse.Namespace) -> int:
    """执行完整演练流程。"""
    gate_actions = build_gate_actions(args.topic, with_edited_data=args.with_edited_data)
    if args.only:
        keep = {s.strip() for s in args.only.split(",") if s.strip()}
        gate_actions = {k: v for k, v in gate_actions.items() if k in keep}

    payload = {
        "project_id": args.project_id,
        "input_data": {
            "industry_topic": args.topic,
            "market_scope": args.market_scope,
            "security_types": ["股票"],
            "reporting_currency": "CNY",
            "research_as_of": args.as_of,
            "focus_questions": [
                f"{args.topic}产业链核心环节代表性上市公司与产业分工",
                f"{args.topic}核心A股标的的营收规模、盈利质量、毛利率、净利率、ROE、资产负债率及估值水平",
                f"{args.topic}行业发展驱动因素、政策催化、市场规模演进与潜在投资风险",
            ],
            "analysis_depth": args.depth,
            "risk_preference": "balanced",
        },
        "review_stages": REVIEW_STAGES,
    }

    if args.dry_run:
        print("演练计划（dry-run，未调用任何接口）")
        print(f"  主题：{args.topic}｜深度：{args.depth}｜基准日：{args.as_of}")
        print(f"  审核门：{REVIEW_STAGES}")
        print("  动作编排（干预 → 通过 成对，因修订后需再次确认才推进）：")
        for stage, queue in gate_actions.items():
            seq = " → ".join(f"{a['action']}" for a in queue)
            print(f"    - {STAGE_LABELS.get(stage, stage)}：{seq}")
        return 0

    started = asyncio.get_event_loop().time()
    async with DrillClient(args.base_url, args.timeout) as client:
        print("[0/5] 检查后端健康状态 …")
        print(f"      {await client.health()}")
        print("[1/5] 创建运行（带四个审核门）…")
        state = await client.create_run(payload)
        print(f"      run_id={client.run_id}  初始阶段={state.get('current_stage')}")
        print("[2/5] 沿流水线推进并逐门提交人工干预 …")
        try:
            reason = await advance_through_gates(client, gate_actions, args.stage_timeout)
            print(f"      推进结束：{reason}")
        except RuntimeError as exc:
            print(f"    [!] {exc}")

        print("[3/5] 读取终态 …")
        final_state = await client.get_state()
        print("[4/5] 导出版本历史、反馈历史、事件流 …")
        await client.export_evidence()
        elapsed = asyncio.get_event_loop().time() - started
        print("[5/5] 生成留证摘要 …")
        summary = client.write_summary(final_state, elapsed)

    print("\n演练结束")
    print(f"  run_id   : {client.run_id}")
    print(f"  终态     : {final_state.get('status')}（{final_state.get('current_stage')}）")
    print(f"  干预次数 : {len(client.records)}")
    print(f"  留证目录 : {client.evidence_dir}")
    if summary:
        print(f"  摘要文件 : {summary}")
    return 0


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="人机协同实操演练留证脚本")
    parser.add_argument("--topic", default="半导体设备", help="行业主题")
    parser.add_argument("--project-id", default="audit-drill", help="项目标识")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1", help="后端 API 前缀")
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y-%m-%d"), help="研究基准日 YYYY-MM-DD")
    parser.add_argument("--depth", choices=["standard", "deep"], default="standard", help="分析深度")
    parser.add_argument("--market-scope", nargs="+", default=["中国 A 股"], help="市场范围")
    parser.add_argument("--only", default="", help="只演练指定阶段（逗号分隔，如 data_interpret,chapter_write）")
    parser.add_argument("--with-edited-data", action="store_true", help="阶段一携带结构化范围关键词编辑内容")
    parser.add_argument("--stage-timeout", type=float, default=1800.0, help="单个审核门等待超时（秒）")
    parser.add_argument("--timeout", type=float, default=120.0, help="单次 HTTP 请求超时（秒）")
    parser.add_argument("--dry-run", action="store_true", help="只打印演练计划，不调用接口")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_drill(parse_args())))
