"""Cliente Streamlit: estimación multi-turno con sesión y project_metadata."""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

from app.schemas.estimations import EstimationResponse
from app.services.sessions import ProjectMetadata

st.set_page_config(page_title="Estimador CAG", layout="wide")

API_BASE_URL = st.sidebar.text_input(
    "URL de la API",
    value=os.getenv("API_BASE_URL", "http://localhost:8000"),
).rstrip("/")

EMPTY_METADATA: dict[str, Any] = ProjectMetadata().model_dump()


def _api_ok() -> bool:
    try:
        health = requests.get(f"{API_BASE_URL}/health", timeout=3)
        return health.ok
    except requests.RequestException:
        return False


def create_session() -> str:
    """POST /sessions → session_id. Lanza si la API falla."""
    response = requests.post(f"{API_BASE_URL}/api/v1/sessions", timeout=10)
    response.raise_for_status()
    return response.json()["session_id"]


def reset_conversation() -> None:
    """Nueva sesión en la API y limpia el estado local de Streamlit."""
    session_id = create_session()
    st.session_state.session_id = session_id
    st.session_state.project_metadata = EMPTY_METADATA.copy()
    st.session_state.last_estimation = None
    st.session_state.transcript = ""
    st.session_state.turn_count = 0


def ensure_session() -> None:
    """Crea sesión al cargar la página si aún no hay session_id."""
    if "session_id" not in st.session_state or not st.session_state.session_id:
        try:
            reset_conversation()
        except requests.RequestException:
            st.session_state.session_id = None
            st.session_state.project_metadata = EMPTY_METADATA.copy()
            st.session_state.last_estimation = None
            st.session_state.setdefault("transcript", "")
            st.session_state.setdefault("turn_count", 0)


def render_metadata_panel(metadata: dict[str, Any]) -> None:
    """Panel lateral: memoria estructurada vs historial de mensajes."""
    st.subheader("project_metadata")
    st.caption(
        "Memoria estructurada de la sesión (hechos). "
        "Es distinta del historial de mensajes (ventana deslizante)."
    )
    model = ProjectMetadata.model_validate(metadata)
    if not any(
        [
            model.project_name,
            model.assumed_team_size,
            model.mentioned_technologies,
            model.agreed_scope,
        ]
    ):
        st.info("Vacío (primer turno o aún sin hechos detectados).")
    else:
        if model.project_name:
            st.markdown(f"**project_name:** {model.project_name}")
        if model.assumed_team_size is not None:
            st.markdown(f"**assumed_team_size:** {model.assumed_team_size}")
        if model.mentioned_technologies:
            st.markdown(
                "**mentioned_technologies:** "
                + ", ".join(model.mentioned_technologies)
            )
        if model.agreed_scope:
            st.markdown(f"**agreed_scope:** {model.agreed_scope}")

    with st.expander("JSON crudo", expanded=False):
        st.json(model.model_dump())


def render_estimation(response: EstimationResponse) -> None:
    result = response.result
    st.markdown(result.summary)
    st.table(
        [
            {
                "Fase": phase.name,
                "Semanas": phase.duration_weeks,
                "Costo (EUR)": phase.cost_eur,
                "Resumen": phase.summary,
            }
            for phase in result.phases
        ]
    )
    st.markdown(
        f"**Total:** {result.total_duration_weeks} semanas · "
        f"{result.total_cost_eur:,} EUR · "
        f"Confianza: {result.confidence_pct}%"
    )


# --- Sidebar: conexión + sesión + metadata ---------------------------------
if _api_ok():
    st.sidebar.success("API conectada")
else:
    st.sidebar.error("API no disponible")

ensure_session()

st.sidebar.markdown("---")
st.sidebar.markdown("### Sesión")
if st.session_state.session_id:
    st.sidebar.code(st.session_state.session_id, language=None)
    st.sidebar.caption(f"Turnos en esta conversación: {st.session_state.get('turn_count', 0)}")
else:
    st.sidebar.warning("Sin session_id (¿API caída?)")

if st.sidebar.button("Nueva conversación", use_container_width=True):
    try:
        reset_conversation()
        st.sidebar.success("Nueva sesión creada")
        st.rerun()
    except requests.RequestException as exc:
        st.sidebar.error(f"No se pudo crear sesión: {exc}")

st.sidebar.markdown("---")
with st.sidebar:
    render_metadata_panel(st.session_state.get("project_metadata", EMPTY_METADATA))

# --- Main -----------------------------------------------------------------
st.title("Estimador CAG")
st.caption(
    "Transcribe la reunión, adjunta PDF/DOCX si hace falta y estima "
    "dentro de la sesión actual (memoria + historial)."
)

transcript = st.text_area(
    "Transcripción",
    height=240,
    key="transcript",
    placeholder="Pega aquí la transcripción o descripción del proyecto...",
    help="Mínimo 20 caracteres. Se envía a POST /sessions/{id}/estimate.",
)

attachments = st.file_uploader(
    "Documentación complementaria (PDF o DOCX)",
    type=["pdf", "docx"],
    accept_multiple_files=True,
    help="PDF se sube a la Files API del LLM; DOCX se extrae en local.",
)

col_submit, _ = st.columns([1, 3])
with col_submit:
    submitted = st.button("Generar estimación", type="primary", use_container_width=True)

if submitted:
    if not st.session_state.session_id:
        st.error("No hay sesión activa. Revisa la API o pulsa «Nueva conversación».")
    elif len((transcript or "").strip()) < 20:
        st.error("La transcripción debe tener al menos 20 caracteres.")
    else:
        session_id = st.session_state.session_id
        files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
        for upload in attachments or []:
            files_payload.append(
                (
                    "attachments",
                    (
                        upload.name,
                        upload.getvalue(),
                        upload.type or "application/octet-stream",
                    ),
                )
            )

        with st.spinner("Generando estimación..."):
            try:
                # Con archivos: multipart. Sin archivos: form-data solo transcript.
                response = requests.post(
                    f"{API_BASE_URL}/api/v1/sessions/{session_id}/estimate",
                    data={"transcript": transcript.strip()},
                    files=files_payload or None,
                    timeout=180,
                )
                response.raise_for_status()
                estimation = EstimationResponse.model_validate(response.json())
            except requests.ConnectionError:
                st.error(
                    "No se pudo conectar con la API. "
                    "Asegúrate de tener corriendo `uv run python main.py`."
                )
            except requests.Timeout:
                st.error("La solicitud tardó demasiado. Intenta de nuevo.")
            except requests.HTTPError:
                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text or f"HTTP {response.status_code}"
                st.error(f"Error de la API: {detail}")
            else:
                st.session_state.turn_count = st.session_state.get("turn_count", 0) + 1
                if estimation.project_metadata is not None:
                    st.session_state.project_metadata = (
                        estimation.project_metadata.model_dump()
                    )
                st.session_state.last_estimation = estimation.model_dump(mode="json")
                st.rerun()

if st.session_state.get("last_estimation"):
    st.subheader("Última estimación")
    last = EstimationResponse.model_validate(st.session_state.last_estimation)
    render_estimation(last)
    with st.expander("Detalles de la generación"):
        col_version, col_cached, col_confidence = st.columns(3)
        col_version.metric("Versión del prompt", last.prompt_version)
        col_cached.metric("Desde caché", "Sí" if last.cached else "No")
        col_confidence.metric("Confianza", f"{last.result.confidence_pct}%")

# También en el cuerpo: panel expandible (útil en móvil / layout wide).
with st.expander("project_metadata (memoria de sesión)", expanded=False):
    render_metadata_panel(st.session_state.get("project_metadata", EMPTY_METADATA))
    st.caption(
        f"session_id: `{st.session_state.get('session_id') or '—'}` · "
        "El historial de mensajes no se muestra aquí; solo la memoria estructurada."
    )
