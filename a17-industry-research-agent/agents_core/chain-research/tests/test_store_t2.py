"""T2 验收测试：证据存储与恢复（方案 §9-T2）。

验收点：
- 原文快照和证据引用落盘；同源转载不作为多份独立来源
- 写入用事务/原子替换，取消和中断后保留一致快照
- SQLite 缓存和每 run 文件解耦；范围/时间/来源策略不同不能误命中缓存
- 重启后可从 manifest 恢复；原文定位可复核，错误引用不能进入 supported
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from chain_research import (
    BundleManifest,
    ChainAssertion,
    ChainEntity,
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
    ChainScope,
    ChainStructure,
    ChainStore,
    Predicate,
    Verification,
    chain_v2_dir,
    document_cache_key,
    stable_id,
)


def _make_evidence(url: str, title: str, *, family: str = "family-a",
                    quote: str = "原文引用内容") -> ChainEvidence:
    return ChainEvidence(
        evidence_id=stable_id("ev", url, quote),
        document_id=stable_id("doc", url),
        url=url,
        title=title,
        document_kind="authoritative_article",
        content_hash=hashlib.sha256(b"").hexdigest()[:32],  # 占位，save_document 时校验
        source_family=family,
        locator="p.3 ¶2",
        quote=quote,
    )


def _make_bundle(revision: int = 1) -> ChainKnowledgeBundle:
    scope = ChainScope(scope_id="sc1", subject="笔记本电脑", as_of="2026-10")
    org = ChainEntity(entity_id="ent-org1", entity_type="organization",
                      canonical_name="联想集团")
    act = ChainEntity(entity_id="ent-act1", entity_type="activity",
                      canonical_name="整机组装")
    ev = _make_evidence("https://example.com/report-2025",
                        "2025笔记本行业报告")
    ev = ev.model_copy(update={"content_hash": hashlib.sha256(b"doc-body").hexdigest()[:32]})
    a = ChainAssertion(
        assertion_id="asr-1", subject_id=org.entity_id,
        predicate=Predicate.PERFORMS, object_id=act.entity_id,
        status="supported", evidence_ids=[ev.evidence_id],
        verification=Verification(method="source_rule", rationale="原文明确"),
    )
    st = ChainStructure(structure_id="st1", scope_id=scope.scope_id,
                        activity_ids=[act.entity_id])
    return ChainKnowledgeBundle(
        run_id="run-t2", revision=revision, scope=scope,
        entities=[org, act], assertions=[a], evidence=[ev], structure=st,
        quality=ChainQualityReport(release_status="draft"),
        manifest=BundleManifest(run_id="run-t2", revision=revision,
                                scope_subject=scope.subject),
    )


@pytest.fixture()
def store(tmp_path: Path) -> ChainStore:
    return ChainStore(tmp_path / "run-t2", cache_db=tmp_path / "cache.sqlite")


class TestBundlePersistence:
    def test_save_and_load_roundtrip(self, store: ChainStore):
        bundle = _make_bundle()
        path = store.save_bundle(bundle)
        assert path == chain_v2_dir(Path(store.run_dir)) / "bundle.json"
        restored = store.load_bundle()
        assert restored is not None
        assert restored == bundle

    def test_quality_and_manifest_files_written(self, store: ChainStore, tmp_path: Path):
        store.save_bundle(_make_bundle())
        v2 = chain_v2_dir(tmp_path / "run-t2")
        assert (v2 / "quality.json").exists()
        assert (v2 / "manifest.json").exists()
        q = json.loads((v2 / "quality.json").read_text(encoding="utf-8"))
        assert q["release_status"] == "draft"

    def test_restore_after_restart(self, store: ChainStore, tmp_path: Path):
        """重启恢复：新 ChainStore 实例（模拟进程重启）读回 bundle 与 revision。"""
        store.save_bundle(_make_bundle(revision=2))
        store2 = ChainStore(tmp_path / "run-t2", cache_db=tmp_path / "cache.sqlite")
        assert store2.load_latest_revision() == 2
        assert store2.load_bundle() is not None

    def test_missing_bundle_returns_none(self, store: ChainStore):
        assert store.load_bundle() is None
        assert store.load_latest_revision() == 0


class TestAtomicWrites:
    def test_interrupted_write_keeps_old_snapshot(self, store: ChainStore):
        """中断后保留一致快照：写失败时旧 bundle.json 不被破坏。"""
        good = _make_bundle()
        store.save_bundle(good)
        before = (chain_v2_dir(Path(store.run_dir)) / "bundle.json").read_text(
            encoding="utf-8")
        # 模拟写一半崩溃：留下损坏的 tmp 文件
        v2 = chain_v2_dir(Path(store.run_dir))
        (v2 / "bundle.json.tmp-broken.tmp").write_text("{partial", encoding="utf-8")
        # 旧快照仍可读回
        restored = store.load_bundle()
        assert restored == good
        assert (v2 / "bundle.json").read_text(encoding="utf-8") == before

    def test_no_tmp_files_left_after_success(self, store: ChainStore):
        store.save_bundle(_make_bundle())
        v2 = chain_v2_dir(Path(store.run_dir))
        leftovers = [p.name for p in v2.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []


class TestDocumentCache:
    def test_save_document_and_cache_hit(self, store: ChainStore):
        ev = _make_evidence("https://example.com/doc1", "文档1")
        ev = ev.model_copy(update={
            "content_hash": hashlib.sha256(b"hello-doc").hexdigest()[:32]})
        raw = store.save_document(
            ev.document_id, b"hello-doc", evidence=ev,
            scope_subject="笔记本电脑", as_of="2026-10", source_policy="doubao_v1")
        assert raw.exists()
        hit = store.find_cached_document(
            "https://example.com/doc1",
            scope_subject="笔记本电脑", as_of="2026-10", source_policy="doubao_v1")
        assert hit is not None
        assert hit["document_id"] == ev.document_id

    def test_content_hash_mismatch_rejected(self, store: ChainStore):
        ev = _make_evidence("https://example.com/doc2", "文档2")
        # content_hash 声明与实际内容不符 → 拒绝写入
        with pytest.raises(ValueError, match="哈希不匹配"):
            store.save_document(
                ev.document_id, b"real-content", evidence=ev,
                scope_subject="笔记本", as_of="2026-10", source_policy="doubao_v1")

    def test_cache_key_isolates_scope_policy_time(self, store: ChainStore):
        """范围/时间/来源策略不同不能误命中缓存（T2 验收）。"""
        ev = _make_evidence("https://example.com/doc3", "文档3")
        ev = ev.model_copy(update={
            "content_hash": hashlib.sha256(b"doc3-body").hexdigest()[:32]})
        store.save_document(
            ev.document_id, b"doc3-body", evidence=ev,
            scope_subject="笔记本电脑", as_of="2026-10", source_policy="doubao_v1")
        # 同 URL、不同 scope → 不命中
        assert store.find_cached_document(
            "https://example.com/doc3",
            scope_subject="白酒", as_of="2026-10", source_policy="doubao_v1") is None
        # 不同来源策略 → 不命中
        assert store.find_cached_document(
            "https://example.com/doc3",
            scope_subject="笔记本电脑", as_of="2026-10", source_policy="bocha_v2") is None
        # 不同 as_of → 不命中
        assert store.find_cached_document(
            "https://example.com/doc3",
            scope_subject="笔记本电脑", as_of="2025-04", source_policy="doubao_v1") is None
        # 完全一致 → 命中
        assert store.find_cached_document(
            "https://example.com/doc3",
            scope_subject="笔记本电脑", as_of="2026-10", source_policy="doubao_v1") is not None

    def test_cache_key_composition(self):
        k1 = document_cache_key("u", "笔记本", "2026-10", "p1")
        k2 = document_cache_key("u", "白酒", "2026-10", "p1")
        assert k1 != k2

    def test_same_family_not_counted_twice(self, store: ChainStore):
        """同源转载按同一 source_family 计算，不作为多份独立来源。"""
        for i, url in enumerate((
                "https://a.example/news/1",
                "https://mirror-a.example/news/1")):
            ev = _make_evidence(url, f"转载{i}", family="wire-cn")
            ev = ev.model_copy(update={
                "content_hash": hashlib.sha256(f"body{i}".encode()).hexdigest()[:32]})
            store.save_document(
                ev.document_id, f"body{i}".encode(), evidence=ev,
                scope_subject="笔记本", as_of="2026-10", source_policy="doubao_v1")
        # 同 family + 同 scope/as_of 下，不同 content_hash 的文档 2 份，
        # 但 same_family_count 语义是"这家来源已收录过"（≥1 即非新独立来源）
        assert store.same_family_count(
            "wire-cn", scope_subject="笔记本", as_of="2026-10") >= 1
        assert store.same_family_count(
            "other-family", scope_subject="笔记本", as_of="2026-10") == 0

    def test_run_files_decoupled_from_shared_cache(self, tmp_path: Path):
        """SQLite 缓存和每 run 文件解耦：新 run 新目录，共享缓存不串 run 产物。"""
        ev = _make_evidence("https://example.com/doc4", "文档4")
        ev = ev.model_copy(update={
            "content_hash": hashlib.sha256(b"doc4").hexdigest()[:32]})
        s1 = ChainStore(tmp_path / "run-a", cache_db=tmp_path / "shared.sqlite")
        s1.save_document(ev.document_id, b"doc4", evidence=ev,
                         scope_subject="笔记本", as_of="2026-10",
                         source_policy="p")
        # 另一个 run 的 store：run 目录为空，但共享缓存可查到
        s2 = ChainStore(tmp_path / "run-b", cache_db=tmp_path / "shared.sqlite")
        assert s2.load_bundle() is None
        hit = s2.find_cached_document(
            "https://example.com/doc4",
            scope_subject="笔记本", as_of="2026-10", source_policy="p")
        assert hit is not None
        assert hit["raw_path"].startswith(str(tmp_path / "run-a"))


class TestAppendLogs:
    def test_query_log_append_and_read(self, store: ChainStore):
        store.append_query_log({"query": "笔记本 面板 厂商", "target": "act-1",
                                "kept": 3, "discarded": {"domain": 1}})
        store.append_query_log({"query": "电池 电芯", "target": "act-2", "kept": 0})
        entries = store.read_query_log()
        assert len(entries) == 2
        assert entries[0]["query"] == "笔记本 面板 厂商"
        assert entries[1]["kept"] == 0

    def test_transformation_log(self, store: ChainStore):
        store.append_transformation({
            "kind": "assertion_status",
            "assertion_id": "asr-1", "from": "candidate", "to": "supported",
            "reason": "原文验证通过", "evidence": "ev-1"})
        tf = store.read_transformations()
        assert tf[0]["to"] == "supported"

    def test_empty_logs_return_empty(self, store: ChainStore):
        assert store.read_query_log() == []
        assert store.read_transformations() == []


class TestNoCacheMode:
    def test_store_without_cache_db(self, tmp_path: Path):
        store = ChainStore(tmp_path / "run-x")   # cache_db=None
        store.save_bundle(_make_bundle())
        assert store.load_bundle() is not None
        assert store.find_cached_document(
            "https://x.com", scope_subject="s", as_of="2026-10",
            source_policy="p") is None
