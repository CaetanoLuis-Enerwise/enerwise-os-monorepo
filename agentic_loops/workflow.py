from typing import Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agentic_loops.logging import AgentEventLogger
from agentic_loops.memory import AgentMemoryStore
from agentic_loops.models import AgentModel
from agentic_loops.schemas import AgentState
from agentic_loops.tools import EnerwiseTools


HIGH_RISK_TERMS = {
    "actuate",
    "closed-loop",
    "command battery",
    "control battery",
    "delete",
    "deploy production",
    "dispatch",
    "emergency stop",
    "financial commitment",
    "inverter command",
    "physical control",
    "production rollout",
    "write register",
}
MEDIUM_RISK_TERMS = {
    "architecture",
    "commercial",
    "customer",
    "integration",
    "pilot",
    "pricing",
    "production",
    "security",
}


def classify_risk(task: str) -> Literal["low", "medium", "high"]:
    normalized = task.lower()
    if any(term in normalized for term in HIGH_RISK_TERMS):
        return "high"
    if any(term in normalized for term in MEDIUM_RISK_TERMS):
        return "medium"
    return "low"


def build_agentic_graph(
    *,
    model: AgentModel,
    memory: AgentMemoryStore,
    logger: AgentEventLogger,
    checkpointer,
):
    tools = EnerwiseTools(memory)

    def log(state: AgentState, event_type: str, payload: dict | None = None):
        logger.write(
            event_type,
            run_id=state["run_id"],
            thread_id=state["thread_id"],
            payload=payload,
        )

    def initialize(state: AgentState) -> dict:
        run_id = state.get("run_id") or str(uuid4())
        risk_level = classify_risk(state["task"])
        memories = memory.search(state["task"], limit=5)
        update = {
            "run_id": run_id,
            "risk_level": risk_level,
            "react_steps": 0,
            "optimization_iterations": 0,
            "observations": [],
            "memories": memories,
            "score_history": [],
            "needs_human": False,
            "human_decision": None,
            "stop_reason": "",
            "final_answer": "",
            "status": "running",
            "error": None,
        }
        logger.write(
            "run_started",
            run_id=run_id,
            thread_id=state["thread_id"],
            payload={"task": state["task"], "risk_level": risk_level},
        )
        return update

    def react(state: AgentState) -> dict:
        context = {
            "task": state["task"],
            "risk_level": state["risk_level"],
            "react_step": state["react_steps"] + 1,
            "max_react_steps": state["max_react_steps"],
            "memories": state["memories"],
            "observations": state["observations"],
        }
        decision = model.decide(context)
        log(
            state,
            "react_decision",
            {"step": state["react_steps"] + 1, **decision.model_dump()},
        )
        update = {
            "decision": decision.model_dump(),
            "react_steps": state["react_steps"] + 1,
        }
        if decision.action == "draft" and decision.draft:
            update["candidate"] = decision.draft
        if decision.action == "request_human":
            update["needs_human"] = True
        return update

    def route_react(state: AgentState) -> str:
        action = state["decision"]["action"]
        if action == "draft":
            return "reflect"
        if action == "request_human":
            return "synthesize"
        if state["react_steps"] >= state["max_react_steps"]:
            return "synthesize"
        return "act"

    def act(state: AgentState) -> dict:
        decision = state["decision"]
        observation = tools.execute(decision["action"], decision.get("query", ""))
        log(state, "tool_result", observation)
        return {"observations": [*state["observations"], observation]}

    def synthesize(state: AgentState) -> dict:
        result = model.synthesize(
            {
                "task": state["task"],
                "risk_level": state["risk_level"],
                "memories": state["memories"],
                "observations": state["observations"],
                "instruction": (
                    "The ReAct tool budget is exhausted. Produce the strongest "
                    "grounded answer now."
                ),
            }
        )
        log(state, "draft_synthesized", {"answer": result.answer})
        return {"candidate": result.answer}

    def reflect(state: AgentState) -> dict:
        reflection = model.reflect(
            {
                "task": state["task"],
                "candidate": state["candidate"],
                "risk_level": state["risk_level"],
                "observations": state["observations"],
            }
        )
        log(state, "reflection_completed", reflection.model_dump())
        return {
            "reflection": reflection.model_dump(),
            "candidate": reflection.revised_answer,
        }

    def evaluate(state: AgentState) -> dict:
        evaluation = model.evaluate(
            {
                "task": state["task"],
                "candidate": state["candidate"],
                "reflection": state.get("reflection", {}),
                "observations": state["observations"],
                "risk_level": state["risk_level"],
                "quality_threshold": state["quality_threshold"],
            }
        )
        scores = [*state["score_history"], evaluation.score]
        exhausted = (
            state["optimization_iterations"]
            >= state["max_optimization_iterations"]
        )
        plateau = (
            len(scores) >= 2
            and scores[-1] - scores[-2] < state["minimum_improvement"]
        )
        quality_passed = (
            evaluation.approved
            and evaluation.score >= state["quality_threshold"]
        )
        needs_human = (
            state.get("needs_human", False)
            or state["approval_mode"] == "always"
            or evaluation.requires_human
            or (
                state["approval_mode"] == "risk"
                and state["risk_level"] == "high"
            )
        )
        stop_reason = ""
        if quality_passed:
            stop_reason = "quality_threshold_met"
        elif exhausted:
            stop_reason = "max_optimization_iterations"
        elif plateau and state["optimization_iterations"] > 0:
            stop_reason = "quality_plateau"

        log(
            state,
            "evaluation_completed",
            {
                **evaluation.model_dump(),
                "quality_passed": quality_passed,
                "exhausted": exhausted,
                "plateau": plateau,
            },
        )
        return {
            "evaluation": evaluation.model_dump(),
            "score_history": scores,
            "needs_human": needs_human,
            "stop_reason": stop_reason,
        }

    def route_evaluation(state: AgentState) -> str:
        if state["stop_reason"]:
            return "human_review" if state["needs_human"] else "finalize"
        return "optimize"

    def optimize(state: AgentState) -> dict:
        result = model.optimize(
            {
                "task": state["task"],
                "candidate": state["candidate"],
                "evaluation": state["evaluation"],
                "reflection": state.get("reflection", {}),
                "observations": state["observations"],
            }
        )
        log(state, "candidate_optimized", result.model_dump())
        return {
            "candidate": result.answer,
            "optimization_iterations": state["optimization_iterations"] + 1,
        }

    def human_review(state: AgentState) -> dict:
        response = interrupt(
            {
                "type": "agentic_review",
                "thread_id": state["thread_id"],
                "run_id": state["run_id"],
                "task": state["task"],
                "risk_level": state["risk_level"],
                "candidate": state.get("candidate", ""),
                "evaluation": state.get("evaluation", {}),
                "stop_reason": state.get("stop_reason", ""),
                "allowed_decisions": ["approve", "reject", "edit"],
            }
        )
        if response is True:
            response = {"decision": "approve"}
        elif response is False:
            response = {"decision": "reject"}
        elif isinstance(response, str):
            response = {"decision": response}
        decision = response.get("decision", "reject")
        update = {"human_decision": decision}
        if decision == "edit":
            edited = str(response.get("candidate", "")).strip()
            if not edited:
                decision = "reject"
                update["human_decision"] = decision
            else:
                update["candidate"] = edited
                update["stop_reason"] = "human_edited"
        elif decision == "approve":
            update["stop_reason"] = state.get("stop_reason") or "human_approved"
        else:
            update["stop_reason"] = "human_rejected"
            update["candidate"] = "Task stopped because human approval was rejected."
        log(state, "human_decision", {"decision": decision})
        return update

    def finalize(state: AgentState) -> dict:
        score = float(state.get("evaluation", {}).get("score", 0))
        answer = state.get("candidate", "")
        status = (
            "rejected"
            if state.get("human_decision") == "reject"
            else "completed"
        )
        memory.save_episode(
            run_id=state["run_id"],
            thread_id=state["thread_id"],
            task=state["task"],
            answer=answer,
            score=score,
            metadata={
                "risk_level": state["risk_level"],
                "stop_reason": state["stop_reason"],
                "react_steps": state["react_steps"],
                "optimization_iterations": state["optimization_iterations"],
                "human_decision": state.get("human_decision"),
            },
        )
        log(
            state,
            "run_finished",
            {
                "status": status,
                "score": score,
                "stop_reason": state["stop_reason"],
            },
        )
        return {
            "final_answer": answer,
            "status": status,
        }

    builder = StateGraph(AgentState)
    builder.add_node("initialize", initialize)
    builder.add_node("react", react)
    builder.add_node("act", act)
    builder.add_node("synthesize", synthesize)
    builder.add_node("reflect", reflect)
    builder.add_node("evaluate", evaluate)
    builder.add_node("optimize", optimize)
    builder.add_node("human_review", human_review)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "react")
    builder.add_conditional_edges(
        "react",
        route_react,
        {
            "act": "act",
            "synthesize": "synthesize",
            "reflect": "reflect",
            "human_review": "human_review",
        },
    )
    builder.add_edge("act", "react")
    builder.add_edge("synthesize", "reflect")
    builder.add_edge("reflect", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_evaluation,
        {
            "optimize": "optimize",
            "human_review": "human_review",
            "finalize": "finalize",
        },
    )
    builder.add_edge("optimize", "reflect")
    builder.add_edge("human_review", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
