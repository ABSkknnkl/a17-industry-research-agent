from importlib import import_module
from pathlib import Path


def test_bootstrap_loads_all_vendored_agent_packages() -> None:
    """Catch a missing package path or an accidental Desktop-path dependency."""

    from app.agents.real_core.bootstrap import ensure_real_agent_packages

    roots = ensure_real_agent_packages()

    assert len(roots) == 5
    assert all(root.is_dir() for root in roots)
    assert all("Desktop" not in str(root) for root in roots)
    assert all(Path(__file__).resolve().parents[4] in root.parents for root in roots)

    entrypoints = {
        "data_fetcher.agent": "DataFetcherAgent",
        "data_interpreter.agent": "DataInterpreterAgent",
        "chart_generator.agent": "ChartGeneratorAgent",
        "chapter_writer.agent": "ChapterWriterAgent",
        "report_fusion.agent": "ReportFusionAgent",
    }
    for module_name, class_name in entrypoints.items():
        module = import_module(module_name)
        assert getattr(module, class_name).__name__ == class_name
