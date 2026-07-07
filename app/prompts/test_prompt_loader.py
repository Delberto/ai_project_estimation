from app.prompts.loader import render_estimation_prompt
from app.schemas.schemas import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)

DESCRIPTION = (
    "Portal de gestión de flotas con GPS en tiempo real y alertas de mantenimiento."
)
ASSUMPTIONS_PER_PHASE_INSTRUCTION = "Lista asunciones explícitas por fase"


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


def test_system_prompt_includes_phases_table_keyword_only_for_phases_table() -> None:
    phases_system, _ = render_estimation_prompt(
        _make_request(output_format=OutputFormat.PHASES_TABLE)
    )
    narrative_system, _ = render_estimation_prompt(
        _make_request(output_format=OutputFormat.NARRATIVE)
    )

    assert "phases_table" in phases_system
    assert "phases_table" not in narrative_system


def test_system_prompt_includes_assumptions_per_phase_only_for_detailed() -> None:
    detailed_system, _ = render_estimation_prompt(
        _make_request(detail_level=DetailLevel.DETAILED)
    )
    summary_system, _ = render_estimation_prompt(
        _make_request(detail_level=DetailLevel.SUMMARY)
    )

    assert ASSUMPTIONS_PER_PHASE_INSTRUCTION in detailed_system
    assert ASSUMPTIONS_PER_PHASE_INSTRUCTION not in summary_system
