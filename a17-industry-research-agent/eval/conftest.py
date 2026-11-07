"""eval 包 pytest 装配（EVALUATION_PLAN §5.1「conftest 自动发现→pytest 参数化」）。

- 将 ``backend/`` 加入 sys.path，使 eval 代码可 import ``app.*``。
- 从 cases/*.json 加载用例（项目未引入 pyyaml，为避免新增重依赖，用 JSON
  承载与 §5.1 YAML schema 等价的字段；见核对清单 #格式替代说明）。
- 提供 group 门禁常量，对应 §6.2 门禁矩阵。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402

CASES_DIR = Path(__file__).resolve().parent / "cases"


def load_json_cases(name: str) -> list[dict]:
    path = CASES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def intent_golden_cases() -> list[dict]:
    """15 条 I 类金标准用例（intent_golden.json）。"""
    return load_json_cases("intent_golden.json")


@pytest.fixture(scope="session")
def cases_v1() -> list[dict]:
    """50 E2E + 12 T + 24 专项用例（cases_v1.json）。"""
    return load_json_cases("cases_v1.json")


@pytest.fixture(scope="session")
def baselines() -> dict:
    """确定性计算 10 组基准（baselines.json）。"""
    data = json.loads((CASES_DIR / "baselines.json").read_text(encoding="utf-8"))
    return {item["key"]: item for item in data.get("baselines", [])}


# §6.2 group 门禁矩阵（PR / 周 / 发版）
GROUP_GATES = {
    "intent_routing": {"pr_pass_at_1": 1.0, "release_pass_star_3": 0.95},
    "core_calc": {"pr_pass_at_1": 1.0, "release_pass_star_5": 1.0},
    "intercept": {"pr_pass_at_1": 1.0, "release_pass_star_5": 1.0},
    "tool_planning": {"pr_pass_at_1": 1.0},
    "full": {"weekly_pass_at_3": 0.90, "release_pass_star_3": 0.95},
}


def group_for_case(case: dict) -> str:
    return case.get("group", "full")