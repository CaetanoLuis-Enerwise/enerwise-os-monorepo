import os
import sqlite3
from pathlib import Path
from threading import Lock
from uuid import uuid4

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agentic_loops.config import AgenticSettings
from agentic_loops.logging import AgentEventLogger
from agentic_loops.memory import AgentMemoryStore
from agentic_loops.models import AgentModel, OpenAIAgentModel
from agentic_loops.workflow import build_agentic_graph


class AgenticRuntime:
    def __init__(
        self,
        *,
        settings: AgenticSettings | None = None,
        model: AgentModel | None = None,
    ) -> None:
        self.settings = settings or AgenticSettings.from_env()
        self.settings.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.settings.checkpoint_db,
            check_same_thread=False,
        )
        self._checkpointer = SqliteSaver(self._connection)
        self.memory = AgentMemoryStore(self.settings.memory_db)
        self.logger = AgentEventLogger(self.settings.event_log)
        self.model = model or OpenAIAgentModel(
            model=self.settings.model,
            temperature=self.settings.temperature,
        )
        self.graph = build_agentic_graph(
            model=self.model,
            memory=self.memory,
            logger=self.logger,
            checkpointer=self._checkpointer,
        )
        self._lock = Lock()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 100,
        }

    @staticmethod
    def _serialize_interrupts(result: dict) -> list[dict]:
        serialized = []
        for item in result.get("__interrupt__", ()):
            serialized.append(
                {
                    "id": getattr(item, "id", None),
                    "value": getattr(item, "value", item),
                }
            )
        return serialized

    def _response(self, thread_id: str, result: dict) -> dict:
        interrupts = self._serialize_interrupts(result)
        return {
            "thread_id": thread_id,
            "status": "awaiting_human" if interrupts else result.get(
                "status", "completed"
            ),
            "interrupts": interrupts,
            "run_id": result.get("run_id"),
            "final_answer": result.get("final_answer", ""),
            "candidate": result.get("candidate", ""),
            "evaluation": result.get("evaluation", {}),
            "stop_reason": result.get("stop_reason", ""),
            "react_steps": result.get("react_steps", 0),
            "optimization_iterations": result.get(
                "optimization_iterations", 0
            ),
        }

    def run(
        self,
        *,
        task: str,
        thread_id: str | None = None,
        approval_mode: str = "risk",
        max_react_steps: int = 6,
        max_optimization_iterations: int = 3,
        quality_threshold: float = 0.85,
        minimum_improvement: float = 0.02,
    ) -> dict:
        thread_id = thread_id or str(uuid4())
        state = {
            "task": task,
            "thread_id": thread_id,
            "run_id": str(uuid4()),
            "approval_mode": approval_mode,
            "max_react_steps": max_react_steps,
            "max_optimization_iterations": max_optimization_iterations,
            "quality_threshold": quality_threshold,
            "minimum_improvement": minimum_improvement,
        }
        with self._lock:
            result = self.graph.invoke(state, config=self._config(thread_id))
        return self._response(thread_id, result)

    def resume(
        self,
        *,
        thread_id: str,
        decision: str,
        candidate: str | None = None,
    ) -> dict:
        payload = {"decision": decision}
        if candidate is not None:
            payload["candidate"] = candidate
        with self._lock:
            result = self.graph.invoke(
                Command(resume=payload),
                config=self._config(thread_id),
            )
        return self._response(thread_id, result)

    def status(self, thread_id: str) -> dict:
        with self._lock:
            snapshot = self.graph.get_state(self._config(thread_id))
        values = dict(snapshot.values or {})
        interrupts = []
        for task in snapshot.tasks:
            for item in getattr(task, "interrupts", ()):
                interrupts.append(
                    {
                        "id": getattr(item, "id", None),
                        "value": getattr(item, "value", item),
                    }
                )
        return {
            "thread_id": thread_id,
            "status": (
                "awaiting_human"
                if interrupts
                else values.get("status", "unknown")
            ),
            "next": list(snapshot.next),
            "interrupts": interrupts,
            "state": values,
        }

    def close(self) -> None:
        self._connection.close()
