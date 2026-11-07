import json
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _is_valid_golden_dir(dir_path: Path, req_files: list[str]) -> bool:
    if not dir_path.exists():
        return False
    if dir_path.name.startswith("test-") or dir_path.parent.name.startswith("test-"):
        return False
    if req_files and not all((dir_path / f).exists() for f in req_files):
        return False
    # 验证不是空运行或失败运行
    interp_file = dir_path / "interpretation_report.json"
    if interp_file.exists():
        try:
            doc = json.loads(interp_file.read_text(encoding="utf-8"))
            if doc.get("status") == "failed" or not doc.get("financial_ratios"):
                return False
        except Exception:
            return False
    return True


def resolve_golden_dir(golden_run_id: str = "run-20260926022235-107", required_files: list[str] | None = None) -> Path:
    """解析黄金样本产物目录。

    优先级：
    1. eval/fixtures/golden_run/artifacts (标准测试夹具)
    2. data/runs/<golden_run_id>/artifacts (本地指定快照)
    3. data/runs/* 任何已完成有效产物目录
    4. output/runs/* 任何已完成有效产物目录

    若未检索到可用快照，调用 pytest.skip 优雅跳过，提示环境数据依赖，杜绝 FileNotFoundError 阻断 CI。
    """
    candidates = [
        PROJECT_ROOT / "eval" / "fixtures" / "golden_run" / "artifacts",
        PROJECT_ROOT / "data" / "runs" / golden_run_id / "artifacts",
    ]

    req_files = required_files or []

    for c in candidates:
        if _is_valid_golden_dir(c, req_files):
            return c

    pytest.skip(
        f"本地未检索到基准黄金产物 ({golden_run_id})。本用例为特定历史黄金样本回归断言，"
        f"缺少指定产物时优雅跳过。"
    )
