from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field


ToolName = Literal[
    "inspect_project",
    "inspect_benchmark",
    "inspect_operations",
    "recall_memory",
    "draft",
    "request_human",
]


class ReActDecision(BaseModel):
    rationale: str = Field(
        description="Brief decision rationale, without hidden chain-of-thought."
    )
    action: ToolName
    query: str = ""
    draft: str = ""


class DraftOutput(BaseModel):
    answer: str


class ReflectionOutput(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    revised_answer: str


class EvaluationOutput(BaseModel):
    score: float = Field(ge=0, le=1)
    approved: bool
    feedback: list[str] = Field(default_factory=list)
    safety_concerns: list[str] = Field(default_factory=list)
    requires_human: bool = False


class OptimizationOutput(BaseModel):
    answer: str
    changes: list[str] = Field(default_factory=list)


class AgentState(TypedDict, total=False):
    task: str
    thread_id: str
    run_id: str
    approval_mode: Literal["risk", "always", "never"]
    risk_level: Literal["low", "medium", "high"]
    max_react_steps: int
    max_optimization_iterations: int
    quality_threshold: float
    minimum_improvement: float
    react_steps: int
    optimization_iterations: int
    observations: list[dict]
    memories: list[dict]
    decision: dict
    candidate: str
    reflection: dict
    evaluation: dict
    score_history: list[float]
    needs_human: bool
    human_decision: Optional[str]
    stop_reason: str
    final_answer: str
    status: str
    error: Optional[str]
