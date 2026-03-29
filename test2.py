from pydantic import BaseModel, Field
from google.adk.tools import _automatic_function_calling_util
from typing import Dict, Any, List, Optional

class Citation(BaseModel):
    title: str
    url: Optional[str] = None
    artifact_name: Optional[str] = None

class InsightPackage(BaseModel):
    citations: List[Citation] = Field(default_factory=list)

def f(x: InsightPackage): pass

print(_automatic_function_calling_util.build_function_declaration(f, ignore_params=[], variant='v1'))
