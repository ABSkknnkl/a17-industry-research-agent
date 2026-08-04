"""Small response contracts used by framework verification endpoints."""

from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ResponseModel):
    status: str
    service: str
    version: str


class PingResponse(ResponseModel):
    message: str
