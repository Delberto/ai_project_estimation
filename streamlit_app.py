import os

import requests
import streamlit as st
from pydantic import ValidationError

from app.schemas.estimations import (
    DetailLevel,
    EstimationRequest,
    EstimationResponse,
    OutputFormat,
    ProjectType,
)

st.set_page_config(page_title="Estimador CAG", layout="wide")

API_BASE_URL = st.sidebar.text_input(
    "URL de la API",
    value=os.getenv("API_BASE_URL", "http://localhost:8000"),
).rstrip("/")

health_url = f"{API_BASE_URL}/health"
try:
    health = requests.get(health_url, timeout=3)
    if health.ok:
        st.sidebar.success("API conectada")
    else:
        st.sidebar.warning("API respondió con error")
except requests.RequestException:
    st.sidebar.error("API no disponible")

PROJECT_TYPE_LABELS = {
    ProjectType.WEB_SAAS: "Web / SaaS",
    ProjectType.MOBILE_APP: "App móvil",
    ProjectType.INTERNAL_TOOL: "Herramienta interna",
    ProjectType.API: "API",
    ProjectType.DATA_PIPELINE: "Pipeline de datos",
}

DETAIL_LEVEL_LABELS = {
    DetailLevel.SUMMARY: "Resumen",
    DetailLevel.MEDIUM: "Medio",
    DetailLevel.DETAILED: "Detallado",
}

OUTPUT_FORMAT_LABELS = {
    OutputFormat.PHASES_TABLE: "Tabla por fases",
    OutputFormat.LINE_ITEMS: "Partidas",
    OutputFormat.NARRATIVE: "Narrativo",
}


def render_estimation(response: EstimationResponse, output_format: OutputFormat) -> None:
    result = response.result
    st.markdown(result.summary)

    if output_format == OutputFormat.PHASES_TABLE:
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
    elif output_format == OutputFormat.LINE_ITEMS:
        for index, phase in enumerate(result.phases, start=1):
            st.markdown(
                f"{index}. **{phase.name}** — {phase.duration_weeks} sem., "
                f"{phase.cost_eur:,} EUR — {phase.summary}"
            )
    else:
        for phase in result.phases:
            st.markdown(
                f"**{phase.name}** ({phase.duration_weeks} sem., {phase.cost_eur:,} EUR): "
                f"{phase.summary}"
            )

    st.markdown(
        f"**Total:** {result.total_duration_weeks} semanas · "
        f"{result.total_cost_eur:,} EUR · "
        f"Confianza: {result.confidence_pct}%"
    )


st.title("Estimador CAG")
st.caption("Describe el proyecto para generar una estimación.")

with st.form("estimation_form"):
    description = st.text_area(
        "Descripción del proyecto",
        height=240,
        placeholder="Describe el alcance, funcionalidades y restricciones del proyecto...",
        help="Mínimo 20 caracteres, máximo 2000.",
    )

    col_type, col_detail = st.columns(2)
    with col_type:
        project_type = st.selectbox(
            "Tipo de proyecto",
            options=list(ProjectType),
            format_func=lambda option: PROJECT_TYPE_LABELS[option],
        )
    with col_detail:
        detail_level = st.selectbox(
            "Nivel de detalle",
            options=list(DetailLevel),
            format_func=lambda option: DETAIL_LEVEL_LABELS[option],
        )

    output_format = st.selectbox(
        "Formato de salida",
        options=list(OutputFormat),
        format_func=lambda option: OUTPUT_FORMAT_LABELS[option],
    )

    submitted = st.form_submit_button("Generar estimación", type="primary")

if submitted:
    try:
        request = EstimationRequest(
            description=description.strip(),
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
        )
    except ValidationError as exc:
        for error in exc.errors():
            st.error(error["msg"])
    else:
        with st.spinner("Generando estimación..."):
            try:
                response = requests.post(
                    f"{API_BASE_URL}/api/v1/estimate",
                    json=request.model_dump(mode="json"),
                    timeout=120,
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
                st.subheader("Estimación")
                render_estimation(estimation, output_format)

                with st.expander("Detalles de la generación"):
                    col_version, col_cached, col_confidence = st.columns(3)
                    col_version.metric("Versión del prompt", estimation.prompt_version)
                    col_cached.metric("Desde caché", "Sí" if estimation.cached else "No")
                    col_confidence.metric("Confianza", f"{estimation.result.confidence_pct}%")
