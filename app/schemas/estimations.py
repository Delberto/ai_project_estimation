from datetime import datetime

from pydantic import BaseModel, Field


class EstimationRequest(BaseModel):
    transcription: str = Field(
        ...,
        min_length=1,
        description="Transcripción de la reunión con el cliente",
    )


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    generated_at: datetime
