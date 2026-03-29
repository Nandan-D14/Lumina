from pydantic import BaseModel, Field
from google.adk.tools import _automatic_function_calling_util
from typing import Dict, Any, List, Optional

class Citation(BaseModel):
    title: str
    url: str | None = None
    artifact_name: str | None = None

class InsightPackage(BaseModel):
    citations: list[Citation] = Field(default_factory=list)

def f(citations: list[Citation]): pass

print(_automatic_function_calling_util.build_function_declaration(f, ignore_params=[], variant='v1'))
