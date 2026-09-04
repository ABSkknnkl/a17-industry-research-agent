"""BUG-5 修复回归：checkpoint 白名单 serde + max_tokens 显式参数。

覆盖：
- JsonPlusSerializer 白名单下 StageName/StageStatus 的 dumps/loads_typed
  往返一致（旧快照兼容读 + 新快照写入）；
- 显式白名单不阻断 langgraph 内置 SAFE 类型（Command/Interrupt 等）；
- ChatOpenAI 构造不再触发 max_tokens 弃用 UserWarning（analysis+visuals）。
"""

import warnings
from enum import StrEnum

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.infrastructure.checkpoint.sqlite import _MSGPACK_ALLOWLIST


def _serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=[*_MSGPACK_ALLOWLIST])


def test_bug5_allowlist_covers_state_enums() -> None:
    """白名单恰好覆盖 state 通道的两个枚举类型 key。"""
    assert ("app.schemas.workflow", "StageName") in _MSGPACK_ALLOWLIST
    assert ("app.schemas.workflow", "StageStatus") in _MSGPACK_ALLOWLIST


@pytest.mark.parametrize(
    "value",
    [
        ("app.schemas.workflow", "StageName", "data_fetch"),
        ("app.schemas.workflow", "StageStatus", "waiting_review"),
    ],
)
def test_bug5_enum_roundtrip_via_msgpack(value: tuple[str, str, str]) -> None:
    """枚举经 msgpack typed 序列化/白名单反序列化往返，成员语义不变。"""
    module, qualname, member = value
    enum_cls = __import__(module, fromlist=[qualname]).__dict__[qualname]
    instance = getattr(enum_cls, member.upper())

    serde = _serde()
    type_str, blob = serde.dumps_typed(instance)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        restored = serde.loads_typed((type_str, blob))
        blocked = [
            str(w.message) for w in caught if "Blocked" in str(w.message) or "unregistered" in str(w.message)
        ]
    assert not blocked, f"白名单未生效: {blocked}"
    assert restored is instance or restored == instance
    assert type(restored) is enum_cls


def test_bug5_safe_types_not_blocked_by_allowlist() -> None:
    """显式白名单不能阻断内置 SAFE 类型（langgraph 消息/Command 等）。"""
    from langchain_core.messages import HumanMessage
    from langgraph.types import Command

    serde = _serde()
    for obj in (HumanMessage(content="hi"), Command(goto="next")):
        type_str, blob = serde.dumps_typed(obj)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            restored = serde.loads_typed((type_str, blob))
            blocked = [
                str(w.message)
                for w in caught
                if "Blocked" in str(w.message) or "unregistered" in str(w.message)
            ]
        assert not blocked
        assert isinstance(restored, type(obj))


def test_bug5_unknown_enum_outside_allowlist_is_blocked(caplog) -> None:
    """白名单外的自定义枚举被阻断并留下日志告警（严格语义，未来升级即当前行为）。"""

    class Outside(StrEnum):
        OTHER = "other"

    serde = _serde()
    type_str, blob = serde.dumps_typed(Outside.OTHER)
    with caplog.at_level("WARNING", logger="langgraph.checkpoint.serde.jsonplus"):
        restored = serde.loads_typed((type_str, blob))
    blocked_logs = [r.message for r in caplog.records if "Blocked" in r.message]
    assert blocked_logs, "白名单外类型必须被阻断并留下日志告警"
    assert "Outside" in blocked_logs[0]
    # 阻断语义：类型不恢复（StrEnum 降级为原始字符串 payload），
    # 不还原为枚举实例——下游 model_validate 不会误认为合法通道值。
    assert type(restored) is not Outside, "被阻断的类型不得还原为枚举实例"


def test_bug5_chatopenai_max_tokens_no_deprecation_warning() -> None:
    """max_tokens 走 ChatOpenAI 显式参数：构造期不再触发弃用 UserWarning。"""
    from langchain_openai import ChatOpenAI

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ChatOpenAI(
            model="deepseek-v4-flash",
            api_key="test-key",
            base_url="http://localhost:8000/v1",
            temperature=0.1,
            timeout=60,
            max_retries=2,
            max_tokens=8_192,
        )
    deprecated = [
        str(w.message)
        for w in caught
        if "max_tokens" in str(w.message) and issubclass(w.category, UserWarning)
    ]
    assert not deprecated, f"max_tokens 弃用告警仍存在: {deprecated}"
