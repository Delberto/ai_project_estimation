"""Extracción local de texto y preparación de adjuntos para el LLM.

Estrategia por formato
----------------------
- **PDF**  → se sube al proveedor (OpenAI / Anthropic) vía Files API y se
  referencia por ``file_id`` en el mensaje al modelo. El binario no se
  convierte a texto aquí: el propio LLM lo lee.
- **DOCX** → extracción local con ``python-docx``; el texto se concatena a
  la transcripción. Word no se sube por Files API (soporte limitado /
  inconsistente entre proveedores).

El router multipart lee los ``UploadFile``, llama a
:func:`prepare_attachments` y obtiene:
1. ``description`` — transcript + texto DOCX (separadores claros).
2. ``pdf_uploads`` — metadatos de PDFs ya subidos al proveedor (para el LLM).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document

from app.services.llm_files import ProviderUploadedFile, upload_pdf_to_provider

# Extensiones aceptadas en multipart. Comparación case-insensitive.
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx"})


class UnsupportedDocumentError(ValueError):
    """El adjunto no es PDF ni DOCX."""


class DocumentExtractionError(ValueError):
    """El archivo parece válido pero no se pudo leer (corrupto / vacío)."""


@dataclass
class PreparedAttachments:
    """Resultado de procesar los adjuntos multipart.

    Attributes
    ----------
    description:
        Texto listo para ``EstimationRequest.description``: transcript más
        cualquier DOCX extraído en local.
    pdf_uploads:
        PDFs ya subidos a la Files API del proveedor activo. Vacío si no
        había PDFs o si el caller no pidió upload.
    """

    description: str
    pdf_uploads: list[ProviderUploadedFile] = field(default_factory=list)


def extract_docx_text(filename: str, data: bytes) -> str:
    """Extrae párrafos y celdas de tabla de un ``.docx``.

    Raises
    ------
    DocumentExtractionError
        DOCX vacío, ilegible o sin texto usable.
    """
    if not data:
        raise DocumentExtractionError(f"El archivo {filename!r} está vacío")

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentExtractionError(f"DOCX ilegible: {exc}") from exc

    chunks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            chunks.append(text)

    # Muchas specs viven en tablas; las aplanamos celda a celda.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    chunks.append(cell_text)

    cleaned = "\n".join(chunks).strip()
    if not cleaned:
        raise DocumentExtractionError(
            f"No se pudo extraer texto de {filename!r} "
            "(¿documento vacío o solo imágenes?)"
        )
    return cleaned


def prepare_attachments(
    transcript: str,
    attachments: list[tuple[str, bytes]],
    *,
    provider: str,
) -> PreparedAttachments:
    """Procesa adjuntos multipart: DOCX → texto local; PDF → Files API.

    Parameters
    ----------
    transcript:
        Texto de la reunión / descripción del proyecto.
    attachments:
        Lista ``(filename, raw_bytes)`` leída desde ``UploadFile``.
    provider:
        ``\"openai\"`` o ``\"anthropic\"`` — decide a qué Files API subir
        los PDFs (debe coincidir con el modelo que generará la estimación).

    Returns
    -------
    PreparedAttachments
        Descripción combinada + lista de PDFs subidos.

    Raises
    ------
    UnsupportedDocumentError
        Extensión distinta de ``.pdf`` / ``.docx``.
    DocumentExtractionError
        Fallo al extraer un DOCX.
    FileUploadError
        Fallo al subir un PDF al proveedor (propagada desde ``llm_files``).
    """
    parts: list[str] = [transcript.strip()]
    pdf_uploads: list[ProviderUploadedFile] = []

    for filename, data in attachments:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise UnsupportedDocumentError(
                f"Formato no soportado: {suffix or '(sin extensión)'}. "
                f"Usa uno de: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        safe_name = Path(filename).name or "unnamed"

        if suffix == ".docx":
            extracted = extract_docx_text(safe_name, data)
            parts.append(f"--- attachment: {safe_name} ---")
            parts.append(extracted)
            continue

        # PDF: subir al proveedor; el LLM lo recibe por file_id.
        if not data:
            raise DocumentExtractionError(f"El archivo {safe_name!r} está vacío")
        uploaded = upload_pdf_to_provider(
            filename=safe_name,
            data=data,
            provider=provider,
        )
        pdf_uploads.append(uploaded)
        # Marcamos en el texto que hay un PDF adjunto (útil en el historial
        # y para que el prompt mencione el documento aunque el file_id vaya
        # aparte en el mensaje multimodal).
        parts.append(f"--- attachment (pdf via Files API): {safe_name} ---")
        parts.append(
            f"[PDF adjunto subido al proveedor {provider}: "
            f"file_id={uploaded.file_id}]"
        )

    return PreparedAttachments(
        description="\n\n".join(parts),
        pdf_uploads=pdf_uploads,
    )
