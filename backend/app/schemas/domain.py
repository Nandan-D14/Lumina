from __future__ import annotations

from typing import Annotated, Literal, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator, model_validator


ScalarValue = Union[StrictInt, StrictFloat, str]


class Metric(BaseModel):
    label: str
    value: ScalarValue
    


class Entity(BaseModel):
    name: str
    type: str
    value: Optional[ScalarValue] = None
    


class TableData(BaseModel):
    name: str
    columns: List[str]
    rows: List[List[Optional[ScalarValue]]]
    


class Citation(BaseModel):
    title: str
    url: Optional[str] = None
    artifact_name: Optional[str] = None
    

    @model_validator(mode="after")
    def validate_reference(self) -> "Citation":
        if not self.url and not self.artifact_name:
            raise ValueError("Citation requires either url or artifact_name.")
        return self


class ArtifactRef(BaseModel):
    name: str
    mime_type: str
    version: int
    


class VisualizationSpec(BaseModel):
    id: str
    title: str
    kind: Literal["bar", "line", "pie", "table"]
    reason: str
    labels: Optional[List[str]] = None
    values: Optional[List[float]] = None
    

    @model_validator(mode="after")
    def validate_shape(self) -> "VisualizationSpec":
        if self.kind in {"bar", "line", "pie"}:
            if not self.labels or not self.values:
                raise ValueError("Chart visualizations require labels and values.")
            if len(self.labels) != len(self.values):
                raise ValueError("Visualization labels and values must be equal in length.")
        return self


class TextSourceInput(BaseModel):
    type: Literal["text"]
    text: str
    title: Optional[str] = None
    

    @field_validator("text")
    @classmethod
    def validate_text(cls, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Text source cannot be empty.")
        return normalized


class UrlSourceInput(BaseModel):
    type: Literal["url"]
    url: str
    title: Optional[str] = None
    

    @field_validator("url")
    @classmethod
    def validate_url(cls, url: str) -> str:
        normalized = url.strip()
        if not normalized:
            raise ValueError("URL source cannot be empty.")
        return normalized


class FileSourceInput(BaseModel):
    type: Literal["file"]
    filename: str
    mime_type: str
    content_base64: str
    

    @field_validator("filename", "mime_type", "content_base64")
    @classmethod
    def validate_file_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("File source fields cannot be empty.")
        return normalized


SourceInput = Annotated[TextSourceInput | UrlSourceInput | FileSourceInput, Field(discriminator="type")]


class NormalizedSource(BaseModel):
    source_id: str
    source_type: Literal["text", "url", "file"]
    title: str
    mime_type: str
    text_content: str
    tables: List[TableData] = Field(default_factory=list)
    citation: Citation
    artifact_names: List[str] = Field(default_factory=list)
    


class ResearchBranch(BaseModel):
    summary: str
    findings: List[str] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    artifact_names: List[str] = Field(default_factory=list)
    


class InsightsBranch(BaseModel):
    summary: str
    insights: List[str] = Field(default_factory=list)
    metrics: List[Metric] = Field(default_factory=list)
    


class EntitiesBranch(BaseModel):
    entities: List[Entity] = Field(default_factory=list)
    


class VisualizationsBranch(BaseModel):
    visualizations: List[VisualizationSpec] = Field(default_factory=list)
    

    @field_validator("visualizations")
    @classmethod
    def ensure_unique_ids(cls, visualizations: List[VisualizationSpec]) -> List[VisualizationSpec]:
        ids = [viz.id for viz in visualizations]
        if len(ids) != len(set(ids)):
            raise ValueError("Visualization ids must be unique.")
        return visualizations


class CoordinatorDraft(BaseModel):
    summary: str
    insights: List[str] = Field(default_factory=list)
    metrics: List[Metric] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    tables: List[TableData] = Field(default_factory=list)
    visualizations: List[VisualizationSpec] = Field(default_factory=list)
    


class CriticReview(BaseModel):
    approved: bool
    issues: List[str] = Field(default_factory=list)
    drop_visualization_ids: List[str] = Field(default_factory=list)
    revised_summary: Optional[str] = None
    
