import pytest
from backend.app.agents.adapters import _extract_target_companies


def test_extract_target_companies():
    # Case 1: Chinese brackets with company list
    p1 = "核心上市公司（中兴通讯、铖昌科技、中国卫星、海格通信等）近三年营收增速与ROE对比"
    res1 = _extract_target_companies([p1])
    assert "中兴通讯" in res1
    assert "铖昌科技" in res1
    assert "中国卫星" in res1
    assert "海格通信" in res1

    # Case 2: Parentheses with '如'
    p2 = "A股核心标的（如绿的谐波、三花智控、鸣志电器、拓普集团）的财务表现"
    res2 = _extract_target_companies([p2])
    assert "绿的谐波" in res2
    assert "三花智控" in res2
    assert "鸣志电器" in res2
    assert "拓普集团" in res2

    # Case 3: Industry segments in brackets should be ignored
    p3 = "商业航天产业链各环节（上游核心元器件与特种材料、中游卫星总装与地面测控、下游卫星运营与终端应用）竞争格局"
    res3 = _extract_target_companies([p3])
    assert len(res3) == 0

    # Case 4: Explicit keyword mention
    p4 = "核心关注宁德时代、比亚迪、亿纬锂能的出海进展"
    res4 = _extract_target_companies([p4])
    assert "宁德时代" in res4
    assert "比亚迪" in res4
    assert "亿纬锂能" in res4
