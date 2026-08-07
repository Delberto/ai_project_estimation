# ai_project_estimation

API FastAPI + cliente Streamlit para estimar proyectos de software con LLM
(salida estructurada vía Instructor) y memoria de sesión multi-turno.

## Adjuntos (PDF / DOCX)

`POST /sessions/{session_id}/estimate` acepta `multipart/form-data` con
`transcript` y `attachments` opcionales. La estrategia por formato está en
`app/services/document_extractor.py`:

| Formato | Camino elegido | Por qué |
|--------|----------------|---------|
| **PDF** | Upload a la **Files API** del proveedor (OpenAI / Anthropic) y referencia por `file_id` en el mensaje multimodal al LLM | El modelo lee el documento nativo (layout, tablas); evita OCR/extracción frágil en local |
| **DOCX** | Extracción de texto **en local** (`python-docx`) y concatenación a la transcripción | El soporte de Word en Files API es limitado/inconsistente entre proveedores; el texto plano basta para estimar |

Los PDFs remotos se borran tras la llamada al LLM (cleanup best-effort).

## Project metadata

Tras cada turno de `POST /sessions/{session_id}/estimate`, el sistema acumula
hechos del proyecto en `ProjectMetadata` y los reinyecta en el system prompt
dentro de un bloque XML:

```text
<project_metadata>
- project_name: …
- assumed_team_size: …
- mentioned_technologies: …
- agreed_scope: …
</project_metadata>
```

En la **primera llamada** de la sesión el metadata está vacío: el bloque
existe pero sin campos. En turnos siguientes el LLM ve el contexto acumulado
sin que el cliente lo reenvíe.

### Decisión: heurística vs extractor LLM

Para actualizar el metadata elegimos una **heurística local**
(`app/services/metadata_extractor.py`) en lugar de una segunda llamada al LLM:

| Enfoque | Pros | Contras |
|---------|------|---------|
| **Heurística (elegida)** | Sin latencia ni coste extra por turno; determinista y testeable; aprovecha el `EstimationResult` ya estructurado | Menos cobertura en redacción libre / nombres poco convencionales |
| Extractor LLM | Más robusto ante lenguaje natural ambiguo | +1 llamada por turno (coste, latencia, posibles fallos) |

La heurística combina regex (nombre de proyecto, tamaño de equipo) con un
diccionario de tecnologías conocidas sobre el texto del usuario y el
`summary`/fases de la estimación. El merge es acumulativo: no borra hechos
ya conocidos y une tecnologías sin duplicar.

Si en una fase posterior la cobertura se queda corta, el mismo contrato
`ProjectMetadata` permite sustituir el extractor por una llamada Instructor
sin tocar el template Jinja.
