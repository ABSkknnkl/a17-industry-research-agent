"""画像数据层契约测试（P0，2026-10-19）。

守四件事（对应实施方案 §五 P0 验收）：

1. ``chart_profiles/*.json`` 与 ``_BUILTIN_PROFILES`` **逐字段一致**——
   改一边忘另一边必须红，否则两套数据会静默漂移；
2. 加载顺序与内置表一致——``detect_profile`` 是"首个命中优先"，
   顺序变了画像归属就会漂移；
3. 坏数据被校验拦下、目录缺失能回退内置表（绝不因配置问题启动失败）；
4. ``cert_bodies`` 是「、」分隔的**字符串**而非数组——这是迁移时最容易踩的坑
   （``cert_bodies()`` 用 ``str(...).split`` 解析，list 会被 str() 成 "['a']" 再切碎）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chart_generator import chain_profile as cp
from chart_generator.chain_loader import (
    compare_with_builtin,
    load_all,
    profile_level,
    validate_profile,
)

ROOT = Path(__file__).resolve().parents[3]          # 仓库根
DATA_DIR = ROOT / "agents_core" / "chart-generator" / "chart_profiles"


@pytest.fixture(autouse=True)
def _restore_profiles():
    """每个用例结束后恢复默认数据源，避免污染其它测试。"""
    yield
    cp.reload_profiles(None)


# ── 1. 数据文件与内置表一致 ────────────────────────────────────────────────

def test_data_dir_exists():
    assert DATA_DIR.is_dir(), f"画像目录不存在：{DATA_DIR}"
    names = {p.name for p in DATA_DIR.iterdir() if p.is_file()}
    assert "_index.json" in names
    assert "_generic.json" in names


def test_builtin_matches_data_files():
    """A2 验收核心：外置 JSON 与内置兜底表逐字段相等。"""
    res = load_all(force_source="data")
    assert res.source == "data", res.warnings
    diffs = compare_with_builtin(res.profiles, cp._BUILTIN_PROFILES)
    assert not diffs, "外置画像与内置表不一致（改一边忘另一边）：\n" + "\n".join(diffs)


def test_generic_matches_builtin():
    res = load_all(force_source="data")
    assert res.generic == json.loads(
        json.dumps(cp._BUILTIN_GENERIC, ensure_ascii=False)
    ), "_generic.json 与 _BUILTIN_GENERIC 不一致"


def test_order_matches_builtin():
    """外置 order 必须**保持内置表的相对顺序**。

    新赛道画像允许插入中间（优先级需要，例如「高端数控机床」必须先于「机器人」命中，
    否则会被 robot 画像的「数控机床」关键词抢走），但**不能打乱已有画像的先后**——
    ``detect_profile`` 是"首个命中优先"，顺序变了画像归属就会漂移。
    """
    res = load_all(force_source="data")
    loaded = [p["key"] for p in res.profiles]
    builtin = [p["key"] for p in cp._BUILTIN_PROFILES]
    assert set(builtin) <= set(loaded), f"缺失内置画像：{sorted(set(builtin) - set(loaded))}"
    it = iter(loaded)
    missing = [k for k in builtin if k not in it]
    assert not missing, f"内置表顺序被打乱：{missing} 未按原相对顺序出现在 {loaded}"


def test_no_duplicate_keys():
    res = load_all(force_source="data")
    keys = [p["key"] for p in res.profiles]
    assert len(keys) == len(set(keys)), f"画像 key 重复：{keys}"


# ── 2. 字段级契约 ─────────────────────────────────────────────────────────

def test_every_profile_has_kw_and_mid_cards():
    res = load_all(force_source="data")
    for p in res.profiles:
        assert p.get("kw"), f"{p['key']} 缺少 kw"
        assert p.get("mid_cards"), f"{p['key']} 缺少 mid_cards"
        for card in p["mid_cards"]:
            assert isinstance(card, list) and len(card) == 2


def test_cert_bodies_is_string_not_list():
    """迁移坑守卫：cert_bodies 是「、」分隔的 string，不是 list。"""
    res = load_all(force_source="data")
    for p in res.profiles:
        val = p.get("cert_bodies")
        assert isinstance(val, str), (
            f"{p['key']}.cert_bodies 必须是字符串（实际 {type(val).__name__}）——"
            "cert_bodies() 用 str().split('、') 解析，list 会被切碎"
        )


def test_scopes_present_for_multi_segment_industries():
    """F13/F14 细分画像不能丢。"""
    res = load_all(force_source="data")
    by_key = {p["key"]: p for p in res.profiles}
    assert {s["key"] for s in by_key["aircraft"].get("scopes", [])} == {
        "drone_consumer", "evtol", "drone_industrial",
    }
    assert {s["key"] for s in by_key["semiconductor_equipment"].get("scopes", [])} == {
        "etch_deposit", "litho", "clean_cmp", "metrology",
    }


def test_no_brand_upstream_overlap_per_profile():
    """同一家公司不能既是整机龙头又是上游龙头（F8 的核心约束）。"""
    res = load_all(force_source="data")
    for p in res.profiles:
        overlap = set(p.get("leading_brand") or []) & set(p.get("leading_upstream") or [])
        assert not overlap, f"{p['key']} 品牌/上游名单重叠：{sorted(overlap)}"


# ── 3. 覆盖等级 ───────────────────────────────────────────────────────────

def test_profile_level_classification():
    assert profile_level({"leading_brand": ["A"], "wrong_fit": {"x": ["B"]}}) == "L2"
    assert profile_level({"leading_brand": ["A"]}) == "L1"
    assert profile_level({}) == "L0"
    assert profile_level({"leading_brand": [], "wrong_fit": {}}) == "L0"


def test_all_builtin_profiles_are_l1_or_l2():
    """现有 7 个画像都应至少是 L1（有龙头名单）。"""
    for p in cp._BUILTIN_PROFILES:
        assert profile_level(p) in ("L1", "L2"), f"{p['key']} 等级异常"


def test_generic_is_l0():
    assert profile_level(cp._BUILTIN_GENERIC) == "L0"


# ── 4. 校验与回退 ─────────────────────────────────────────────────────────

def test_validate_accepts_minimal_profile():
    """新行业最小画像（3 个字段）必须合法——这是"8 行加一个行业"的前提。"""
    assert validate_profile({
        "key": "pv", "kw": ["光伏"], "leading_brand": ["隆基绿能"],
    }) == []


def test_validate_rejects_bad_key():
    errs = validate_profile({"key": "光伏", "kw": ["x"]})
    assert any("key" in e for e in errs)


def test_validate_rejects_brand_upstream_overlap():
    errs = validate_profile({
        "key": "x", "kw": ["x"],
        "leading_brand": ["隆基绿能"], "leading_upstream": ["隆基绿能"],
    })
    assert any("重叠" in e for e in errs)


def test_validate_rejects_cert_bodies_list():
    errs = validate_profile({"key": "x", "kw": ["x"], "cert_bodies": ["A", "B"]})
    assert any("cert_bodies" in e for e in errs)


def test_validate_rejects_bad_mid_cards():
    errs = validate_profile({"key": "x", "kw": ["x"], "mid_cards": [["只有一项"]]})
    assert any("mid_cards" in e for e in errs)


def test_fallback_when_dir_missing(tmp_path, monkeypatch):
    """目录指到空路径 → 回退内置表，绝不能抛异常。"""
    monkeypatch.setenv("CHAIN_PROFILE_DIR", str(tmp_path / "nope"))
    res = load_all(builtin_profiles=cp._BUILTIN_PROFILES,
                   builtin_generic=cp._BUILTIN_GENERIC)
    assert res.source == "builtin"
    assert len(res.profiles) == len(cp._BUILTIN_PROFILES)
    assert any("目录不存在" in w for w in res.warnings)


def test_bad_file_is_skipped_not_fatal(tmp_path, monkeypatch):
    """单个坏文件只跳过自己，其它画像照常加载。"""
    good = {"key": "ok", "kw": ["测试"], "leading_brand": ["甲公司"]}
    (tmp_path / "ok.json").write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "bad.json").write_text("{ this is not json", encoding="utf-8")
    (tmp_path / "_index.json").write_text(json.dumps({"order": ["ok"]}), encoding="utf-8")
    (tmp_path / "_generic.json").write_text(
        json.dumps({"key": "generic"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("CHAIN_PROFILE_DIR", str(tmp_path))

    res = load_all()
    assert [p["key"] for p in res.profiles] == ["ok"]
    assert any("bad.json" in w for w in res.warnings)


def test_force_builtin_source():
    res = load_all(force_source="builtin",
                   builtin_profiles=cp._BUILTIN_PROFILES,
                   builtin_generic=cp._BUILTIN_GENERIC)
    assert res.source == "builtin"
    assert len(res.profiles) == len(cp._BUILTIN_PROFILES)


def test_reload_roundtrip():
    assert cp.reload_profiles("builtin") == "builtin"
    assert cp.profile_source() == "builtin"
    assert cp.reload_profiles(None) == "data"
    assert cp.profile_source() == "data"


def test_detect_profile_behaviour_unchanged():
    """端到端：改造后画像判定结果与改造前一致（抽 8 个主题）。"""
    cases = {
        "海上风电": ("power_equipment", ""),
        "工业机器人": ("robot", ""),
        "创新药": ("pharma", ""),
        "车载激光雷达": ("lidar", ""),
        "消费级无人机": ("aircraft", "drone_consumer"),
        "半导体设备（刻蚀/沉积）": ("semiconductor_equipment", "etch_deposit"),
        "新能源车": ("vehicle", ""),
        "人造草坪": ("generic", ""),
    }
    for subject, (key, scope) in cases.items():
        prof = cp.detect_profile(subject)
        assert prof["key"] == key, f"{subject} 画像漂移：{prof['key']} != {key}"
        assert (prof.get("scope_key") or "") == scope, (
            f"{subject} scope 漂移：{prof.get('scope_key')} != {scope}"
        )
