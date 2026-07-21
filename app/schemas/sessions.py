"""Request/response models for session endpoints."""

from pydantic import BaseModel, Field


class SessionCreateResponse(BaseModel):
    session_id: str = Field(description="UUID v4 identifying the conversation session.")
