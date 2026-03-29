from __future__ import annotations

from typing import Literal, List, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from .domain import ArtifactRef, Citation, Entity, Metric, TableData, VisualizationSpec


class InsightPackage(BaseModel):
    analysis_id: str
    session_id: str | None = None
    persistence_mode: Literal["session", "persistent"] = "session"
    summary: str
    advanced_html_report: str | None = None
    insights: List[str] = Field(default_factory=list)
    metrics: List[Metric] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    tables: List[TableData] = Field(default_factory=list)
    visualizations: List[VisualizationSpec] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    


class LegacyChartData(BaseModel):
    labels: List[str]
    values: List[Union[StrictInt, StrictFloat]]
    

    @model_validator(mode="after")
    def validate_lengths(self) -> "LegacyChartData":
        if len(self.labels) != len(self.values):
            raise ValueError("Labels and values must be equal in length.")
        return self


class LegacyRunResponse(BaseModel):
    summary: str
    chart_type: Literal["bar", "pie", "line"]
    chart_data: LegacyChartData
    
