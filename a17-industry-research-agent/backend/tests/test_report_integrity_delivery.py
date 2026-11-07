"""Draft availability never changes formal eligibility or generation guards."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import backend.app.core.setup_env
from backend.app.api.routes import router
from backend.app.core.storage import storage
from backend.app.schemas.workflow import WorkflowState, StageResult, ArtifactRef
from report_fusion.render import _format_outlier_val


@pytest.fixture
def draft_client(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'base_dir',tmp_path)
    app=FastAPI();app.include_router(router)
    root=storage.get_run_dir('run-integrity');art=root/'artifacts';art.mkdir(parents=True,exist_ok=True)
    path=art/'report.pdf';path.write_bytes(b'%PDF-sanitized-draft')
    state=WorkflowState(project_id='p',run_id='run-integrity',status='waiting_review',current_stage='report_fusion',
        revision=2,created_at='2026-11-01',updated_at='2026-11-01',stage_results={
        'report_fusion':StageResult(stage='report_fusion',status='waiting_review',revision=2,
            data={'built_at_revision':2,'agent_status':'partial','hard_blocked':True,'draft_available':True,
                  'draft_sanitized':True,'quality':{'passed':False},'delivery_status':'ready_with_limits'},
            artifacts=[ArtifactRef(artifact_id='report_pdf',kind='report_pdf',uri=str(path),revision=2)])})
    storage.save_state(state)
    return TestClient(app)


def test_formal_blocked_and_explicit_sanitized_draft_available(draft_client):
    url='/api/v1/runs/run-integrity/artifacts/report_pdf'
    assert draft_client.get(url).status_code==409
    response=draft_client.get(url+'?mode=draft')
    assert response.status_code==200
    assert response.headers['x-report-mode']=='draft'
    assert response.content==b'%PDF-sanitized-draft'


def test_stale_draft_is_never_downloaded_as_current(draft_client):
    state=storage.load_state('run-integrity');state.revision=3;storage.save_state(state)
    assert draft_client.get('/api/v1/runs/run-integrity/artifacts/report_pdf?mode=draft').status_code==409


def test_pe_outlier_keeps_multiple_unit_at_any_magnitude():
    assert _format_outlier_val(55446.147051,'pe_ttm')=='55446.15倍'


def test_publish_manifest_resolves_after_temporary_directory_is_removed(tmp_path):
    import hashlib,json,shutil
    from backend.app.agents.adapters import _publish_fusion_artifacts
    source=tmp_path/'temporary';source.mkdir();destination=tmp_path/'published'
    content=b'final report';(source/'report.md').write_bytes(content)
    (source/'manifest.json').write_text(json.dumps({'artifacts':[{'kind':'markdown',
        'uri':str(source/'report.md'),'sha256':hashlib.sha256(content).hexdigest(),'size_bytes':12}]}))
    _publish_fusion_artifacts(source,destination)
    shutil.rmtree(source)
    manifest=json.loads((destination/'manifest.json').read_text())
    entry=manifest['artifacts'][0]
    assert entry['uri']==str(destination/'report.md')
    assert entry['sha256']==hashlib.sha256(content).hexdigest()
    assert entry['size_bytes']==12


def test_exported_markdown_uses_the_final_renumbered_svg(tmp_path):
    import asyncio,json
    from report_fusion.agent import ReportFusionAgent
    from report_fusion.config import Settings
    from report_fusion.models import ReportFusionRequest
    source=tmp_path/'input.svg';source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>图 9：原图</text></svg>')
    req=ReportFusionRequest.model_validate(dict(
        report=dict(report_id='r',subject='行业',as_of='2026-11-01',status='completed',evidence_index={
            'R1':dict(record_id='R1',domain='industry',entity='行业',metric='结构',value='上中下游')}),
        chapters=dict(run_id='c',subject='行业',as_of='2026-11-01',status='completed',chapters=[
            dict(chapter_id='CH-01',title='研究',summary='结构梳理',sections=[dict(section_id='S1',title='结构',
                paragraphs=[],chart_ids=['C1'])])]),
        charts=dict(charts=[dict(chart_id='C1',title='产业结构',chart_type='industry_chain',
            figure_number='图 9',svg_uri=str(source),evidence_ids=['R1'])]),
        options=dict(formats=['markdown','html'],enable_editorial_llm=False)))
    result=asyncio.run(ReportFusionAgent(settings=Settings(output_dir=tmp_path)).run(req))
    from pathlib import Path
    art=Path(result.artifact_dir)
    final_view=json.loads((art/'report_view.json').read_text())
    svg=(art/'charts'/'C1.svg').read_text()
    assert svg==final_view['charts'][0]['svg']
    assert '图 9' not in svg and '图 1' in svg


def test_limited_exports_show_warning_and_data_gaps_in_all_text_formats(tmp_path):
    from report_fusion.models import ReportViewModel
    from report_fusion.render import render_html,render_markdown
    view=ReportViewModel(report_id='r',title='行业报告',subject='行业',as_of='2026-11-01',tone='professional',
        report_depth='standard',visual_style='deep_research',delivery_status='ready_with_limits',chapters=[],
        executive_summary={'headline':'研究资料'},quality_issues=[{'code':'required_financial_cell','severity':'error',
            'location':'annual_x','claim':'2025年经营现金流缺失','suggestion':'补齐公开年报数据'}])
    for rendered in (render_html(view),render_markdown(view)):
        assert '受限草稿' in rendered
        assert '2025年经营现金流缺失' in rendered


@pytest.mark.parametrize('alias',['pdf','report.p','report.pdf','report_pdf'])
def test_resolved_report_alias_cannot_bypass_formal_gate(draft_client,alias):
    assert draft_client.get('/api/v1/runs/run-integrity/artifacts/'+alias).status_code in (404,409)


def test_all_formats_preserve_verified_structured_section_content():
    from report_fusion.models import ReportViewModel
    from report_fusion.render import render_html,render_markdown
    view=ReportViewModel(report_id='r',title='报告',subject='行业',as_of='2026-11-01',tone='professional',
        report_depth='standard',visual_style='deep_research',delivery_status='ready',
        executive_summary={'headline':'研究资料'},chapters=[{'chapter_id':'C','title':'章节','summary':'概述',
        'sections':[{'section_id':'S','title':'小节','metric_cards':[{'label':'已核验收入','value':'123.45','unit':'亿元'}],
            'callouts':[{'title':'关键解释','text':'保留定性边界说明'}],
            'comparison_table':{'title':'公司对比','columns':['企业','收入'],'rows':[['公司甲','123.45']]}}]}])
    for rendered in [render_markdown(view),render_html(view),render_html(view.model_copy(update={'chart_mode':'rich'}))]:
        for fragment in ['已核验收入','123.45','关键解释','保留定性边界说明','公司对比','公司甲']:
            assert fragment in rendered
        assert '全部通过' not in rendered and '<=1.5%' not in rendered


@pytest.mark.parametrize('alias',['report.pdf','pdf','report_pdf'])
def test_explicit_current_draft_aliases_share_revision_guard(draft_client,alias):
    assert draft_client.get('/api/v1/runs/run-integrity/artifacts/'+alias+'?mode=draft').status_code==200

def test_real_stage_commit_makes_current_sanitized_draft_downloadable(tmp_path,monkeypatch):
    import asyncio
    from backend.app.engine.state_machine import WorkflowEngine
    from backend.app.agents.adapters import FiveAgentsAdapter
    from backend.app.schemas.workflow import RunCreateRequest
    monkeypatch.setattr(storage,'base_dir',tmp_path)
    run='run-commit-draft';root=storage.get_run_dir(run)
    art=root/'artifacts';art.mkdir(parents=True,exist_ok=True)
    pdf=art/'report.pdf';pdf.write_bytes(b'%PDF-current-limited')
    state=WorkflowState(project_id='p',run_id=run,status='running',current_stage='report_fusion',revision=3,
        created_at='2026-11-02',updated_at='2026-11-02',stage_results={'report_fusion':StageResult(stage='report_fusion',status='running')})
    storage.save_state(state)
    (root/'input_data.json').write_text(RunCreateRequest(project_id='p',input_data={'industry_topic':'行业'}).model_dump_json())
    async def fusion(**kwargs):
        return StageResult(stage='report_fusion',revision=3,data={'agent_status':'partial','hard_blocked':True,
            'draft_available':True,'draft_sanitized':True,'quality':{'passed':False},'delivery_status':'ready_with_limits'},
            artifacts=[ArtifactRef(artifact_id='report_pdf',kind='report_pdf',uri=str(pdf),revision=3)])
    monkeypatch.setattr(FiveAgentsAdapter,'run_report_fusion',fusion)
    asyncio.run(WorkflowEngine()._execute_stage(run,'report_fusion',[]))
    app=FastAPI();app.include_router(router);client=TestClient(app)
    url=f'/api/v1/runs/{run}/artifacts/report_pdf'
    assert client.get(url).status_code==409
    assert client.get(url+'?mode=draft').status_code==200
    state=storage.load_state(run);state.revision=4;storage.save_state(state)
    assert client.get(url+'?mode=draft').status_code==409
