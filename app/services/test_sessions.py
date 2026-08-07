"""Tests de ventana deslizante y to_messages_list en ConversationHistory."""

from __future__ import annotations

from app.schemas.estimations import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)
from app.services.sessions import (
    MAX_TURNS,
    ConversationHistory,
    ProjectMetadata,
)


def _request(description: str = "Necesitamos un SaaS de facturación con login.") -> EstimationRequest:
    return EstimationRequest(
        description=description,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
    )


def test_max_turns_default_is_six() -> None:
    assert MAX_TURNS == 6
    history = ConversationHistory(system_prompt="sys")
    assert history.max_turns == 6


def test_system_prompt_is_invariant_when_trimming() -> None:
    history = ConversationHistory(system_prompt="SYSTEM_V1", max_turns=2)
    for i in range(3):
        history.add_user(f"user-{i}")
        history.add_assistant(f"assistant-{i}")

    messages = history.to_messages()
    assert messages[0] == {"role": "system", "content": "SYSTEM_V1"}
    assert history.turn_count == 2
    # Solo los dos turnos más recientes.
    user_contents = [m["content"] for m in messages if m["role"] == "user"]
    assert user_contents == ["user-1", "user-2"]


def test_trim_discards_oldest_user_assistant_pairs() -> None:
    history = ConversationHistory(system_prompt="sys", max_turns=2)
    history.add_user("u0")
    history.add_assistant("a0")
    history.add_user("u1")
    history.add_assistant("a1")
    history.add_user("u2")  # dispara trim del par u0+a0

    assert history.turn_count == 2
    roles = [(m["role"], m["content"]) for m in history.to_messages()[1:]]
    assert roles == [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
    ]


def test_to_messages_list_regenerates_system_from_project_metadata() -> None:
    history = ConversationHistory(system_prompt="stale-system", max_turns=MAX_TURNS)
    history.add_user("primer turno del usuario")
    history.add_assistant("respuesta previa")
    history.add_user("segundo turno")

    metadata = ProjectMetadata(
        project_name="FacturaGo",
        assumed_team_size=4,
        mentioned_technologies=["Python", "React"],
        agreed_scope="MVP de facturación",
    )
    messages = history.to_messages_list(
        metadata,
        request=_request(),
        version="v1",
    )

    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert "stale-system" not in system
    assert "<project_metadata>" in system
    assert "FacturaGo" in system
    assert "assumed_team_size: 4" in system
    assert "Python" in system and "React" in system
    assert "MVP de facturación" in system
    # El historial user/assistant se conserva tras el system regenerado.
    assert [m["role"] for m in messages[1:]] == ["user", "assistant", "user"]
    # Invariante actualizado en la instancia.
    assert history.system_prompt == system


def test_to_messages_list_ready_for_llm_api_shape() -> None:
    history = ConversationHistory(system_prompt="sys", max_turns=3)
    history.add_user("hola")
    messages = history.to_messages_list(
        ProjectMetadata(),
        request=_request(),
    )
    assert isinstance(messages, list)
    assert all("role" in m and "content" in m for m in messages)
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
