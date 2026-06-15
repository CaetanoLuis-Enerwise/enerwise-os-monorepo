import json
import os
from typing import Protocol, TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agentic_loops.agents import (
    EVALUATOR_AGENT,
    OPTIMIZER_AGENT,
    REACT_AGENT,
    REFLECTION_AGENT,
    SYNTHESIS_AGENT,
)
from agentic_loops.schemas import (
    DraftOutput,
    EvaluationOutput,
    OptimizationOutput,
    ReActDecision,
    ReflectionOutput,
)


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AgentModel(Protocol):
    def decide(self, context: dict) -> ReActDecision:
        ...

    def synthesize(self, context: dict) -> DraftOutput:
        ...

    def reflect(self, context: dict) -> ReflectionOutput:
        ...

    def evaluate(self, context: dict) -> EvaluationOutput:
        ...

    def optimize(self, context: dict) -> OptimizationOutput:
        ...


class OpenAIAgentModel:
    def __init__(self, model: str, temperature: float = 0) -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for the agentic loop.")
        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            max_retries=2,
            timeout=120,
        )

    def _invoke(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        context: dict,
    ) -> SchemaT:
        structured = self.llm.with_structured_output(
            schema,
            method="json_schema",
        )
        return structured.invoke(
            [
                ("system", system_prompt),
                (
                    "human",
                    json.dumps(context, ensure_ascii=False, default=str),
                ),
            ]
        )

    def decide(self, context: dict) -> ReActDecision:
        return self._invoke(
            ReActDecision,
            REACT_AGENT.system_prompt,
            context,
        )

    def synthesize(self, context: dict) -> DraftOutput:
        return self._invoke(
            DraftOutput,
            SYNTHESIS_AGENT.system_prompt,
            context,
        )

    def reflect(self, context: dict) -> ReflectionOutput:
        return self._invoke(
            ReflectionOutput,
            REFLECTION_AGENT.system_prompt,
            context,
        )

    def evaluate(self, context: dict) -> EvaluationOutput:
        return self._invoke(
            EvaluationOutput,
            EVALUATOR_AGENT.system_prompt,
            context,
        )

    def optimize(self, context: dict) -> OptimizationOutput:
        return self._invoke(
            OptimizationOutput,
            OPTIMIZER_AGENT.system_prompt,
            context,
        )
