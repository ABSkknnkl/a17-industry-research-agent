"""融合阶段导出透明度回归测试。

守护 `backend/app/agents/adapters.py::run_report_fusion` 的三处修复：

1. 格式导出播报必须以产物是否真实存在为准（此前为无条件宣告成功）
2. 智能体层返回的导出告警必须被读取并透传（此前 result.warnings 从未被读取）
3. 对外声明的交付格式必须等于实际产物（此前硬编码 markdown/html/pdf 三种）
"""
from __future__ import annotations

from pathlib import Path

ADAPTERS = Path("backend/app/agents/adapters.py")


def _source() -> str:
    assert ADAPTERS.exists(), "未找到适配层源码"
    return ADAPTERS.read_text(encoding="utf-8")


def test_export_broadcast_is_conditional_on_real_artifacts():
    """PDF/HTML 播报前必须判断文件存在且非空。"""
    src = _source()
    assert 'if pdf_file.exists() and pdf_file.stat().st_size > 0:' in src, \
        "PDF 成功播报必须以文件存在且非空为前提"
    assert 'if html_file.exists() and html_file.stat().st_size > 0:' in src, \
        "HTML 成功播报必须以文件存在且非空为前提"


def test_unconditional_success_broadcast_removed():
    """旧的「无条件宣告 PDF 已编译 / 三格式交付就绪」文案不得残留。"""
    src = _source()
    assert "已排版编译 A4 出版级高清矢量 PDF 研报 (report.pdf)\"" not in src, \
        "不得无条件宣告 PDF 编译成功（应带实际体积并做存在性判断）"
    assert "MD / HTML / PDF 多格式出版物全部交付就绪" not in src, \
        "不得无条件宣告三格式全部交付就绪"


def test_stage_completion_reports_actual_formats():
    """阶段完成事件必须播报实际交付格式。"""
    src = _source()
    assert "实际交付格式：" in src, "阶段完成播报必须说明实际交付格式"
    assert "delivered_formats" in src, "必须基于实际产物构建交付格式列表"


def test_agent_export_warnings_are_read_and_forwarded():
    """智能体返回的导出告警必须被读取。"""
    src = _source()
    assert 'getattr(result, "warnings", None)' in src, \
        "必须读取智能体返回的 warnings（此前从未读取，导致导出失败不可见）"
    assert "export_warnings: list[str]" in src, "必须建立导出告警收集容器"


def test_missing_or_empty_format_produces_warning():
    """缺失或空文件必须生成告警。"""
    src = _source()
    assert "格式导出缺失或为空文件" in src, "缺失/空文件必须产生显式告警"


def test_delivered_formats_not_hardcoded():
    """对外 formats 必须来自实际产物，不得硬编码三格式。"""
    src = _source()
    assert '"formats": delivered_formats' in src, "formats 必须取自实际交付产物"
    assert '"formats": ["markdown", "html", "pdf"]' not in src, \
        "formats 不得硬编码为三种（会出现声明有、实际没有的情况）"


def test_export_warnings_exposed_in_stage_data():
    """导出告警必须落到阶段 data，前端与评审核对可见。"""
    src = _source()
    assert '"warnings": export_warnings' in src, "导出告警必须写入阶段 data.warnings"
    assert "for w in export_warnings[:5]:" in src, \
        "导出告警必须并入质量问题清单（quality.issues），否则对评审不可见"