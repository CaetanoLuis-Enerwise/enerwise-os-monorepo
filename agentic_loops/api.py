from functools import lru_cache
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from agentic_loops.runtime import AgenticRuntime


router = APIRouter(prefix="/agentic", tags=["Agentic"])


@lru_cache(maxsize=1)
def get_runtime() -> AgenticRuntime:
    return AgenticRuntime()


class AgentRunRequest(BaseModel):
    task: str = Field(min_length=3, max_length=20000)
    thread_id: Optional[str] = Field(default=None, max_length=120)
    approval_mode: Literal["risk", "always", "never"] = "risk"
    max_react_steps: int = Field(default=6, ge=1, le=20)
    max_optimization_iterations: int = Field(default=3, ge=0, le=10)
    quality_threshold: float = Field(default=0.85, ge=0, le=1)
    minimum_improvement: float = Field(default=0.02, ge=0, le=1)


class AgentResumeRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=120)
    decision: Literal["approve", "reject", "edit"]
    candidate: Optional[str] = Field(default=None, max_length=50000)

    @model_validator(mode="after")
    def validate_edit(self):
        if self.decision == "edit" and not self.candidate:
            raise ValueError("candidate is required when decision is edit.")
        return self


@router.post("/run")
def run_agentic_loop(payload: AgentRunRequest):
    try:
        return get_runtime().run(**payload.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agentic loop failed: {exc}",
        ) from exc


@router.post("/resume")
def resume_agentic_loop(payload: AgentResumeRequest):
    try:
        return get_runtime().resume(**payload.model_dump())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agentic loop resume failed: {exc}",
        ) from exc


@router.get("/threads/{thread_id}")
def get_agentic_thread(thread_id: str):
    try:
        return get_runtime().status(thread_id)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Agentic thread unavailable: {exc}",
        ) from exc


@router.get("/memory")
def get_agentic_memory(limit: int = 20):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200.")
    return {
        "status": "success",
        "episodes": get_runtime().memory.recent(limit),
    }
