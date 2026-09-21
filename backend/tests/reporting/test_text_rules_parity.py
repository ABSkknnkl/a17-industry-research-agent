"""正文净化「唯一入口」的机械防线。

2026-09-18 的事故是**同一套词表存在三份副本**，各自演化：

    ① skills/report-page-composer/scripts/text_rules.py   （完整，含 sanitize_public）
    ② skills/report-style-benchmark/scripts/text_rules.py （"精简自"① 的过时副本）
    ③ backend/app/reporting/html.py::_PUBLIC_TEXT_RULES    （23 条独立正则，措辞还不一样）

后果是发出去的 PDF 里带着 `competition · partial`、`unavailable`、`data_fetch`、
`UNSUPPORTED-METRICS`，以及 81 处 3 位以上小数 —— 因为渲染器压根没接状态码表和精度表，
而体裁审计的 INTERNAL_PROCESS_LANGUAGE 只查 MACHINE_FIELD_MAP + PIPELINE_PHRASE_RES，
**结构上看不见这两类泄漏**。

收敛后只剩一份真源。本文件把这个事实变成断言：谁再存副本、谁再把某一端接错，测试就红。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from app.reporting import markdown as markdown_module
from app.reporting import text_rules_loader
from app.reporting.html import sanitize_public_text

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_COMPOSER_SCRIPTS = _PROJECT_ROOT / "skills" / "report-page-composer" / "scripts"
_BENCHMARK_SCRIPTS = _PROJECT_ROOT / "skills" / "report-style-benchmark" / "scripts"

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# 真源里的表名：后端重新定义其中任何一个都等于又开了一份副本
_WORD_LIST_TABLE_NAMES = (
    "MACHINE_FIELD_MAP",
    "PIPELINE_PHRASE_RES",
    "PROSE_RULES",
    "STATUS_CODE_MAP",
    "STATUS_CHAIN_RE",
    "FILLER_RES",
    "BARE_CODE_RE",
    "PAREN_CODE_RE",
    "HIGH_PRECISION_PCT_RE",
    "YUAN_AMOUNT_RE",
    "BIG_BARE_NUMBER_RE",
    "DECIMALS_3PLUS_RE",
)

# 真源里的替换目标（选了几条措辞独特、不会自然出现在别处的）
_WORD_LIST_TARGETS = ("竞争格局", "部分支持", "数据限制清单", "质量校验")


def _string_literals(source: str) -> list[str]:
    """取出所有字符串字面量，**排除注释与文档串**。

    注释里举例说明「原先有 _PUBLIC_TEXT_RULES」是合法的，不该被判成副本；
    但把替换目标写进真正的字符串（例如又建一张 dict）就是副本。
    """

    tree = ast.parse(source)
    docstrings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            found = ast.get_docstring(node, clean=False)
            if found is not None:
                docstrings.add(found)

    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            literals.append(node.value)
    return literals


def _load_module_from_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _fresh_rules_cache():
    """每个用例都从冷缓存开始，避免 lru_cache 串味。"""

    text_rules_loader.reset_text_rules_cache()
    yield
    text_rules_loader.reset_text_rules_cache()


# ---------------------------------------------------------------------------
# 1. 真源可加载
# ---------------------------------------------------------------------------
def test_loader_resolves_the_canonical_skill_file() -> None:
    rules = text_rules_loader.get_text_rules()

    assert rules.source == "skill", f"退化到兜底词表了：{rules.issue_code}"
    assert rules.is_canonical is True
    assert rules.issue_code is None
    assert text_rules_loader.text_rules_issue_codes() == []

    assert rules.path is not None
    assert Path(rules.path) == _COMPOSER_SCRIPTS / "text_rules.py"
    assert Path(rules.path).is_file()

    assert _HEX64_RE.match(rules.fingerprint), rules.fingerprint


def test_loader_exposes_the_whole_word_list_not_just_sanitize() -> None:
    """渲染器缺任何一张表都会复现原始缺陷，所以逐表断言非空。"""

    rules = text_rules_loader.get_text_rules()

    assert len(rules.machine_field_map) >= 15
    assert len(rules.pipeline_phrase_res) >= 6
    assert len(rules.prose_rules) >= 8, "PROSE_RULES 是从 html.py 迁过来的那 9 条"
    assert len(rules.status_code_map) >= 12, "状态码表缺失 = PDF 里重现 competition · partial"
    assert len(rules.filler_res) >= 3


# ---------------------------------------------------------------------------
# 2. 副本已被消灭（这才是收敛的核心）
# ---------------------------------------------------------------------------
def test_benchmark_skill_is_a_shim_not_a_copy() -> None:
    """② 必须是转发 ① 的 shim —— 指纹相同即证明没有第二份内容。"""

    canonical = text_rules_loader.get_text_rules()
    shim = _load_module_from_path(
        _BENCHMARK_SCRIPTS / "text_rules.py", "_parity_benchmark_text_rules"
    )

    assert shim.RULES_FINGERPRINT == canonical.fingerprint
    assert shim.STATUS_CODE_MAP == canonical.status_code_map
    assert shim.PROSE_RULES == canonical.prose_rules
    assert shim.MACHINE_FIELD_MAP == canonical.machine_field_map
    # shim 不是自己的实现：它把 sanitize_public 直接指过去
    assert shim.sanitize_public is not None
    assert shim.sanitize_public("competition · partial") == "竞争格局 · 部分支持"


def test_benchmark_shim_file_contains_no_inline_word_list() -> None:
    """shim 里不该再出现任何一条具体的替换目标。"""

    source = (_BENCHMARK_SCRIPTS / "text_rules.py").read_text(encoding="utf-8")

    for leaked in ("竞争格局", "部分支持", "数据限制清单", "质量校验"):
        assert leaked not in source, f"shim 里出现了词表内容：{leaked}"


def test_backend_holds_no_second_word_list() -> None:
    """③ 的墓碑：html.py 不得再出现 _PUBLIC_TEXT_RULES，后端也不得重新定义任何一张词表。

    两层检测，避免把注释里的举例当成副本：
      * 结构层 —— 不得再出现词表表名的**定义**（`NAME =` / `NAME:`）；
      * 内容层 —— 不得在任何**字符串字面量**里出现替换目标（注释与文档串豁免）。
    """

    html_source = (_PROJECT_ROOT / "backend" / "app" / "reporting" / "html.py").read_text(
        encoding="utf-8"
    )
    # 墓碑注释里可以提到这个名字，但不允许再出现「定义」
    assert not re.search(r"^_PUBLIC_TEXT_RULES\s*[:=]", html_source, re.MULTILINE)
    assert "_PUBLIC_TEXT_RULES: tuple" not in html_source

    # 结构层：所有模块都不得定义词表 —— 包括 presentation.py。
    # 内容层：presentation.py 持有的是**结构化字段标签**（DIMENSION_LABELS 等），
    #         它与词表的重叠部分由 test_status_wording_matches_presentation_labels
    #         保证同词，所以内容层对它豁免；text_rules_loader.py 只消费不定义。
    reporting_dir = _PROJECT_ROOT / "backend" / "app" / "reporting"
    content_exempt = {"presentation.py", "text_rules_loader.py"}

    structural: list[str] = []
    content: list[str] = []
    for path in sorted(reporting_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")

        for table in _WORD_LIST_TABLE_NAMES:
            if re.search(rf"^{table}\s*[:=]", source, re.MULTILINE):
                structural.append(f"{path.name}: {table}")

        if path.name in content_exempt:
            continue
        for literal in _string_literals(source):
            for leaked in _WORD_LIST_TARGETS:
                if leaked in literal:
                    content.append(f"{path.name}: {leaked}")

    assert structural == [], f"后端重新定义了词表：{structural}"
    assert content == [], f"后端字符串里内联了词表内容：{content}"


def test_presentation_layer_owns_labels_but_not_the_word_list() -> None:
    """分层边界：presentation.py 是**结构化字段标签**的归属地，不是词表的第二份。

    它合法持有 DIMENSION_LABELS / COVERAGE_STATUS_LABELS / CHECK_STATUS_LABELS，
    这些是模板渲染表格时用的标签；词表的重叠部分必须与它同词
    （见 test_status_wording_matches_presentation_labels）。
    但它**不得**定义 MACHINE_FIELD_MAP / STATUS_CODE_MAP 这类净化词表。
    """

    source = (_PROJECT_ROOT / "backend" / "app" / "reporting" / "presentation.py").read_text(
        encoding="utf-8"
    )

    for table in _WORD_LIST_TABLE_NAMES:
        assert not re.search(rf"^{table}\s*[:=]", source, re.MULTILINE), (
            f"presentation.py 定义了净化词表 {table} —— 词表只能有一份"
        )

    # humanize_internal_ids 只处理机器编号，不处理措辞
    assert "humanize_internal_ids" in source
    assert "def sanitize_public" not in source


# ---------------------------------------------------------------------------
# 3. 渲染层：HTML 与 Markdown 必须给出同一段对外文本
# ---------------------------------------------------------------------------
# 逐字取自交付 PDF 的 figcaption。Agent 2 的对账决定（"本条被降级"）与处理建议
# （"处理：核实…"）是内部处置语，不该出现在读者可见的图注里；它同时把图注撑过
# 两行、触发 CAPTION_OVERLOAD。
_DISPOSITION_LEAK = (
    "同数据点多条证据值不一致，已择优保留E-07（法定审计与信息丰富度优先），"
    "本条被降级；处理：核实两来源口径差异后保留其一或单独说明。"
)

_LEAKY_SAMPLES = (
    "研究维度共 5 项；代表项：competition · partial、growth · partial、macro_policy · partial",
    "状态：unavailable、warning",
    "上游环节 data_fetch · UNSUPPORTED-METRICS 未通过校验。",
    "组件出口均价为2.5534美元/个，环比增长5.1848%。",
    "相关缺口见missing_inputs，另见 DQ-03 与 E-07、SEC-02-01。",
    "数据解读智能体给出的结论与章节撰写智能体不一致。",
    # 2026-09-18 实测交付图注（Agent 2 对账决定 + 处理建议原样落到 figcaption）
    _DISPOSITION_LEAK,
)


@pytest.mark.parametrize("sample", _LEAKY_SAMPLES)
def test_markdown_and_html_agree_on_sanitized_text(sample: str) -> None:
    """2026-09-18 之前 markdown.py 只做 humanize_internal_ids、从不走词表。"""

    html_text = sanitize_public_text(sample)
    md_text = markdown_module._safe(sample)  # noqa: SLF001 - 这正是出过缺口的那一层

    # _safe 额外做 HTML 转义；这些样本不含尖括号，因此应当逐字相同
    assert "<" not in sample and ">" not in sample
    assert md_text == html_text, f"MD/HTML 口径不一致\n  MD : {md_text}\n  HTML: {html_text}"


def test_markdown_still_escapes_angle_brackets() -> None:
    """共用净化入口不等于放弃转义。"""

    assert markdown_module._safe("A<B>C") == "A&lt;B&gt;C"  # noqa: SLF001


# ---------------------------------------------------------------------------
# 4. 泄漏确实被消除（行为断言，对应真实事故）
# ---------------------------------------------------------------------------
def test_internal_status_codes_are_humanized() -> None:
    out = sanitize_public_text(
        "代表项：competition · partial、growth · partial、macro_policy · partial"
    )

    for token in ("competition", "macro_policy", "growth", "partial"):
        assert token not in out, out
    assert "竞争格局" in out
    assert "部分支持" in out


def test_standalone_status_codes_are_humanized() -> None:
    """`unavailable、warning` 是「孤立码」形态，链式正则必须也能命中。"""

    out = sanitize_public_text("状态：unavailable、warning")

    assert "unavailable" not in out, out
    assert "warning" not in out, out


def test_pipeline_and_artifact_language_is_rewritten() -> None:
    out = sanitize_public_text("上游环节 data_fetch · UNSUPPORTED-METRICS 未通过校验。")

    assert "data_fetch" not in out, out
    assert "UNSUPPORTED-METRICS" not in out, out


def test_high_precision_decimals_are_capped() -> None:
    out = sanitize_public_text("组件出口均价为2.5534美元/个，环比增长5.1848%。")

    assert "2.5534" not in out, out
    assert "5.1848" not in out, out
    assert "2.55" in out and "5.18" in out


def test_machine_identifiers_never_reach_the_reader() -> None:
    out = sanitize_public_text("相关缺口见missing_inputs，另见 DQ-03 与 E-07、SEC-02-01。")

    for token in ("missing_inputs", "DQ-03", "E-07", "SEC-02-01"):
        assert token not in out, out


def test_internal_disposition_language_never_reaches_the_reader() -> None:
    """Agent 2 的对账决定与处理建议不得出现在读者可见文本里。

    实测来源：交付 PDF 的 figcaption。图注按体裁判据只保留「短来源 + 必要口径」。
    """

    out = sanitize_public_text(_DISPOSITION_LEAK)

    for token in ("本条被降级", "已择优保留", "法定审计", "信息丰富度", "处理："):
        assert token not in out, f"{token} 仍在: {out}"

    # 保留一条可读的口径说明，而不是把整句删空
    assert "口径不一致" in out, out
    assert len(out) < len(_DISPOSITION_LEAK) / 2, f"未有效压缩: {out}"


@pytest.mark.parametrize("sample", _LEAKY_SAMPLES)
def test_sanitization_is_idempotent(sample: str) -> None:
    """替换目标自己不得命中任何规则，否则二次渲染会继续变形。"""

    once = sanitize_public_text(sample)
    assert sanitize_public_text(once) == once


# ---------------------------------------------------------------------------
# 4b. 措辞一致性：同一状态码在「正文」与「结构化表格」里必须同词
# ---------------------------------------------------------------------------
def test_status_wording_matches_presentation_labels() -> None:
    """第二次收敛的机械防线。

    2026-09-18 实测：同一份交付 PDF 里 `partial` 同时渲染为「部分支持」(×5) 与
    「部分覆盖」(×6)，`warning` 为「需要复核」(×1) 与「存在警告」(×2)，
    `unavailable` 为「资料不足」(×3) 与「数据不可得」(×2) —— 因为结构化表格走
    presentation.py 的标签表、正文走 STATUS_CODE_MAP，两套措辞各写各的。

    两边只要共享同一个 token，措辞就必须逐字相同。
    """

    from app.reporting.presentation import (
        CHECK_STATUS_LABELS,
        COVERAGE_STATUS_LABELS,
        DIMENSION_LABELS,
    )

    rules = text_rules_loader.get_text_rules()
    structured = {
        **COVERAGE_STATUS_LABELS,
        **CHECK_STATUS_LABELS,
        **DIMENSION_LABELS,
    }

    overlaps = sorted(set(structured) & set(rules.status_code_map))
    assert overlaps, "两张表已不再重叠 —— 本测试失去意义，请复核收敛方向"

    disagreements = {
        token: (structured[token], rules.status_code_map[token])
        for token in overlaps
        if structured[token] != rules.status_code_map[token]
    }

    assert disagreements == {}, (
        "同一状态码出现两种中文措辞（结构化标签 vs 正文词表）："
        f"{disagreements}"
    )


def test_status_codes_do_not_match_inside_longer_ascii_identifiers() -> None:
    """边界硬化：状态码是 ASCII 标识符，不能切进更长的标识符内部。

    没有这条，新增的 `supported` 会把 `unsupported` 改成 `un证据充分`，
    `growth` 会把 `growth_rate` 改成 `行业增长_rate`，`risk` 会切进 `asterisk`。
    """

    samples = {
        "unsupported": "unsupported",
        "growth_rate": "growth_rate",
        "asterisk": "asterisk",
        "partial_ratio": "partial_ratio",
    }

    for token, sample in samples.items():
        out = sanitize_public_text(sample)
        assert out == sample, f"{token!r} 被误切：{sample!r} → {out!r}"

    # 但中文标点 / 空格 / 行首行尾旁仍然必须命中
    assert sanitize_public_text("状态：unavailable") == "状态：资料不足"
    assert sanitize_public_text("(partial)") == "(部分支持)"
    assert sanitize_public_text("partial") == "部分支持"


# ---------------------------------------------------------------------------
# 5. fail-open：Agent 5 硬约束 #3
# ---------------------------------------------------------------------------
def test_missing_skill_file_degrades_loudly_but_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """skill 文件缺失 → 报告照常生成，但 readiness 必须报出来。

    兜底只覆盖「机器 ID → 占位词」这一层（`humanize_internal_ids`），
    词表那一层（内部工件名、管线语言、状态码、精度）**故意不覆盖** ——
    因为覆盖它就得内联副本，而副本正是本次事故的成因。
    所以降级边界必须被断言清楚：宁可让门禁看见 major，也不要静默的副本。
    """

    monkeypatch.setattr(text_rules_loader, "_SKILL_SCRIPTS_DIR", tmp_path / "nope")
    monkeypatch.setenv(text_rules_loader.ENV_SCRIPTS_DIR, str(tmp_path / "also-nope"))
    text_rules_loader.reset_text_rules_cache()

    rules = text_rules_loader.get_text_rules()

    assert rules.source == "fallback"
    assert rules.is_canonical is False
    assert rules.issue_code == text_rules_loader.ISSUE_TEXT_RULES_MISSING
    assert text_rules_loader.text_rules_issue_codes() == [
        text_rules_loader.ISSUE_TEXT_RULES_MISSING
    ]

    # 兜底仍然处理的：机器 ID → 占位词（且绝不抛异常）
    out = text_rules_loader.sanitize_for_render("见 SEC-02-01、E-07 与 DQ-03。")
    assert isinstance(out, str)
    for machine_id in ("SEC-02-01", "E-07", "DQ-03"):
        assert machine_id not in out, out

    # 兜底故意不处理的：词表那一层。降级必须"响亮"，不能悄悄糊过去。
    degraded = text_rules_loader.sanitize_for_render("代表项：competition · partial")
    assert "competition" in degraded, "兜底不该改写词表内容 —— 那意味着又内联了一份副本"


def test_unusable_skill_file_reports_a_distinct_issue_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """文件在但读不动 → 与「缺失」区分开，否则排障时会找错方向。"""

    broken = tmp_path / "text_rules.py"
    broken.write_text("this is not valid python !!!\n", encoding="utf-8")
    monkeypatch.setattr(
        text_rules_loader, "resolve_text_rules_path", lambda: broken
    )
    text_rules_loader.reset_text_rules_cache()

    rules = text_rules_loader.get_text_rules()

    assert rules.source == "fallback"
    assert rules.issue_code == text_rules_loader.ISSUE_TEXT_RULES_UNUSABLE
    assert text_rules_loader.text_rules_issue_codes() == [
        text_rules_loader.ISSUE_TEXT_RULES_UNUSABLE
    ]


def test_fallback_does_not_inline_a_word_list() -> None:
    """兜底若内联副本，收敛当场失效 —— 用源码断言钉死。"""

    source = (
        _PROJECT_ROOT / "backend" / "app" / "reporting" / "text_rules_loader.py"
    ).read_text(encoding="utf-8")

    for leaked in ("竞争格局", "部分支持", "数据限制清单", "质量校验"):
        assert leaked not in source, f"兜底里内联了词表内容：{leaked}"


# ---------------------------------------------------------------------------
# 6. readiness 接线
# ---------------------------------------------------------------------------
def test_readiness_status_payload_is_diagnostic_friendly() -> None:
    status = text_rules_loader.text_rules_status()

    assert status["canonical"] is True
    assert status["source"] == "skill"
    assert status["issue"] is None
    assert _HEX64_RE.match(status["fingerprint"])
    assert status["status_codes"] >= 12
    assert status["prose_rules"] >= 8


def test_ready_endpoint_surfaces_text_rules_issues(api_client) -> None:
    """/health/ready 的 issues 必须来自 text_rules_issue_codes()，而不是写死空列表。"""

    response = api_client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert "issues" in payload
    # 正常情况下真源可加载，issues 为空；关键是这个字段确实被接线了
    assert payload["issues"] == []
