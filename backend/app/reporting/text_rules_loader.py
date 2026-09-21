"""Load the canonical public-text rules from the report-page-composer skill.

## 为什么要有这一层

正文净化的词表只有一份，在
`skills/report-page-composer/scripts/text_rules.py`（见该模块文档的收敛记录）。
后端不复制它，而是按路径加载 —— 复制正是 2026-09-18 三份词表漂移事故的成因。

## 与 app/agents/data_interpreter/skill_loader.py 的关键差异

那个 loader 是**fail-closed**：skill 文件缺失或哈希不符就抛 `RuntimeError`。
本 loader 是 **fail-open**，因为 Agent 5 的硬约束 #3 规定
「模型/工具失败必须静默回退，不得阻断生成」。

所以 skill 文件读不到时：

    * 不抛异常、不阻断 —— 报告照常生成；
    * 退化为「只做机器 ID 人性化」的兜底净化（`humanize_internal_ids`），
      **不内联一份词表副本**（内联副本会立刻重新制造漂移）；
    * 通过 `text_rules_issue_codes()` 上报 `report_skill_text_rules_missing`，
      该代码进入 `/health/ready` 的 `issues`，并在渲染产物里留下风险记录。

兜底模式下管线语言与内部状态码不会被清理，genre 审计的
`INTERNAL_PROCESS_LANGUAGE` 会因此报 major —— 这是**有意为之**：
失败必须被门禁看见，而不是被静默的副本掩盖。

## 指纹

真源导出的 `RULES_FINGERPRINT` 会被原样带出。渲染器与审计各自读同一份文件时
指纹必然相同；指纹不同只可能来自"有人又存了一份副本"。测试用
`assert_single_source_of_truth()` 把这条纪律变成断言。
"""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

# backend/app/reporting/text_rules_loader.py → parents[3] = 仓库根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SKILL_SCRIPTS_DIR = _PROJECT_ROOT / "skills" / "report-page-composer" / "scripts"
_TEXT_RULES_FILENAME = "text_rules.py"
_MODULE_NAME = "_backend_canonical_text_rules"

ENV_SCRIPTS_DIR = "REPORT_PAGE_COMPOSER_SCRIPTS"

ISSUE_TEXT_RULES_MISSING = "report_skill_text_rules_missing"
ISSUE_TEXT_RULES_UNUSABLE = "report_skill_text_rules_unusable"


@dataclass(frozen=True, slots=True)
class TextRules:
    """Resolved public-text rules plus provenance for diagnostics."""

    sanitize_public: Callable[[str], str]
    machine_field_map: Mapping[str, str]
    pipeline_phrase_res: tuple[tuple[Any, str], ...]
    prose_rules: tuple[tuple[Any, str], ...]
    status_code_map: Mapping[str, str]
    filler_res: tuple[Any, ...]
    fingerprint: str
    source: str
    path: str | None
    issue_code: str | None

    @property
    def is_canonical(self) -> bool:
        """True when the skill file was loaded (not the degraded fallback)."""

        return self.source == "skill"


def _candidate_scripts_dirs() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get(ENV_SCRIPTS_DIR)
    if override:
        candidates.append(Path(override).expanduser().resolve())
    candidates.append(_SKILL_SCRIPTS_DIR)
    return candidates


def resolve_text_rules_path() -> Path | None:
    """Return the canonical skill file path, or None when it is absent."""

    for directory in _candidate_scripts_dirs():
        candidate = directory / _TEXT_RULES_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # 真源是纯标准库实现，按路径执行即可；注册进 sys.modules 让 dataclass/typing 正常解析。
    import sys

    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _fallback_rules(issue_code: str, path: Path | None) -> TextRules:
    """Degraded sanitizer: machine IDs only, no inlined copy of the word list."""

    from app.reporting.presentation import humanize_internal_ids

    def sanitize_public(value: str) -> str:
        return humanize_internal_ids(value) if value else value

    logger.error(
        "public-text rules unavailable (%s); falling back to ID-only sanitisation. "
        "Pipeline phrases and internal status codes will NOT be rewritten. path=%s",
        issue_code,
        path,
    )
    return TextRules(
        sanitize_public=sanitize_public,
        machine_field_map={},
        pipeline_phrase_res=(),
        prose_rules=(),
        status_code_map={},
        filler_res=(),
        fingerprint="",
        source="fallback",
        path=str(path) if path else None,
        issue_code=issue_code,
    )


def _build() -> TextRules:
    path = resolve_text_rules_path()
    if path is None:
        return _fallback_rules(ISSUE_TEXT_RULES_MISSING, None)
    try:
        module = _load_module(path)
        return TextRules(
            sanitize_public=module.sanitize_public,
            machine_field_map=dict(module.MACHINE_FIELD_MAP),
            pipeline_phrase_res=tuple(module.PIPELINE_PHRASE_RES),
            prose_rules=tuple(getattr(module, "PROSE_RULES", ())),
            status_code_map=dict(module.STATUS_CODE_MAP),
            filler_res=tuple(module.FILLER_RES),
            fingerprint=str(module.RULES_FINGERPRINT),
            source="skill",
            path=str(path),
            issue_code=None,
        )
    except Exception:  # noqa: BLE001 - fail open by contract, but say so loudly
        logger.exception("failed to load canonical text rules from %s", path)
        return _fallback_rules(ISSUE_TEXT_RULES_UNUSABLE, path)


@lru_cache(maxsize=1)
def get_text_rules() -> TextRules:
    """Return the cached canonical rules (never raises)."""

    return _build()


def reset_text_rules_cache() -> None:
    """Drop the cache so tests can exercise env overrides and fallback paths."""

    get_text_rules.cache_clear()


def sanitize_public(text: str) -> str:
    """Canonical word-list entry point (no machine-ID pre-pass)."""

    return get_text_rules().sanitize_public(text)


def sanitize_for_render(value: str) -> str:
    """渲染层的唯一净化入口 —— HTML 与 Markdown 都必须走这里。

    两步，顺序不可颠倒：

    1. `humanize_internal_ids` 把 `E-…`/`SEC-…`/`DQ-…` 等**替换为占位词**
       （「相关证据」「相关小节」），保留句子的可读性；
    2. 唯一词表 `sanitize_public` 处理内部工件名、管线语言、状态码与数值精度。

    2026-09-18 之前只有 HTML 走两步、Markdown 只走第 1 步，
    于是同一份 ReportViewModel 在两种格式里得到不同的对外文本。
    """

    if not value:
        return value
    from app.reporting.presentation import humanize_internal_ids

    return get_text_rules().sanitize_public(humanize_internal_ids(value))


def text_rules_issue_codes() -> list[str]:
    """Non-fatal readiness codes; empty when the canonical file loaded."""

    rules = get_text_rules()
    return [rules.issue_code] if rules.issue_code else []


def text_rules_status() -> dict[str, Any]:
    """Diagnostics payload for readiness responses and QA reports."""

    rules = get_text_rules()
    return {
        "source": rules.source,
        "path": rules.path,
        "fingerprint": rules.fingerprint,
        "canonical": rules.is_canonical,
        "machine_field_rules": len(rules.machine_field_map),
        "pipeline_rules": len(rules.pipeline_phrase_res),
        "prose_rules": len(rules.prose_rules),
        "status_codes": len(rules.status_code_map),
        "issue": rules.issue_code,
    }
