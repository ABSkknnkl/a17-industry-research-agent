import asyncio
import json

import pytest

from report_fusion.agent import ReportFusionAgent, _check_final_view
from report_fusion.config import Settings
from report_fusion.models import ReportFusionRequest


def appendix_request(appendix):
    return ReportFusionRequest.model_validate({
        'report': {'report_id': 'r', 'subject': '电池', 'as_of': '2026-11-01',
            'status': 'completed', 'data_quality_appendix': appendix,
            'evidence_index': {'R1': {'record_id': 'R1', 'entity': '亿纬锂能',
                'domain': 'financials', 'metric': 'gross_margin', 'value': 18.5,
                'unit': '%', 'period': '2025-12-31'}},
            'comps_matrix': {'entries': [{'company_name': '亿纬锂能', 'pe_ttm': 25,
                'pb': 2.5, 'valuation_tier': 'profitable'}]}},
        'chapters': {'run_id': 'c', 'subject': '电池', 'as_of': '2026-11-01',
            'status': 'completed', 'chapters': []},
        'options': {'formats': ['markdown', 'html'], 'enable_editorial_llm': False}})


@pytest.mark.parametrize('appendix', [
    {'sample_info': {'pe_available_count': 0}},
    {'outlier_items': [{'entity': '亿纬锂能', 'metric': 'gross_margin',
        'observed_value': '99999', 'period': '2025-12-31', 'evidence_ids': ['R1']}]},
    {'outlier_items': [{'entity': '亿纬锂能', 'metric': 'gross_margin',
        'observed_value': '18.5', 'period': '2026-12-31', 'evidence_ids': ['R1']}]},
    {'non_extrapolation_disclaimers': ['亿纬锂能2025年毛利率99999%。']},
    {'non_extrapolation_disclaimers': ['集团毛利率表明电池业务议价权提升。']},
    {'conflict_items': [{'entity': '亿纬锂能', 'metric': 'gross_margin',
        'period': '2025-12-31', 'observed_values': ['18.5', '999'], 'evidence_ids': ['R1']}]},
    {'outlier_items': [{'entity': '亿纬锂能', 'metric': 'gross_margin',
        'observed_value': '18.5', 'period': '2025-12-31', 'evidence_ids': ['R1'],
        'expected_range': '横截面中位数99999、MAD1'}]},
])
def test_appendix_mutations_block_formal(appendix):
    req = appendix_request(appendix)
    assert _check_final_view([], [], req)[0]


def test_draft_removes_bad_appendix_and_preserves_resolvable_evidence(tmp_path):
    req = appendix_request({'sample_info': {'pe_available_count': 0},
        'outlier_items': [{'entity': '亿纬锂能', 'metric': 'gross_margin',
            'observed_value': '18.5', 'period': '2025-12-31', 'evidence_ids': ['R1'],
            'reason': '统计离群观察，需复核。'}],
        'non_extrapolation_disclaimers': ['集团毛利率表明电池业务议价权提升。']})
    result = asyncio.run(ReportFusionAgent(settings=Settings(output_dir=tmp_path)).run(req))
    from pathlib import Path
    root = Path(result.artifact_dir)
    view = json.loads((root / 'report_view.json').read_text())
    assert view['data_quality_appendix']['sample_info']['pe_available_count'] == 1
    assert view['data_quality_appendix']['non_extrapolation_disclaimers'] == []
    assert view['data_quality_appendix']['outlier_items'][0]['evidence_ids'] == ['R1']
    assert [s['record_id'] for s in view['evidence_catalog']] == ['R1']
    assert view['delivery_status'] == 'ready_with_limits'
    for filename in ['report.md', 'report.html']:
        exported = (root / filename).read_text()
        assert '集团毛利率表明电池业务议价权提升' not in exported
        assert '2025-12-31' in exported


def test_valid_appendix_observation_does_not_get_deleted(tmp_path):
    from report_fusion.appendix import audit_appendix
    req = appendix_request({'outlier_items': [{'entity': '亿纬锂能',
        'metric': 'gross_margin', 'observed_value': '18.5', 'period': '2025-12-31',
        'evidence_ids': ['R1'], 'reason': '记录供复核，不作业务因果推断。'}]})
    clean, issues = audit_appendix(req.report)
    assert not issues
    assert clean['outlier_items'][0]['period'] == '2025-12-31'


@pytest.mark.parametrize("separator", ["。", "；", "\n"])
def test_local_sanitizing_keeps_supported_sentences(tmp_path, separator):
    req = appendix_request({})
    from report_fusion.models import ChapterDraft
    req.chapters.chapters = [ChapterDraft.model_validate({'chapter_id':'C', 'title':'财务', 'summary':'核验资料',
        'sections':[{'section_id':'S', 'title':'观察', 'paragraphs':[
            {'paragraph_id':'P', 'text':f'亿纬锂能2025年毛利率18.5%{separator}亿纬锂能2025年毛利率99999%。仍需核对分部经营情况。',
             'evidence_ids':['R1']}]}]})]
    result = asyncio.run(ReportFusionAgent(settings=Settings(output_dir=tmp_path)).run(req))
    from pathlib import Path
    view = json.loads((Path(result.artifact_dir) / 'report_view.json').read_text())
    paragraph = view['chapters'][0]['sections'][0]['paragraphs'][0]['text']
    assert '18.5%' in paragraph and '仍需核对分部经营情况' in paragraph
    assert '99999' not in paragraph


def test_different_scopes_cannot_be_described_as_source_conflict():
    req = appendix_request({'conflict_items': [{'entity':'亿纬锂能', 'metric':'gross_margin',
        'period':'2025-12-31', 'observed_values':['18.5', '30'], 'evidence_ids':['R1','R2']}]})
    req.report.evidence_index['R2'] = req.report.evidence_index['R1'].model_copy(
        update={'record_id':'R2','value':30,'scope':'battery_segment'})
    assert _check_final_view([], [], req)[0]


def test_invalid_period_is_never_a_shared_range_bucket():
    from report_fusion.appendix import audit_appendix
    req = appendix_request({'outlier_items':[{'entity':'亿纬锂能','metric':'gross_margin',
        'observed_value':'18.5','period':'2025-12-31','evidence_ids':['R1']}]})
    req.report.evidence_index['R1'].issues=['period_conflict']
    req.report.evidence_index['R2']=req.report.evidence_index['R1'].model_copy(
        update={'record_id':'R2','value':999})
    clean, issues=audit_appendix(req.report)
    assert issues and clean['outlier_items']==[]


def test_unsupported_forecast_without_a_number_is_isolated():
    from report_fusion.agent import _audit_numeric_components
    from report_fusion.models import ChapterDraft, ParagraphDraft, SectionDraft

    req = appendix_request({})
    chapter = ChapterDraft(chapter_id="C", title="财务", summary="核验资料", sections=[
        SectionDraft(section_id="S", title="观察", paragraphs=[
            ParagraphDraft(paragraph_id="P", text="行业未来将持续增长。")
        ])
    ])
    issues = _audit_numeric_components([chapter], None, req, sanitize=True)

    assert [issue["code"] for issue in issues] == ["unsupported_direction_claim"]
    assert not chapter.sections[0].paragraphs
    assert chapter.content_audit[0]["original"] == "行业未来将持续增长。"


@pytest.mark.parametrize("mode", ["auto", "rich"])
def test_restricted_reading_view_formats_financial_terms_without_mutating_values(tmp_path, mode):
    from pathlib import Path
    from report_fusion.models import ChapterDraft

    req = appendix_request({})
    req.options.chart_mode = mode
    req.report.evidence_index["R1"].value = 8.1987
    req.chapters.chapters = [ChapterDraft.model_validate({
        "chapter_id": "C", "title": "财务", "summary": "数据复核",
        "sections": [{"section_id": "S", "title": "观察", "paragraphs": [{
            "paragraph_id": "P", "text": "亿纬锂能2025年（annual，consolidated）gross_margin为8.1987%。",
            "evidence_ids": ["R1"],
        }]}],
    })]
    result = asyncio.run(ReportFusionAgent(settings=Settings(output_dir=tmp_path)).run(req))
    root = Path(result.artifact_dir)
    for name in ("report.html", "report.md"):
        content = (root / name).read_text()
        assert "受限草稿" in content and "核验与交付限制" in content
        assert "8.20%" in content
        assert "draft-watermark" not in content and "52pt" not in content
        assert "（annual，consolidated）" not in content
    view = json.loads((root / "report_view.json").read_text())
    assert view["evidence_catalog"][0]["value"] == 8.1987


def test_audited_paragraph_can_be_restored_with_local_evidence():
    from report_fusion.models import ChapterDraft, SectionDraft

    req = appendix_request({})
    chapter = ChapterDraft(chapter_id="C", title="财务", summary="财务观察",
        sections=[SectionDraft(section_id="S", title="观察")],
        content_audit=[{"code": "chapter_claim_repair", "location": "P", "section_id": "S",
                        "disposition": "isolated", "original": "亿纬锂能2025年毛利率99999%。"}])
    raw = {"headline": "财务观察", "paragraph_edits": {
        "P": {"text": "亿纬锂能2025年毛利率18.5%。", "evidence_ids": ["R1"]},
    }}
    _, chapters, _, accepted, rejected, _ = ReportFusionAgent()._apply_editorial(raw, req, [chapter])
    assert accepted == 1 and rejected == 0
    assert chapters[0].sections[0].paragraphs[0].evidence_ids == ["R1"]
    assert chapters[0].content_audit[0]["disposition"] == "repaired"


def test_isolating_last_answer_preserves_hard_requirement_gap(tmp_path):
    from report_fusion.models import ChapterDraft

    req = appendix_request({"requirement_evidence_matrix": [{
        "requirement": {"requirement_id": "margin", "label": "年度毛利率", "hard": True},
        "coverage": {"passed": True, "evidence_record_ids": ["R1"]},
    }]})
    req.chapters.chapters = [ChapterDraft.model_validate({
        "chapter_id": "C", "title": "财务", "summary": "数据复核",
        "sections": [{"section_id": "S", "title": "观察", "paragraphs": [{
            "paragraph_id": "P", "text": "亿纬锂能2025年毛利率99999%。", "evidence_ids": ["R1"],
        }]}],
    })]
    result = asyncio.run(ReportFusionAgent(settings=Settings(output_dir=tmp_path)).run(req))
    assert any("必答内容尚未通过核验" in issue for issue in result.consistency.issues)


@pytest.mark.parametrize("claim", ["行业持续增长。", "该公司行业领先。"])
def test_unqualified_direction_or_rank_needs_evidence(claim):
    from agents_core.financial_semantics import quantity_issues

    assert [item["code"] for item in quantity_issues(claim, [])] == ["unsupported_direction_claim"]


def test_two_comparable_observations_support_direction_but_not_the_opposite():
    from agents_core.financial_semantics import quantity_issues

    refs = [
        {"record_id": str(year), "entity": "甲公司", "metric": "gross_margin",
         "value": value, "unit": "%", "period": f"{year}-12-31", "period_type": "annual"}
        for year, value in [(2024, 30), (2025, 28)]
    ]
    assert not quantity_issues("甲公司2024年至2025年毛利率下降。", refs)
    assert quantity_issues("甲公司2024年至2025年毛利率上升。", refs)
    assert quantity_issues("甲公司2024年至2025年毛利率持续下降。", refs)


def test_source_opinion_cannot_be_republished_as_causal_fact():
    from agents_core.financial_semantics import quantity_issues

    refs = [{"record_id": "OPINION", "domain": "news", "value": "机构认为成本下降导致利润改善。"}]
    assert any(item["code"] == "unsupported_causal_claim"
               for item in quantity_issues("成本下降导致利润改善。", refs))
    assert not quantity_issues("机构认为成本下降导致利润改善。", refs)


def test_fully_recovered_chapter_claim_does_not_leave_a_stale_quality_block(tmp_path):
    from report_fusion.models import ChapterDraft, SectionDraft, ParagraphDraft

    req = appendix_request({})
    req.options.enable_editorial_llm = True
    req.chapters.chapters = [ChapterDraft(
        chapter_id=f"CH-{i:02d}", title=f"主题{i}", summary="材料范围",
        sections=[SectionDraft(section_id=f"S-{i}-{j}", title=f"观察{j}", paragraphs=[
            ParagraphDraft(paragraph_id=f"P-{i}-{j}", text="汇总披露材料。")
        ]) for j in range(3)],
    ) for i in range(1, 8)]
    chapter = req.chapters.chapters[0]
    chapter.sections[0].paragraphs = []
    chapter.content_audit = [{"code": "chapter_claim_repair", "location": "P-1-0",
        "section_id": "S-1-0", "disposition": "isolated", "original": "未核验断言"}]
    req.chapters.quality = {"passed": False, "issues": ["段落资料缺口：CH-01 P-1-0 数值待核"]}

    class Editorial:
        is_available = True

        async def generate_json(self, system, prompt):
            return {"headline": "财务观察", "paragraph_edits": {
                "P-1-0": {"text": "亿纬锂能2025年毛利率18.5%。", "evidence_ids": ["R1"]},
            }}

    result = asyncio.run(ReportFusionAgent(llm=Editorial(), settings=Settings(output_dir=tmp_path)).run(req))
    assert result.status == "completed", result.consistency.issues
    audit = json.loads((tmp_path / "runs" / result.run_id / "fact_audit.json").read_text())
    assert audit["content_audit"][0]["disposition"] == "repaired"
