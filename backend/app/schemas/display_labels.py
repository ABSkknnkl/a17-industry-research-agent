"""展示用中文标签（display labels）。

唯一来源：`contracts/display-labels.json`。

设计要点：
1. 终端用户看不懂 `hithink_industry_query`、`insufficient` 这类内部标识，
   所有展示值必须由后端下发中文，前端不再自己维护映射。
2. 契约文件缺失或取值未收录时，**回退显示原始标识**而不是抛异常——
   标签是展示层的事，绝不能让整个 Pipeline 因为少一行映射而失败。
3. 新增技能 / 维度时改 `contracts/display-labels.json` 即可，
   前后端同步生效，不需要改两处代码。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# backend/app/schemas/display_labels.py -> parents[3] == 仓库根
CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "display-labels.json"

SKILLS = "skills"
DIMENSIONS = "dimensions"
COVERAGE_STATUS = "coverage_status"
EVIDENCE_CATEGORIES = "evidence_categories"


@lru_cache(maxsize=1)
def _sections() -> dict[str, dict[str, str]]:
    """加载契约文件并缓存。任何异常都退化成空映射。"""
    try:
        raw: Any = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _lookup(section: str, value: str | None) -> str:
    """查中文标签；查不到就原样返回，保证不丢信息。"""
    if not value:
        return ""
    return _sections().get(section, {}).get(str(value)) or str(value)


def skill_label(skill: str | None) -> str:
    """数据技能标识 → 中文名（如 hithink_industry_query → 行业数据）。"""
    return _lookup(SKILLS, skill)


def dimension_label(dimension: str | None) -> str:
    """分析维度 → 中文名（如 macro_policy → 宏观政策）。"""
    return _lookup(DIMENSIONS, dimension)


def coverage_status_label(status: str | None) -> str:
    """维度覆盖状态 → 中文（如 insufficient → 数据不足）。"""
    return _lookup(COVERAGE_STATUS, status)


def evidence_category_label(category: str | None) -> str:
    """证据来源类型 → 中文（如 opinion → 公开观点）。"""
    return _lookup(EVIDENCE_CATEGORIES, category)


def reload() -> None:
    """测试或热更新时手动清缓存。"""
    _sections.cache_clear()
