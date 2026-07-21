from fastapi import APIRouter

Rutas (prefijo ``/api/v1`` montado en ``main.py``)
-------------------------------------------------
- ``POST /sessions``
      Crea una sesión nueva y devuelve ``{"session_id": "<uuid-v4>"}``.
      El cliente guarda ese id y lo reenvía en peticiones posteriores para
      reutilizar historial y metadatos entre páginas.

- ``POST /sessions/{session_id}/estimate``
      Acepta ``multipart/form-data`` con la transcripción y, opcionalmente,
      PDFs/DOCX. El servicio IA extrae el texto **en local**, lo concatena
      a la transcripción y lanza la estimación estructurada vía LLM.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.prompts.loader import render_estimation_prompt
from app.routers.estimations import (
    PROMPT_VERSION,
    InputModerationError,
    validate_input,
)
from app.schemas.estimations import (
    DetailLevel,
    EstimationRequest,
    EstimationResponse,
    OutputFormat,
    ProjectType,
)
from app.schemas.sessions import SessionCreateResponse
from app.services.document_extractor import (
    DocumentExtractionError,
    UnsupportedDocumentError,
    build_prompt_description,
)
from app.services.llm_wrapper import generate_estimation
from app.services.sessions import ConversationHistory, session_store

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session() -> SessionCreateResponse:
    """Create a new conversation session.

    Clients that want to reuse memory across pages should send the returned
    ``session_id`` on every subsequent request.
    """
    session = session_store.create()
    return SessionCreateResponse(session_id=session.session_id)
