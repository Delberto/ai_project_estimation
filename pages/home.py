import os

import requests
import streamlit as st

st.set_page_config(page_title="Inicio", layout="wide")

api_base_url = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

st.title("Inicio")
st.write(
    "Esta app usa Streamlit como interfaz y FastAPI como backend. "
    "Ve a **streamlit app** en el sidebar para generar estimaciones."
)

st.subheader("Endpoints")
st.markdown(
    f"""
- **Health:** `{api_base_url}/health`
- **Estimar:** `POST {api_base_url}/api/v1/estimate`
- **Documentación:** [{api_base_url}/docs]({api_base_url}/docs)
"""
)

try:
    health = requests.get(f"{api_base_url}/health", timeout=3)
    if health.ok:
        st.success(f"API activa: `{health.json()}`")
    else:
        st.warning("La API respondió, pero no con status OK.")
except requests.RequestException:
    st.error(
        "La API no está disponible. Iníciala con:\n\n"
        "```bash\nuv run python main.py\n```"
    )
