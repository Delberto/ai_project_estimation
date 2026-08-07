from app.schemas.estimations import EstimationResult, Phase
from app.services.metadata_extractor import (
    extract_metadata_from_turn,
    merge_project_metadata,
    update_project_metadata,
)
from app.services.sessions import ProjectMetadata


def _result(**overrides) -> EstimationResult:
    defaults = {
        "summary": (
            "Estimación para el proyecto FleetTrack con stack React y PostgreSQL."
        ),
        "confidence_pct": 70,
        "phases": [
            Phase(
                name="Discovery",
                duration_weeks=2,
                cost_eur=4000,
                summary="Levantamiento de requisitos y arquitectura inicial.",
            )
        ],
        "total_duration_weeks": 2,
        "total_cost_eur": 4000,
    }
    defaults.update(overrides)
    return EstimationResult(**defaults)


def test_extracts_name_technologies_and_team_size() -> None:
    user_text = (
        "Necesitamos estimar el proyecto llamado FleetTrack: app web con React, "
        "Node.js y PostgreSQL. Equipo de 4 desarrolladores."
    )
    meta = extract_metadata_from_turn(user_text=user_text, result=_result())

    assert meta.project_name == "FleetTrack"
    assert meta.assumed_team_size == 4
    assert "React" in meta.mentioned_technologies
    assert "Node.js" in meta.mentioned_technologies
    assert "PostgreSQL" in meta.mentioned_technologies
    assert meta.agreed_scope is not None
    assert "FleetTrack" in meta.agreed_scope


def test_merge_preserves_known_facts_and_unions_technologies() -> None:
    current = ProjectMetadata(
        project_name="FleetTrack",
        assumed_team_size=3,
        mentioned_technologies=["React"],
        agreed_scope="Alcance inicial",
    )
    incoming = ProjectMetadata(
        project_name=None,
        assumed_team_size=5,
        mentioned_technologies=["PostgreSQL", "react"],
        agreed_scope=None,
    )
    merged = merge_project_metadata(current, incoming)

    assert merged.project_name == "FleetTrack"
    assert merged.assumed_team_size == 5
    assert merged.mentioned_technologies == ["React", "PostgreSQL"]
    assert merged.agreed_scope == "Alcance inicial"


def test_update_project_metadata_end_to_end() -> None:
    current = ProjectMetadata()
    updated = update_project_metadata(
        current,
        user_text=(
            "Portal SaaS de flotas con React Native y Firebase. "
            "Equipo de 2 developers."
        ),
        result=_result(
            summary="Portal móvil de flotas con sync offline y alertas."
        ),
    )

    assert updated.assumed_team_size == 2
    assert "React Native" in updated.mentioned_technologies
    assert "Firebase" in updated.mentioned_technologies
    assert updated.agreed_scope.startswith("Portal móvil")
