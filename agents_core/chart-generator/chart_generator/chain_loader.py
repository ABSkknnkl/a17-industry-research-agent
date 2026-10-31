"""行业画像数据层：外置画像加载 + 轻量校验 + 内置表兜底（P0，2026-10-19）。

═════════════════════════════════════════════════════════════════════════════
设计约束（按实施方案 §3.1）
═════════════════════════════════════════════════════════════════════════════

1. **零新增依赖**：只用标准库 ``json``。YAML 仅在环境已装 PyYAML 时**可选**支持，
   不写进 requirements.txt（项目依赖保持极简，避免为读配置引入新依赖）。
2. **失败不阻断**：单个画像文件解析/校验失败 → 跳过该文件 + 记录告警；
   整个目录不可用或全部失败 → 调用方回退 ``_BUILTIN_PROFILES`` 内置表。
3. **顺序即优先级**：``_index.json`` 的 ``order`` 决定 ``detect_profile`` 首个命中
   顺序，必须与改造前 ``_PROFILES`` 列表顺序一致（否则画像归属会漂移）。
4. **可热重载**：``load_all(force_source=...)`` 供测试与开发临时切换数据源。
5. **不改语义**：加载结果与内置表**逐字段相等**（``compare_with_builtin`` 可验证）。

目录结构::

    chart-generator/
    ├── chart_generator/
    │   └── chain_loader.py      ← 本模块
    └── chart_profiles/
        ├── _index.json          加载顺序 + generic 指针
        ├── _generic.json        未命中任何画像时的兜底
        ├── aircraft.json
        └── ...
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_DIR = "CHAIN_PROFILE_DIR"
ENV_SOURCE = "CHAIN_PROFILE_SOURCE"          # auto(默认) | data | builtin

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "chart_profiles"
_INDEX_NAME = "_index.json"
_GENERIC_NAME = "_generic.json"

# 校验用：这些字段若存在必须是 list[str]（允许空）
_LIST_STR_FIELDS = (
    "kw", "leading_brand", "leading_upstream", "cap_pool", "forbid",
    "upstream", "ban_anywhere",
)
# 这些字段若存在必须是 str（注意 cert_bodies 是「、」分隔的**字符串**，不是 list）
_STR_FIELDS = ("name", "mid_column", "downstream", "support", "cert", "cert_bodies")


@dataclass
class LoadResult:
    """一次加载的完整结果。"""

    profiles: list[dict[str, Any]] = field(default_factory=list)
    generic: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source: str = "builtin"          # "data" | "builtin" | "dir-missing"
    dir_used: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.profiles)


# ── 路径与读取 ────────────────────────────────────────────────────────────

def data_dir() -> Path:
    """画像目录：环境变量优先，否则 ``chart-generator/chart_profiles``。"""
    raw = os.environ.get(ENV_DIR, "").strip()
    return Path(raw).expanduser().resolve() if raw else _DEFAULT_DIR


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_profile_file(path: Path) -> dict[str, Any]:
    """读单个画像文件。JSON 为唯一硬依赖；YAML 仅在装了 PyYAML 时可用。"""
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = _read_json(path)
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - 环境相关
            raise RuntimeError(
                f"{path.name}: 未安装 PyYAML，无法读取 YAML 画像；"
                "请改用 .json 或安装 pyyaml（非项目硬依赖）"
            ) from exc
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        raise RuntimeError(f"不支持的画像文件类型: {path.name}")
    if not isinstance(data, dict):
        raise RuntimeError(f"{path.name}: 顶层必须是对象，实际是 {type(data).__name__}")
    return data


# ── 校验 ──────────────────────────────────────────────────────────────────

def validate_profile(prof: dict[str, Any]) -> list[str]:
    """字段级校验。返回错误列表（空 = 通过）。

    刻意**宽松**：新行业只写 ``key`` + ``kw`` + ``leading_brand`` 即为合法 L1 画像，
    其余字段留空由 LLM 生成。只拦截会导致运行期崩溃或语义错乱的类型问题。
    """
    errs: list[str] = []
    key = prof.get("key")
    if not isinstance(key, str) or not key.strip():
        errs.append("key 缺失或非字符串")
    elif not all(c.islower() or c.isdigit() or c == "_" for c in key):
        errs.append(f"key「{key}」只能用小写字母/数字/下划线")

    for name in _LIST_STR_FIELDS:
        if name not in prof:
            continue
        val = prof[name]
        if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
            errs.append(f"{name} 必须是字符串数组")

    for name in _STR_FIELDS:
        if name not in prof:
            continue
        if not isinstance(prof[name], str):
            errs.append(f"{name} 必须是字符串（cert_bodies 用「、」分隔，不是数组）")

    mid_cards = prof.get("mid_cards")
    if mid_cards is not None:
        if not isinstance(mid_cards, list):
            errs.append("mid_cards 必须是数组")
        else:
            for i, card in enumerate(mid_cards):
                if not (isinstance(card, list) and len(card) == 2
                        and all(isinstance(x, str) for x in card)):
                    errs.append(f"mid_cards[{i}] 必须是 [卡名, 说明] 两个字符串")

    wrong_fit = prof.get("wrong_fit")
    if wrong_fit is not None:
        if not isinstance(wrong_fit, dict):
            errs.append("wrong_fit 必须是对象 {环节: [公司...]}")
        else:
            for k, v in wrong_fit.items():
                if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                    errs.append(f"wrong_fit[{k}] 必须是字符串数组")

    anchors = prof.get("upstream_anchor")
    if anchors is not None and not isinstance(anchors, dict):
        errs.append("upstream_anchor 必须是对象")

    scopes = prof.get("scopes")
    if scopes is not None:
        if not isinstance(scopes, list):
            errs.append("scopes 必须是数组")
        else:
            for i, sc in enumerate(scopes):
                if not isinstance(sc, dict):
                    errs.append(f"scopes[{i}] 必须是对象")
                elif not sc.get("key"):
                    errs.append(f"scopes[{i}] 缺少 key")

    brand = set(prof.get("leading_brand") or [])
    upstream = set(prof.get("leading_upstream") or [])
    overlap = sorted(brand & upstream)
    if overlap:
        errs.append(
            "leading_brand 与 leading_upstream 重叠（同一家公司不能既是整机又是上游）："
            + "、".join(overlap[:6])
        )
    return errs


def profile_level(prof: dict[str, Any]) -> str:
    """覆盖等级：L2 有龙头+禁配、L1 只有龙头、L0 无龙头（走通用降级）。"""
    has_brand = bool(prof.get("leading_brand"))
    has_guard = bool(prof.get("wrong_fit") or prof.get("ban_anywhere"))
    if has_brand and has_guard:
        return "L2"
    if has_brand:
        return "L1"
    return "L0"


# ── 加载 ──────────────────────────────────────────────────────────────────

def _ordered_keys(index: dict[str, Any], found: dict[str, Path]) -> list[str]:
    """按 _index.order 排序；未登记的画像追加到末尾（告警由调用方给）。"""
    order = [k for k in (index.get("order") or []) if isinstance(k, str)]
    known = [k for k in order if k in found]
    extra = sorted(k for k in found if k not in order)
    return known + extra


def load_all(
    *,
    force_source: str | None = None,
    builtin_profiles: list[dict[str, Any]] | None = None,
    builtin_generic: dict[str, Any] | None = None,
    strict: bool = False,
) -> LoadResult:
    """加载全部画像。

    Args:
        force_source: ``"data"`` 强制读目录（失败也返回空，用于验收）；
                      ``"builtin"`` 直接用内置表；``None`` 自动（默认）。
        builtin_profiles/builtin_generic: 内置兜底表（由 chain_profile 传入）。
        strict: True 时任何告警升级为异常（测试用）。
    """
    src = (force_source or os.environ.get(ENV_SOURCE, "auto")).strip().lower()
    if src == "builtin":
        return LoadResult(
            profiles=[dict(p) for p in (builtin_profiles or [])],
            generic=dict(builtin_generic or {}),
            warnings=["CHAIN_PROFILE_SOURCE=builtin，使用内置表"],
            source="builtin",
        )

    root = data_dir()
    res = LoadResult(dir_used=str(root))

    if not root.is_dir():
        res.warnings.append(f"画像目录不存在：{root}")
        res.source = "dir-missing"
        return _fallback(res, builtin_profiles, builtin_generic, strict)

    index_path = root / _INDEX_NAME
    index: dict[str, Any] = {}
    if index_path.exists():
        try:
            index = _read_json(index_path) or {}
        except Exception as exc:
            res.warnings.append(f"{_INDEX_NAME} 解析失败（按文件名排序兜底）：{exc}")
    else:
        res.warnings.append(f"{_INDEX_NAME} 不存在，按文件名排序加载")

    # 收集候选文件
    found: dict[str, Path] = {}
    for fp in sorted(root.iterdir()):
        if not fp.is_file() or fp.name.startswith("_"):
            continue
        if fp.suffix.lower() not in (".json", ".yaml", ".yml"):
            continue
        try:
            peek = _read_profile_file(fp)
        except Exception as exc:
            res.warnings.append(f"{fp.name} 解析失败，已跳过：{exc}")
            continue
        key = str(peek.get("key") or "").strip()
        if not key:
            res.warnings.append(f"{fp.name} 缺少 key，已跳过")
            continue
        if key in found:
            res.warnings.append(f"画像 key 重复「{key}」：{fp.name} 覆盖 {found[key].name}")
        found[key] = fp

    for key in _ordered_keys(index, found):
        fp = found[key]
        try:
            prof = _read_profile_file(fp)
        except Exception as exc:
            res.warnings.append(f"{fp.name} 读取失败，已跳过：{exc}")
            continue
        errs = validate_profile(prof)
        if errs:
            res.warnings.append(f"{fp.name} 校验失败，已跳过：" + "；".join(errs))
            continue
        res.profiles.append(prof)

    # generic
    generic_name = str(index.get("generic") or _GENERIC_NAME)
    gpath = root / generic_name
    if gpath.exists():
        try:
            g = _read_profile_file(gpath)
            if validate_profile(g):
                res.warnings.append(
                    f"{generic_name} 校验失败：" + "；".join(validate_profile(g))
                )
            else:
                res.generic = g
        except Exception as exc:
            res.warnings.append(f"{generic_name} 读取失败：{exc}")
    else:
        res.warnings.append(f"{generic_name} 不存在")

    if res.profiles:
        res.source = "data"
        return res
    return _fallback(res, builtin_profiles, builtin_generic, strict)


def _fallback(
    res: LoadResult,
    builtin_profiles: list[dict[str, Any]] | None,
    builtin_generic: dict[str, Any] | None,
    strict: bool,
) -> LoadResult:
    if strict and res.warnings:
        raise RuntimeError("画像加载失败：" + "；".join(res.warnings))
    if builtin_profiles:
        res.profiles = [dict(p) for p in builtin_profiles]
        res.generic = dict(builtin_generic or {})
        res.source = "builtin"
        res.warnings.append("已回退内置画像表（功能不受影响，但外置画像未生效）")
    return res


# ── 验收辅助 ──────────────────────────────────────────────────────────────

def _norm(value: Any) -> Any:
    """tuple→list、嵌套归一，便于与内置表逐字段比对。"""
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    return value


def compare_with_builtin(
    loaded: list[dict[str, Any]],
    builtin: list[dict[str, Any]],
    *,
    allow_extra: bool = True,
) -> list[str]:
    """逐字段比对（A2 验收）：返回差异清单，空 = 完全一致。

    Args:
        allow_extra: True（默认）时允许外置画像**多于**内置表——内置表只是
            "兜底最小集"，新赛道画像只写 JSON 即可，不必同步膨胀 Python 代码。
            但内置表里的每个 key **必须**在外置存在（否则删了画像会静默回退）。
    """
    diffs: list[str] = []
    bmap = {str(p.get("key")): _norm(p) for p in builtin}
    lmap = {str(p.get("key")): _norm(p) for p in loaded}

    for key in bmap.keys() - lmap.keys():
        diffs.append(f"缺失画像：{key}（内置表有、外置目录没有 → 会静默回退）")
    if not allow_extra:
        for key in lmap.keys() - bmap.keys():
            diffs.append(f"多余画像：{key}")

    for key in bmap.keys() & lmap.keys():
        b, l = bmap[key], lmap[key]
        for f in sorted(b.keys() | l.keys()):
            if b.get(f) != l.get(f):
                diffs.append(f"{key}.{f} 不一致")
    return diffs
