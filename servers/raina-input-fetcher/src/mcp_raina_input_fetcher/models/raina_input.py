from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

# Pydantic models mirror the JSON Schema; we still validate against JSON Schema
# to enforce additionalProperties: false strictly.

class Goal(BaseModel):
    id: str
    text: str
    metric: Optional[str] = None

class NonFunctional(BaseModel):
    type: str
    target: str

class Context(BaseModel):
    domain: str
    actors: List[str] = Field(default_factory=list)

class SuccessCriterion(BaseModel):
    kpi: str
    target: str

class AVC(BaseModel):
    vision: List[str] = Field(default_factory=list)
    problem_statements: List[str] = Field(default_factory=list)
    goals: List[Goal] = Field(default_factory=list)
    non_functionals: List[NonFunctional] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    context: Context
    success_criteria: List[SuccessCriterion] = Field(default_factory=list)

class Story(BaseModel):
    key: str
    title: str
    description: Optional[str | List[str]] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

class FSS(BaseModel):
    stories: List[Story] = Field(default_factory=list)

class PSS(BaseModel):
    paradigm: str
    style: List[str] = Field(default_factory=list)
    tech_stack: List[str] = Field(default_factory=list)

class Inputs(BaseModel):
    avc: AVC
    fss: FSS
    pss: PSS

class RainaInputDoc(BaseModel):
    inputs: Inputs

    @field_validator("inputs", mode="before")
    @classmethod
    def _ensure_inputs(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError("`inputs` must be an object")
        return v