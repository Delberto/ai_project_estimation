"""Request/response models for session endpoints."""

from pydantic import BaseModel, Field

from app.services.sessions import ProjectMetadata


class SessionCreateResponse(BaseModel):
    session_id: str = Field(description="UUID v4 identifying the conversation session.")


class SessionDetailResponse(BaseModel):
    """Estado actual de una sesión (útil para debug / UI Streamlit)."""

    session_id: str = Field(description="UUID v4 identifying the conversation session.")
    project_metadata: ProjectMetadata = Field(
        description="Hechos estructurados acumulados (memoria, no historial).",
    )
