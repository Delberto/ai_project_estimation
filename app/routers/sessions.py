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
from app.schemas.sessions import SessionCreateResponse, SessionDetailResponse
from app.services.document_extractor import (
    DocumentExtractionError,
    UnsupportedDocumentError,
    prepare_attachments,
)
from app.services.llm_files import FileUploadError, delete_provider_file
from app.services.llm_wrapper import active_llm_provider, generate_estimation
from app.services.metadata_extractor import update_project_metadata
from app.config import settings
from app.services.sessions import ConversationHistory, session_store

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
    """Estima un proyecto dentro de una sesión existente.

    Contrato multipart
    ------------------
    - ``transcript`` (string, obligatorio): transcripción de la reunión o
      descripción libre del alcance.
    - ``attachments`` (lista de archivos, opcional): PDFs / Word.

    Pipeline
    --------
    1. Resolver la sesión (404 si el UUID no existe en el store en memoria).
    2. Procesar adjuntos:
       - DOCX → extracción local y concat a transcript
         (``--- attachment: nombre.docx ---``).
       - PDF  → upload a Files API del proveedor activo + ``file_id``
         en el mensaje multimodal al LLM.
    3. Moderación + anti prompt-injection sobre el texto combinado.
    4. Renderizar prompts Jinja (inyectando ``session.metadata`` en el
       system prompt) y llamar al LLM estructurado (Instructor).
    5. Actualizar historial + ``project_metadata`` con hechos del turno.
    6. Devolver ``EstimationResponse`` (mismo shape que ``POST /estimate``).
       Los PDFs remotos se borran al terminar la llamada LLM.
    """
    # --- 1. Sesión ---------------------------------------------------------
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail=f"Sesión no encontrada: {session_id}",
        )

    # --- 2. Lectura + preparación de adjuntos ------------------------------
    # El proveedor debe coincidir con el modelo primario (Files API ≠ cruzado).
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

    # --- 3. Request tipado para el motor de prompts ------------------------
    request = EstimationRequest(
        description=prepared.description,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )

    # --- 4. Moderación + LLM -----------------------------------------------
    # Si fallamos antes de generate_estimation, hay que borrar los PDFs
    # remotos a mano (generate_estimation ya limpia en su finally).
    pdfs_handed_to_llm = False
    try:
        validate_input(request.description)

        # Metadata vacío → bloque <project_metadata> vacío (primer turno).
        # El system se regenera otra vez en to_messages_list(); aquí solo
        # necesitamos el user_prompt del turno actual.
        system_prompt, user_prompt = render_estimation_prompt(
            request,
            version=PROMPT_VERSION,
            project_metadata=session.metadata,
        )

        if session.history is None:
            session.history = ConversationHistory(
                system_prompt=system_prompt,
                max_turns=settings.MAX_TURNS,
            )
        session.history.add_user(user_prompt)

        messages = session.history.to_messages_list(
            session.metadata,
            request=request,
            version=PROMPT_VERSION,
        )

        pdfs_handed_to_llm = True
        result = generate_estimation(
            messages=messages,
            pdf_uploads=prepared.pdf_uploads,
        )

        session.history.add_assistant(result.summary)
        session.metadata = update_project_metadata(
            session.metadata,
            user_text=prepared.description,
            result=result,
        )
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
        if not pdfs_handed_to_llm:
            for uploaded in prepared.pdf_uploads:
                delete_provider_file(uploaded)

    return EstimationResponse(
        result=result,
        prompt_version=PROMPT_VERSION,
        cached=False,
        project_metadata=session.metadata,
    )
