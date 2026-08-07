from app.prompts.loader import render_estimation_prompt
from app.schemas.estimations import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)
from app.services.sessions import ProjectMetadata

DESCRIPTION = (
    "Portal de gestión de flotas con GPS en tiempo real y alertas de mantenimiento."
)
ASSUMPTIONS_PER_PHASE_INSTRUCTION = "supuestos explícitos y riesgos técnicos"


def _make_request(**overrides) -> EstimationRequest:
    defaults = {
        "description": DESCRIPTION,
        "project_type": ProjectType.WEB_SAAS,
        "detail_level": DetailLevel.MEDIUM,
        "output_format": OutputFormat.PHASES_TABLE,
    }
    defaults.update(overrides)
    return EstimationRequest(**defaults)


def test_user_prompt_wraps_description_in_project_description_block() -> None:
    _, user = render_estimation_prompt(_make_request())

    expected_block = f"<project_description>\n{DESCRIPTION}\n</project_description>"
    assert expected_block in user


def test_system_prompt_reflects_requested_output_format() -> None:
    phases_system, _ = render_estimation_prompt(
        _make_request(output_format=OutputFormat.PHASES_TABLE)
    )
    narrative_system, _ = render_estimation_prompt(
        _make_request(output_format=OutputFormat.NARRATIVE)
    )

    assert "(phases_table)" in phases_system
    assert "(narrative)" in narrative_system


def test_system_prompt_includes_assumptions_per_phase_only_for_detailed() -> None:
    detailed_system, _ = render_estimation_prompt(
        _make_request(detail_level=DetailLevel.DETAILED)
    )
    summary_system, _ = render_estimation_prompt(
        _make_request(detail_level=DetailLevel.SUMMARY)
    )

    assert ASSUMPTIONS_PER_PHASE_INSTRUCTION in detailed_system
    assert ASSUMPTIONS_PER_PHASE_INSTRUCTION not in summary_system


def test_system_prompt_includes_empty_project_metadata_block_by_default() -> None:
    system, _ = render_estimation_prompt(_make_request())

    assert "<project_metadata>" in system
    assert "</project_metadata>" in system
    assert "project_name:" not in system
    assert "mentioned_technologies:" not in system


def test_system_prompt_injects_populated_project_metadata() -> None:
    metadata = ProjectMetadata(
        project_name="FleetTrack",
        assumed_team_size=3,
        mentioned_technologies=["React", "PostgreSQL"],
        agreed_scope="GPS en tiempo real y alertas de mantenimiento.",
    )
    system, _ = render_estimation_prompt(
        _make_request(),
        project_metadata=metadata,
    )

    start = system.index("<project_metadata>")
    end = system.index("</project_metadata>")
    block = system[start:end]

    assert "- project_name: FleetTrack" in block
    assert "- assumed_team_size: 3" in block
    assert "- mentioned_technologies: React, PostgreSQL" in block
    assert "- agreed_scope: GPS en tiempo real y alertas de mantenimiento." in block