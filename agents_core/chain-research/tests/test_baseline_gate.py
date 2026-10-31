import importlib.util
from pathlib import Path


def test_bad_or_unmeasured_structure_cannot_pass_release_gate():
    path = Path(__file__).resolve().parents[3]/'scripts'/'score_chain_baseline.py'
    spec = importlib.util.spec_from_file_location('chain_baseline_gate', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    good = dict(structure=1.0, coverage=1.0, scene_rate=1.0,
                violations=[], topic_leak=[], generic=[])
    assert not mod.baseline_failed([good])
    assert mod.baseline_failed([good, {**good, 'structure': 0.5}])
    assert mod.baseline_failed([{**good, 'structure': None}])
    assert mod.baseline_failed([{**good, 'scene_rate': 0.3}])
    assert mod.baseline_failed([])
