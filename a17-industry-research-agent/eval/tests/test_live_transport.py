from __future__ import annotations

import json

from eval.transport import canonical_query, classify_provider_stop, compute_live_match_key


def test_skillhub_key_deduplicates_canonical_query_but_not_page() -> None:
    first = compute_live_match_key(
        provider="skillhub",
        skill="hithink_finance_query",
        endpoint="POST /v1/query2data",
        request_body={"query": " 宁德时代   营业收入 ", "page": "1"},
    )
    same = compute_live_match_key(
        provider="skillhub",
        skill="hithink_finance_query",
        endpoint="POST /v1/query2data",
        request_body={"query": "宁德时代 营业收入", "page": 1},
    )
    next_page = compute_live_match_key(
        provider="skillhub",
        skill="hithink_finance_query",
        endpoint="POST /v1/query2data",
        request_body={"query": "宁德时代 营业收入", "page": 2},
    )
    assert canonical_query(" 宁德时代\u3000营业收入 ") == "宁德时代 营业收入"
    assert first == same
    assert first != next_page
    assert len(first) == 64


def test_provider_limit_signals_stop_without_guessing_response() -> None:
    assert classify_provider_stop(provider="skillhub", status_code=429, content="")
    assert classify_provider_stop(provider="llm", status_code=400, content="insufficient_quota")
    assert classify_provider_stop(provider="skillhub", status_code=200, content="正常数据") is None


def test_data_payload_with_financial_keywords_does_not_stop() -> None:
    # Regression: announcement text legitimately contains 额度/余额/计费; a 200
    # response carrying data rows must never be classified as quota exhaustion.
    payload = json.dumps({"datas": [{"标题": "关于授信额度及账户余额的公告", "计费方式": "按次"}]})
    assert classify_provider_stop(provider="skillhub", status_code=200, content=payload) is None
    nested = json.dumps({"result": {"list": [{"内容": "额度调整"}]}})
    assert classify_provider_stop(provider="skillhub", status_code=200, content=nested) is None
    llm_ok = json.dumps({"choices": [{"message": {"content": "分析涉及权限与额度"}}]})
    assert classify_provider_stop(provider="llm", status_code=200, content=llm_ok) is None
    # A genuine error envelope without data rows still stops.
    assert classify_provider_stop(provider="skillhub", status_code=200, content='{"error":"次数已达上限"}')
