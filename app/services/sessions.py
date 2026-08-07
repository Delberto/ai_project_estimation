"""Estado de sesión para conversaciones multi-turno de estimación.

Este módulo es el corazón de la "memoria" del servicio IA entre páginas:

- :class:`ProjectMetadata` — hechos estructurados del proyecto (nombre, stack…).
- :class:`ConversationHistory` — buffer de mensajes con ventana deslizante
  que **nunca** descarta el system prompt.
- :class:`Session` / :class:`SessionStore` — registro en memoria keyed por
  UUID v4. El cliente obtiene el id con ``POST /sessions`` y lo reutiliza
  en ``POST /sessions/{session_id}/estimate``.

Nota de despliegue: el store es **process-local**. Con varios workers de
Uvicorn cada proceso tiene su propio diccionario; en producción habría que
cambiar a Redis u otro backend compartido.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.config import settings

if TYPE_CHECKING:
    from app.schemas.estimations import EstimationRequest

# Roles admitidos en el historial (formato chat OpenAI / LiteLLM).
MessageRole = Literal["system", "user", "assistant"]
# Un mensaje es un dict con al menos ``role`` y ``content``.
Message = dict[str, Any]

# Valor por defecto de la ventana (ajustable vía ``Settings.MAX_TURNS``).
MAX_TURNS = 6


class ProjectMetadata(BaseModel):
    """Contexto de proyecto acumulado a lo largo de la conversación.

    Se rellena tras cada turno con la heurística de
    :mod:`app.services.metadata_extractor` y se reinyecta en el system
    prompt (bloque ``<project_metadata>``) en llamadas posteriores.
    """

    project_name: str | None = Field(
        default=None,
        max_length=128,
        description="Nombre de trabajo del proyecto en estimación.",
    )
    assumed_team_size: int | None = Field(
        default=None,
        ge=1,
        le=500,
        description="Tamaño de equipo asumido, si se mencionó.",
    )
    mentioned_technologies: list[str] = Field(
        default_factory=list,
        description="Tecnologías citadas explícitamente en la conversación.",
    )
    agreed_scope: str | None = Field(
        default=None,
        max_length=8000,
        description="Resumen en texto libre del alcance acordado hasta ahora.",
    )


class ConversationHistory:
    """Buffer de mensajes con ventana deslizante.

    Invariante clave
    ----------------
    El system prompt **no** vive dentro de la lista recortable: se guarda
    aparte y siempre se antepone en :meth:`to_messages_list`. Así, aunque
    descartemos turnos antiguos, las instrucciones del sistema permanecen.

    Un "turno" = un par ``user`` + ``assistant``. Al superar ``max_turns``
    se eliminan los pares más antiguos.
    """

    def __init__(
        self,
        *,
        system_prompt: str,
        max_turns: int | None = None,
    ) -> None:
        resolved = settings.MAX_TURNS if max_turns is None else max_turns
        if resolved < 1:
            raise ValueError("max_turns must be at least 1")
        self.system_prompt = system_prompt
        self.max_turns = resolved
        # Solo user/assistant. El system va fuera para no destruirlo al trim.
        self._messages: list[Message] = []

    @property
    def turn_count(self) -> int:
        """Cantidad de mensajes ``user`` actualmente almacenados."""
        return sum(1 for message in self._messages if message["role"] == "user")

    def add_user(self, content: str) -> None:
        """Añade un turno de usuario y, si hace falta, recorta la ventana."""
        self._messages.append({"role": "user", "content": content})
        self._trim()

    def add_assistant(self, content: str) -> None:
        """Añade la respuesta del asistente al turno más reciente."""
        self._messages.append({"role": "assistant", "content": content})

    def to_messages_list(
        self,
        project_metadata: ProjectMetadata,
        *,
        request: EstimationRequest,
        version: str = "v1",
    ) -> list[Message]:
        """Array ``messages`` listo para la API del LLM.

        Regenera el system prompt a partir del ``project_metadata`` actual
        (vía el template Jinja) y lo antepone al historial user/assistant
        de la ventana. Actualiza :attr:`system_prompt` para mantener el
        invariante al día.
        """
        # Import diferido: ``prompts.loader`` importa ``ProjectMetadata`` de aquí.
        from app.prompts.loader import render_estimation_prompt

        system_prompt, _ = render_estimation_prompt(
            request,
            version=version,
            project_metadata=project_metadata,
        )
        self.system_prompt = system_prompt
        return [
            {"role": "system", "content": system_prompt},
            *self._messages,
        ]

    def to_messages(self) -> list[Message]:
        """Compat: ``[system almacenado, ...user/assistant]`` sin regenerar."""
        return [
            {"role": "system", "content": self.system_prompt},
            *self._messages,
        ]

    def _trim(self) -> None:
        """Descarta los pares user+assistant más antiguos hasta caber."""
        while self.turn_count > self.max_turns:
            drop_index = next(
                index
                for index, message in enumerate(self._messages)
                if message["role"] == "user"
            )
            drop_end = drop_index + 1
            if (
                drop_end < len(self._messages)
                and self._messages[drop_end]["role"] == "assistant"
            ):
                drop_end += 1
            del self._messages[drop_index:drop_end]


@dataclass
class Session:
    """Una conversación viva: id, metadata estructurada e historial opcional.

    ``history`` arranca en ``None`` y se materializa en el primer
    ``/estimate`` de la sesión, cuando ya conocemos el system prompt.
    """

    session_id: str
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)
    history: ConversationHistory | None = None


class SessionStore:
    """Registro en memoria de sesiones indexadas por UUID v4.

    API mínima:
    - :meth:`create` — reserva un id nuevo.
    - :meth:`get` — recupera la sesión o ``None`` (el router traduce a 404).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        """Crea y registra una sesión con un UUID v4 fresco."""
        session_id = str(uuid.uuid4())
        session = Session(session_id=session_id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Devuelve la sesión o ``None`` si el id no existe (o el proceso
        reinició y se perdió el store en memoria)."""
        return self._sessions.get(session_id)


# Singleton de proceso: todos los routers comparten el mismo store.
session_store = SessionStore()
