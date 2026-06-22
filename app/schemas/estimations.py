from datetime import datetime

from pydantic import BaseModel

from app.schemas.schemas import EstimationRequest

__all__ = ["EstimationRequest", "EstimationResponse"]


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
