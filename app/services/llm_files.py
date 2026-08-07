"""Subida de PDFs a la Files API de OpenAI o Anthropic.

Flujo
-----
1. El caller decide el proveedor según el modelo activo (``openai`` /
   ``anthropic``).
2. :func:`upload_pdf_to_provider` envía el binario y devuelve un
   :class:`ProviderUploadedFile` con el ``file_id``.
3. Ese ``file_id`` se embebe en el mensaje user del LLM (ver
   :func:`build_user_content_with_pdfs` y ``llm_wrapper``).
4. Tras la llamada, :func:`delete_provider_file` limpia el archivo remoto
   (best-effort: un fallo de borrado no tumba la estimación).

Notas por proveedor
-------------------
- **OpenAI**: ``client.files.create(file=..., purpose=\"user_data\")``.
  En Chat Completions se referencia como
  ``{\"type\": \"file\", \"file\": {\"file_id\": \"...\"}}``.
- **Anthropic**: beta Files API
  (``anthropic-beta: files-api-2025-04-14``). Se referencia como bloque
  ``document`` con ``source.type = \"file\"``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from openai import OpenAI

from app.config import settings

log = structlog.get_logger()

ProviderName = Literal["openai", "anthropic"]

# Header beta requerido por la Files API de Anthropic.
ANTHROPIC_FILES_BETA = "files-api-2025-04-14"


class FileUploadError(RuntimeError):
    """Fallo al subir o borrar un archivo en la Files API del proveedor."""


@dataclass(frozen=True)
class ProviderUploadedFile:
    """Metadatos de un PDF ya alojado en la Files API del proveedor."""

    file_id: str
    filename: str
    provider: ProviderName
    size_bytes: int


def upload_pdf_to_provider(
    *,
    filename: str,
    data: bytes,
    provider: str,
) -> ProviderUploadedFile:
    """Sube un PDF a OpenAI o Anthropic y devuelve su ``file_id``.

    Parameters
    ----------
    filename:
        Nombre visible del fichero (se envía al proveedor).
    data:
        Contenido binario PDF.
    provider:
        ``\"openai\"`` o ``\"anthropic\"``.
    """
    normalised = _normalise_provider(provider)
    safe_name = filename if filename.lower().endswith(".pdf") else f"{filename}.pdf"

    if normalised == "openai":
        return _upload_openai(safe_name, data)
    return _upload_anthropic(safe_name, data)


def delete_provider_file(uploaded: ProviderUploadedFile) -> None:
    """Borra un archivo remoto. Errores se registran y se ignoran."""
    try:
        if uploaded.provider == "openai":
            _openai_client().files.delete(uploaded.file_id)
        else:
            client = _anthropic_client()
            client.beta.files.delete(
                uploaded.file_id,
                betas=[ANTHROPIC_FILES_BETA],
            )
        log.info(
            "provider_file_deleted",
            file_id=uploaded.file_id,
            provider=uploaded.provider,
            filename=uploaded.filename,
        )
    except Exception as exc:  # best-effort cleanup
        log.warning(
            "provider_file_delete_failed",
            file_id=uploaded.file_id,
            provider=uploaded.provider,
            error=str(exc),
        )


def build_user_content_with_pdfs(
    *,
    text: str,
    pdf_uploads: list[ProviderUploadedFile],
    provider: str,
) -> str | list[dict[str, Any]]:
    """Construye el ``content`` del mensaje user (texto ± bloques PDF).

    Si no hay PDFs, devuelve el string tal cual (mismo contrato que antes).
    Con PDFs, devuelve una lista de content-parts en el formato del
    proveedor activo para que LiteLLM/Instructor lo reenvíen al modelo.
    """
    if not pdf_uploads:
        return text

    normalised = _normalise_provider(provider)
    if normalised == "openai":
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for uploaded in pdf_uploads:
            parts.append(
                {
                    "type": "file",
                    "file": {"file_id": uploaded.file_id},
                }
            )
        return parts

    # Anthropic: document blocks + text.
    parts = [{"type": "text", "text": text}]
    for uploaded in pdf_uploads:
        parts.append(
            {
                "type": "document",
                "source": {
                    "type": "file",
                    "file_id": uploaded.file_id,
                },
            }
        )
    return parts


def _upload_openai(filename: str, data: bytes) -> ProviderUploadedFile:
    try:
        # purpose=user_data: ficheros pensados para pasarse como input al modelo.
        created = _openai_client().files.create(
            file=(filename, io.BytesIO(data), "application/pdf"),
            purpose="user_data",
        )
    except Exception as exc:
        raise FileUploadError(
            f"Error al subir PDF a OpenAI Files API ({filename!r}): {exc}"
        ) from exc

    file_id = created.id
    size = int(getattr(created, "bytes", None) or len(data))
    log.info(
        "openai_file_uploaded",
        file_id=file_id,
        filename=filename,
        size_bytes=size,
    )
    return ProviderUploadedFile(
        file_id=file_id,
        filename=filename,
        provider="openai",
        size_bytes=size,
    )


def _upload_anthropic(filename: str, data: bytes) -> ProviderUploadedFile:
    if not settings.ANTHROPIC_API_KEY:
        raise FileUploadError(
            "ANTHROPIC_API_KEY no configurada; no se pueden subir PDFs a Anthropic"
        )
    try:
        client = _anthropic_client()
        created = client.beta.files.upload(
            file=(filename, io.BytesIO(data), "application/pdf"),
            betas=[ANTHROPIC_FILES_BETA],
        )
    except Exception as exc:
        raise FileUploadError(
            f"Error al subir PDF a Anthropic Files API ({filename!r}): {exc}"
        ) from exc

    file_id = created.id
    size = int(getattr(created, "size_bytes", None) or len(data))
    log.info(
        "anthropic_file_uploaded",
        file_id=file_id,
        filename=filename,
        size_bytes=size,
    )
    return ProviderUploadedFile(
        file_id=file_id,
        filename=filename,
        provider="anthropic",
        size_bytes=size,
    )


def _openai_client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _anthropic_client() -> Any:
    # Import diferido: anthropic es opcional si solo se usa OpenAI.
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise FileUploadError(
            "El paquete 'anthropic' no está instalado; "
            "añádelo para subir PDFs a Anthropic Files API"
        ) from exc
    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _normalise_provider(provider: str) -> ProviderName:
    name = provider.lower().strip()
    if name not in ("openai", "anthropic"):
        raise FileUploadError(
            f"Proveedor no soportado para Files API: {provider!r} "
            "(usa 'openai' o 'anthropic')"
        )
    return name  # type: ignore[return-value]
