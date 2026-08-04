import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "langchain",
        "langgraph",
        "langchain_openai",
        "pywencai",
        "pyecharts",
        "playwright",
    ],
)
def test_runtime_dependency_can_be_imported(module_name: str) -> None:
    importlib.import_module(module_name)
