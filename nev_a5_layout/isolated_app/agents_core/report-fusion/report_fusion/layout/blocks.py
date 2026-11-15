"""P1 · 结构化块最小形状与硬校验。

方案 §3-P1：LayoutDocument(schema_version, theme, content_sha256, blocks, assets)；
每块有 id, kind, source_ref；标题补 level，段落保存原文与引文，图表保存
asset_id，表格保存表头、行、单位和来源。重复 ID、非法标题层级、挂图引用
不存在或双挂接直接失败。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = "1.0"

KINDS = frozenset({
    "cover", "toc", "heading", "paragraph", "list", "quote", "conclusion",
    "claim", "figure", "table", "note", "appendix", "page_break", "cite", "raw",
})
HEADING_LEVEL_MIN, HEADING_LEVEL_MAX = 1, 4
BLOCKER = "blocker"
WARNING = "warning"


class LayoutValidationError(ValueError):
    """布局 AST 不合法，禁止进入排版与发布。"""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        codes = ", ".join(sorted({x["code"] for x in issues if x["severity"] == BLOCKER}))
        super().__init__(f"LayoutDocument 校验失败: {codes} ({len(issues)} 条)")


def make_block_id(section_id: str | None, kind: str, ordinal: int) -> str:
    """ID 由章节/节的稳定标识与块的源位置序号生成，可复算、不依赖随机值。"""
    base = re.sub(r"[^A-Za-z0-9_-]", "-", section_id or "doc").strip("-") or "doc"
    if kind not in KINDS:
        raise ValueError(f"未知块类型: {kind}")
    return f"{base}:{kind}:{ordinal:04d}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Asset:
    asset_id: str
    path: str
    sha256: str | None = None
    media_type: str | None = None
    note: str | None = None
    origin: str | None = None


@dataclass
class Block:
    id: str
    kind: str
    source_ref: str
    section_id: str | None = None
    level: int | None = None
    text: str | None = None
    raw_html: str | None = None
    quote: str | None = None
    asset_id: str | None = None
    headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    unit: str | None = None
    source: str | None = None
    note: str | None = None
    number: str | None = None
    title: str | None = None
    placement_section_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayoutDocument:
    schema_version: str = SCHEMA_VERSION
    theme: str = "a5_nev"
    content_sha256: str = ""
    blocks: list[Block] = field(default_factory=list)
    assets: dict[str, Asset] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def validate(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []

        def fail(code: str, detail: str, block_id: str | None = None,
                 severity: str = BLOCKER):
            issues.append({"code": code, "severity": severity,
                           "block_id": block_id, "detail": detail})

        if self.schema_version != SCHEMA_VERSION:
            fail("SCHEMA_MISMATCH", f"schema_version={self.schema_version!r}")
        if not self.content_sha256:
            fail("CONTENT_HASH_MISSING", "content_sha256 未冻结")
        if not self.theme:
            fail("THEME_MISSING", "theme 未指定")

        seen: set[str] = set()
        asset_refs: dict[str, list[str]] = {}
        prev_heading_level: int | None = None

        for block in self.blocks:
            bid = block.id
            if not bid:
                fail("BLOCK_ID_MISSING", "块缺少 id")
            elif bid in seen:
                fail("DUPLICATE_BLOCK_ID", f"重复块 ID: {bid}", bid)
            else:
                seen.add(bid)
            if block.kind not in KINDS:
                fail("UNKNOWN_KIND", f"未知块类型: {block.kind}", bid)
            if not block.source_ref:
                fail("SOURCE_REF_MISSING", "块缺少 source_ref", bid)

            if block.kind == "heading":
                lv = block.level
                if lv is None or not (HEADING_LEVEL_MIN <= lv <= HEADING_LEVEL_MAX):
                    fail("INVALID_HEADING_LEVEL", f"非法标题层级: {lv}", bid)
                elif prev_heading_level is not None and lv - prev_heading_level > 1:
                    fail("HEADING_LEVEL_SKIP",
                         f"标题层级从 {prev_heading_level} 跳到 {lv}", bid)
                else:
                    prev_heading_level = lv
                if not block.text:
                    fail("HEADING_TEXT_MISSING", "标题缺原文", bid)

            if block.kind == "figure":
                if not block.asset_id:
                    fail("FIGURE_ASSET_MISSING", "图块缺 asset_id", bid)
                else:
                    if block.asset_id not in self.assets:
                        fail("FIGURE_ASSET_UNKNOWN",
                             f"挂图引用不存在: {block.asset_id}", bid)
                    asset_refs.setdefault(block.asset_id, []).append(bid)
                if not block.source:
                    fail("FIGURE_SOURCE_MISSING", "图块缺来源", bid, WARNING)

            if block.kind == "table":
                if not block.headers:
                    fail("TABLE_HEADERS_MISSING", "表格缺表头", bid)
                if not block.rows:
                    fail("TABLE_ROWS_MISSING", "表格缺数据行", bid)
                if not block.source:
                    fail("TABLE_SOURCE_MISSING", "表格缺来源", bid, WARNING)

            if block.kind == "raw" and not block.raw_html:
                fail("RAW_CONTENT_MISSING", "保留原文块缺 raw_html", bid)

        for asset_id, refs in asset_refs.items():
            if len(refs) > 1:
                fail("DOUBLE_ATTACHMENT",
                     f"资产 {asset_id} 被重复挂接到 {refs}", refs[0])

        for asset_id, asset in self.assets.items():
            if asset.asset_id != asset_id:
                fail("ASSET_KEY_MISMATCH", f"assets 键与 asset_id 不一致: {asset_id}")
            if not asset.path:
                fail("ASSET_PATH_MISSING", f"资产 {asset_id} 缺路径")

        return issues

    def raise_if_invalid(self) -> "LayoutDocument":
        issues = self.validate()
        blockers = [x for x in issues if x["severity"] == BLOCKER]
        if blockers:
            raise LayoutValidationError(issues)
        return self

    @property
    def issues(self) -> list[dict[str, Any]]:
        return self.validate()

    @property
    def figures(self) -> list[Block]:
        return [b for b in self.blocks if b.kind == "figure"]

    @property
    def tables(self) -> list[Block]:
        return [b for b in self.blocks if b.kind == "table"]
