from enum import Enum

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    WEB_SAAS = "web_saas"
    MOBILE_APP = "mobile_saas"
    INTERNAL_TOOL = "internal_tool"
    API = "api"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


class EstimationRequest(BaseModel):
    description: str = Field(min_length=20, max_length=2000)
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat


class EstimationResponse(BaseModel):
    text: str
    prompt_version: str
