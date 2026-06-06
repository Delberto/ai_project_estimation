import os

import requests
import streamlit as st
# Inicia la historia del chat 
st.set_page_config(page_title="Estimador CAG", layout="wide")
if "messages" not in st.session_state:
    st.session_state.messages = []
#Itera la historia del chat y la muestra en la interfaz

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

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

st.title("Estimador CAG")
st.caption("Pega la transcripción de una reunión para generar una estimación.")

transcription = st.text_area(
    "Transcripción",
    height=240,
    placeholder="Pega aquí la transcripción de la reunión con el cliente...",
)

if st.button(
    "Generar estimación",
    type="primary",
    disabled=not transcription.strip(),
):
    with st.spinner("Generando estimación..."):
        try:
            response = requests.post(
                f"{API_BASE_URL}/api/v1/estimate",
                json={"transcription": transcription.strip()},
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
        except requests.ConnectionError:
            st.error(
                "No se pudo conectar con la API. "
                "Asegúrate de tener corriendo `uv run python main.py`."
            )
        except requests.Timeout:
            st.error("La solicitud tardó demasiado. Intenta de nuevo.")
        except requests.HTTPError:
            detail = response.json().get("detail", response.text)
            st.error(f"Error de la API: {detail}")
        else:

            message = st.chat_message("assistant")
            message.markdown(data["estimation"])

            with st.expander("Detalles de la generación"):
                col_model, col_provider, col_tokens, col_cost = st.columns(4)
                col_model.metric("Modelo", data["model"])
                col_provider.metric("Proveedor", data["provider"])
                col_tokens.metric("Tokens", data.get("total_tokens") or "—")
                st.session_state.messages.append({"role": "assistant", "content": data["estimation"]})

                cost_parts = []
                if data.get("cost_usd") is not None:
                    cost_parts.append(f"USD ${data['cost_usd']:.4f}")
                if data.get("cost_mxn") is not None:
                    cost_parts.append(f"MXN ${data['cost_mxn']:.2f}")
                col_cost.metric("Costo", " · ".join(cost_parts) if cost_parts else "—")

                st.caption(f"Generado: {data['generated_at']}")
