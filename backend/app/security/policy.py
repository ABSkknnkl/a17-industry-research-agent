"""Lightweight prompt-injection and sensitive-output policies."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PolicyFinding:
    rule_id: str
    field_path: str


_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "IGNORE_RULES",
        re.compile(
            r"(?:忽略|忘掉|忘记|绕过|覆盖).{0,20}(?:规则|指令|提示词|限制)"
            r"|(?:ignore|forget|disregard).{0,20}(?:previous|prior|all)"
            r".{0,20}(?:instruction|rule|prompt)",
            re.IGNORECASE,
        ),
    ),
    (
        "ROLE_OVERRIDE",
        re.compile(
            r"(?:你现在是|改变角色|切换角色|无限制AI)"
            r"|(?:you are now|act as).{0,30}(?:unrestricted|administrator|developer)",
            re.IGNORECASE,
        ),
    ),
    (
        "PROMPT_DISCLOSURE",
        re.compile(
            r"(?:显示|输出|告诉我|复述).{0,20}(?:系统提示词|提示词全文|技能全文)"
            r"|(?:show|reveal|print|repeat).{0,30}(?:system prompt|hidden prompt|skill text)",
            re.IGNORECASE,
        ),
    ),
    (
        "SECRET_ACCESS",
        re.compile(
            r"(?:显示|读取|获取|输出).{0,24}(?:API[ _-]?Key|Token|密钥|环境变量)"
            r"|(?:show|read|reveal|print).{0,30}(?:api[ _-]?key|token|secret|environment variable)",
            re.IGNORECASE,
        ),
    ),
    (
        "UNAUTHORIZED_RESOURCE",
        re.compile(
            r"(?:访问|读取|执行).{0,24}(?:其他任务|数据库|文件系统|Shell|未授权工具)"
            r"|(?:access|read|execute).{0,30}"
            r"(?:other task|database|file system|shell|unauthorized tool)",
            re.IGNORECASE,
        ),
    ),
)

_SENSITIVE_OUTPUT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "SECRET_ASSIGNMENT",
        re.compile(
            r"(?:LLM_API_KEY|SKILLHUB_API_KEY|API[ _-]?KEY|TOKEN|SECRET|PASSWORD)"
            r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}",
            re.IGNORECASE,
        ),
    ),
    (
        "BEARER_TOKEN",
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    ),
    (
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "PROMPT_REFLECTION",
        re.compile(
            r"(?:系统提示词|隐藏提示词|技能全文)\s*(?:如下|[:：])"
            r"|(?:system prompt|hidden prompt|skill text)\s*(?:is|follows|[:])",
            re.IGNORECASE,
        ),
    ),
)


def _text_values(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _text_values(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _text_values(item, f"{path}[{index}]")


def detect_prompt_injection(value: Any) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []
    for path, text in _text_values(value):
        for rule_id, pattern in _INJECTION_RULES:
            if pattern.search(text):
                findings.append(PolicyFinding(rule_id=rule_id, field_path=path))
    return findings


def detect_sensitive_output(value: Any) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []
    for path, text in _text_values(value):
        for rule_id, pattern in _SENSITIVE_OUTPUT_RULES:
            if pattern.search(text):
                findings.append(PolicyFinding(rule_id=rule_id, field_path=path))
    return findings
