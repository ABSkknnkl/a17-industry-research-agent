"""Small response contracts used by framework verification endpoints."""

from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ResponseModel):
    status: str
    service: str
    version: str


class ReadinessResponse(ResponseModel):
    ready: bool
    environment: str
    llm_provider: str
    llm_model: str
    skillhub_provider: str
    mock_components: list[str]
    database: str
    artifact_storage: str
    pdf_renderer: str
    issues: list[str]


class PingResponse(ResponseModel):
    message: str
