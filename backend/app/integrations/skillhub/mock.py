"""Deterministic SkillHub fake used only by tests and no-key development."""

import hashlib
import json

from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import SkillName, SkillPayload


class MockSkillHubClient:
    provider_mode = "mock"

    def __init__(self) -> None:
        self.calls: list[tuple[SkillName, SkillQueryArgs]] = []

    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        self.calls.append((skill_name, args))
        rows = _mock_rows(skill_name)
        raw = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        suffix = f"{len(self.calls):064x}"[-64:]
        return SkillPayload(
            skill_name=skill_name,
            query=args.query,
            rows=rows,
            total_count=len(rows),
            page=args.page,
            trace_id=suffix,
            raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            source_name=f"本地测试桩 {skill_name.value}",
            source_locator=f"mock://{skill_name.value}/{len(self.calls)}",
        )


def _mock_rows(skill_name: SkillName) -> list[dict[str, object]]:
    common = {"数据日期": "2026-06-30", "来源": "本地测试桩"}
    rows: dict[SkillName, list[dict[str, object]]] = {
        SkillName.INDUSTRY: [
            {**common, "行业名称": "测试行业", "行业规模(亿元)": 1200.0, "同比增速(%)": 18.2}
        ],
        SkillName.FINANCE: [
            {**common, "股票简称": "测试公司A", "营业收入(亿元)": 320.0, "ROE(%)": 14.5},
            {**common, "股票简称": "测试公司B", "营业收入(亿元)": 260.0, "ROE(%)": 12.0},
        ],
        SkillName.MACRO: [{**common, "指标名称": "制造业PMI", "指标值": 50.8, "单位": "%"}],
        SkillName.INDUSTRY_CHAIN: [{**common, "上游": "原材料", "中游": "制造", "下游": "应用"}],
        SkillName.REPORT: [{**common, "标题": "测试行业深度研究", "发布日期": "2026-06-20"}],
        SkillName.NEWS: [{**common, "标题": "测试行业政策动态", "发布日期": "2026-06-25"}],
        SkillName.ANNOUNCEMENT: [{**common, "公告标题": "测试公司年度报告"}],
        SkillName.EVENT: [{**common, "事件类型": "机构调研", "事件数量": 8}],
        SkillName.BUSINESS: [{**common, "股票简称": "测试公司A", "主营业务占比(%)": 75.0}],
        SkillName.SECTOR: [{**common, "板块名称": "测试行业", "板块涨跌幅(%)": 2.1}],
        SkillName.INSTITUTIONAL_RESEARCH: [{**common, "股票简称": "测试公司A", "机构覆盖数": 12}],
    }
    return rows[skill_name]
