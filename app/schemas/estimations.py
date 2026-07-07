from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.schemas import EstimationRequest

__all__ = [
    "EstimationRequest",
    "EstimationResponse",
    "EstimationResult",
    "Phase",
]


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None
    cost_mxn: float | None = None
    generated_at: datetime


class Phase(BaseModel):
    name: str
    duration_weeks: int = Field(ge=0)
    cost_eur: int = Field(ge=0)


class EstimationResult(BaseModel):
    summary: str
    total_duration_weeks: int = Field(ge=0)
    total_cost_eur: int = Field(ge=0)
    confidence_pct: int = Field(ge=0, le=100)
    phases: list[Phase]

    @model_validator(mode="after")
    def low_confidence_must_be_explicit(self):
        if self.confidence_pct < 30 and not self.summary.startswith("Out of scope:"):
            raise ValueError(
                "Confidence below 30% requires an explicit out-of-scope summary"
            )
        return self
