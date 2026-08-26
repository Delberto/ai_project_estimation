"""Endpoints de sesión: creación y estimación con adjuntos.

Rutas (prefijo ``/api/v1`` montado en ``main.py``)
-------------------------------------------------
- ``POST /sessions``
      Crea una sesión nueva y devuelve ``{"session_id": "<uuid-v4>"}``.
      El cliente guarda ese id y lo reenvía en peticiones posteriores para
      reutilizar historial y metadatos entre páginas.

- ``POST /sessions/{session_id}/estimate``
      Acepta ``multipart/form-data`` con la transcripción y, opcionalmente,
      PDFs/DOCX.
      - DOCX → texto extraído **en local** (python-docx) y concatenado al
        transcript.
      - PDF  → subido a la **Files API** de OpenAI o Anthropic y referenciado
        por ``file_id`` en el mensaje al LLM.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.routers.estimations import (
    PROMPT_VERSION,
    InputModerationError,
)
from app.schemas.estimations import (
    DetailLevel,
    EstimationRequest,
    EstimationResponse,
    OutputFormat,
    ProjectType,
)
from app.schemas.sessions import SessionCreateResponse, SessionDetailResponse
from app.services.document_extractor import (
    DocumentExtractionError,
    UnsupportedDocumentError,
    prepare_attachments,
)
from app.services.estimation import estimation_service
from app.services.llm_files import FileUploadError, delete_provider_file
from app.services.llm_wrapper import active_llm_provider
from app.services.sessions import session_store

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session() -> SessionCreateResponse:
    """Crea una sesión de conversación identificada por UUID v4.

    El ``session_id`` debe viajar en cada petición posterior (path o body)
    si el cliente quiere reutilizar memoria entre páginas.
    """
    session = session_store.create()
    return SessionCreateResponse(session_id=session.session_id)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str) -> SessionDetailResponse:
    """Devuelve el ``project_metadata`` actual de la sesión (debug / UI)."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Sesión no encontrada: {session_id}",
        )
    return SessionDetailResponse(
        session_id=session.session_id,
        project_metadata=session.metadata,
    )


@router.post(
    "/sessions/{session_id}/estimate",
    response_model=EstimationResponse,
)
async def estimate_for_session(
    session_id: str,
    transcript: str = Form(
        ...,
        min_length=20,
        description="Texto de la transcripción o descripción del proyecto.",
    ),
    attachments: list[UploadFile] | None = File(
        default=None,
        description=(
            "Documentación complementaria opcional (PDF o DOCX). "
            "PDF se sube vía Files API al LLM; DOCX se extrae en local."
        ),
    ),
) -> EstimationResponse:
    """Estima un proyecto dentro de una sesión existente."""
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Sesión no encontrada: {session_id}",
        )

    provider = active_llm_provider()
    attachment_payload: list[tuple[str, bytes]] = []
    for upload in attachments or []:
        filename = upload.filename or "unnamed"
        data = await upload.read()
        attachment_payload.append((filename, data))

    try:
        prepared = prepare_attachments(
            transcript,
            attachment_payload,
            provider=provider,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileUploadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    request = EstimationRequest(
        description=prepared.description,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )

    estimation_started = False
    try:
        result, metadata, turn_observed = estimation_service.estimate_conversational(
            session_id=session_id,
            session=session,
            prepared=prepared,
            request=request,
            prompt_version=PROMPT_VERSION,
        )
        estimation_started = True
    except InputModerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Error al generar la estimación: {exc}",
        ) from exc
    finally:
        if not estimation_started:
            for uploaded in prepared.pdf_uploads:
                delete_provider_file(uploaded)

    return EstimationResponse(
        result=result,
        prompt_version=PROMPT_VERSION,
        cached=False,
        project_metadata=metadata,
        turn_observed=turn_observed,
    )
