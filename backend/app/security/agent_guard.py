"""StageAgent decorator enforcing untrusted-input and output policies."""

from app.schemas.workflow import StageName, StageResult, StageStatus
from app.security.audit import SecurityEventType, security_audit_log
from app.security.policy import detect_prompt_injection, detect_sensitive_output
from app.workflow.stages import StageAgent, StageContext


class SecuredStageAgent:
    """Prevent suspicious Agent 2/4 output from reaching downstream stages."""

    def __init__(self, agent: StageAgent) -> None:
        if agent.stage not in {StageName.DATA_INTERPRET, StageName.CHAPTER_WRITE}:
            raise ValueError("SecuredStageAgent currently protects Agent 2 and Agent 4")
        self._agent = agent
        self.stage = agent.stage

    async def run(self, context: StageContext) -> StageResult:
        untrusted_input: dict[str, object] = {"review_feedback": context.review_feedback}
        if self.stage == StageName.DATA_INTERPRET:
            fetch_result = context.previous_results.get(StageName.DATA_FETCH)
            untrusted_input["input_data"] = context.input_data
            untrusted_input["data_fetch"] = fetch_result.data if fetch_result is not None else None
        input_findings = detect_prompt_injection(untrusted_input)
        if input_findings:
            event = security_audit_log.record(
                SecurityEventType.PROMPT_INJECTION_SUSPECTED,
                owner_id=context.owner_id,
                run_id=context.run_id,
                stage=self.stage.value,
                risk_level="high",
                reason_code=",".join(sorted({finding.rule_id for finding in input_findings})),
                outcome="agent_call_blocked",
                content=untrusted_input,
            )
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "security_alert": {
                        "code": "PROMPT_INJECTION_SUSPECTED",
                        "trace_id": event.trace_id,
                        "rules": sorted({finding.rule_id for finding in input_findings}),
                    }
                },
                error="prompt_injection_suspected",
            )
        result = await self._agent.run(context)
        serialized_result = result.model_dump(mode="json")
        findings = detect_sensitive_output(serialized_result)
        if not findings:
            return result
        event = security_audit_log.record(
            SecurityEventType.OUTPUT_POLICY_BLOCKED,
            owner_id=context.owner_id,
            run_id=context.run_id,
            stage=self.stage.value,
            risk_level="high",
            reason_code=",".join(sorted({finding.rule_id for finding in findings})),
            outcome="output_replaced",
            content=serialized_result,
        )
        return StageResult(
            stage=self.stage,
            status=StageStatus.WAITING_REVIEW,
            revision=context.revision,
            data={
                "security_alert": {
                    "code": "OUTPUT_POLICY_BLOCKED",
                    "trace_id": event.trace_id,
                    "rules": sorted({finding.rule_id for finding in findings}),
                }
            },
            error="output_policy_blocked",
        )
