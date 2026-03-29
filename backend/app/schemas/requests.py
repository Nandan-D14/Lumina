from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import SourceInput, TextSourceInput


class AnalyzeOptions(BaseModel):
    allow_web_research: bool = False
    allow_scraping: bool = True
    max_visualizations: int = Field(default=3, ge=1, le=10)
    persistence_mode: Literal["session", "persistent"] = "session"
    gemini_api_key: str | None = None
    user_id: str | None = None

    @field_validator("gemini_api_key", "user_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
    


class AnalyzeRequest(BaseModel):
    prompt: str
    sources: list[SourceInput]
    options: AnalyzeOptions = Field(default_factory=AnalyzeOptions)
    

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, prompt: str) -> str:
        normalized = prompt.strip()
        if not normalized:
            raise ValueError("Prompt is required.")
        return normalized

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, sources: list[SourceInput]) -> list[SourceInput]:
        if not sources:
            raise ValueError("At least one source is required.")
        return sources


class ExportRequest(BaseModel):
    analysis_id: str
    format: Literal["json", "csv"]
    

    @field_validator("analysis_id")
    @classmethod
    def validate_analysis_id(cls, analysis_id: str) -> str:
        normalized = analysis_id.strip()
        if not normalized:
            raise ValueError("Analysis id is required.")
        return normalized


class LegacyRunRequest(BaseModel):
    text: str
    

    @field_validator("text")
    @classmethod
    def validate_text(cls, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Text is required.")
        return normalized

    def to_analyze_request(self) -> AnalyzeRequest:
        return AnalyzeRequest(
            prompt="Extract the key data from the supplied text and return the best visualization-ready insight package.",
            sources=[TextSourceInput(type="text", text=self.text, title="Legacy text input")],
        )
