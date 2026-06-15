import tempfile
import unittest
from pathlib import Path

from agentic_loops.config import AgenticSettings
from agentic_loops.runtime import AgenticRuntime
from agentic_loops.schemas import (
    DraftOutput,
    EvaluationOutput,
    OptimizationOutput,
    ReActDecision,
    ReflectionOutput,
)


class DeterministicAgentModel:
    def __init__(self, *, evaluations, requires_human=False):
        self.evaluations = list(evaluations)
        self.requires_human = requires_human
        self.decisions = 0
        self.reflections = 0
        self.optimizations = 0

    def decide(self, context):
        self.decisions += 1
        if self.decisions == 1:
            return ReActDecision(
                rationale="Inspect verified project context.",
                action="inspect_project",
                query=context["task"],
            )
        return ReActDecision(
            rationale="Evidence is sufficient.",
            action="draft",
            draft="Initial grounded candidate.",
        )

    def synthesize(self, context):
        return DraftOutput(answer="Synthesized candidate.")

    def reflect(self, context):
        self.reflections += 1
        return ReflectionOutput(
            strengths=["Grounded"],
            weaknesses=[],
            missing_evidence=[],
            revised_answer=(
                f"{context['candidate']} Reflected {self.reflections}."
            ),
        )

    def evaluate(self, context):
        score = self.evaluations.pop(0)
        return EvaluationOutput(
            score=score,
            approved=score >= context["quality_threshold"],
            feedback=[] if score >= 0.85 else ["Improve specificity."],
            safety_concerns=[],
            requires_human=self.requires_human,
        )

    def optimize(self, context):
        self.optimizations += 1
        return OptimizationOutput(
            answer=f"{context['candidate']} Optimized.",
            changes=["Improved specificity"],
        )


class AgenticLoopTests(unittest.TestCase):
    def make_runtime(self, directory, model):
        root = Path(directory)
        settings = AgenticSettings(
            model="test-model",
            temperature=0,
            checkpoint_db=root / "checkpoints.sqlite3",
            memory_db=root / "memory.sqlite3",
            event_log=root / "events.jsonl",
        )
        return AgenticRuntime(settings=settings, model=model)

    def test_evaluator_optimizer_loops_until_quality_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            model = DeterministicAgentModel(evaluations=[0.55, 0.92])
            runtime = self.make_runtime(directory, model)
            try:
                result = runtime.run(
                    task="Summarize the Enerwise architecture.",
                    thread_id="quality-loop",
                    approval_mode="never",
                )

                self.assertEqual(result["status"], "completed")
                self.assertEqual(
                    result["stop_reason"],
                    "quality_threshold_met",
                )
                self.assertEqual(result["optimization_iterations"], 1)
                self.assertEqual(model.optimizations, 1)
                self.assertEqual(len(runtime.memory.recent()), 1)
            finally:
                runtime.close()

    def test_human_interrupt_can_resume_from_sqlite_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            model = DeterministicAgentModel(
                evaluations=[0.95],
                requires_human=True,
            )
            runtime = self.make_runtime(directory, model)
            paused = runtime.run(
                task="Prepare a production integration decision.",
                thread_id="human-loop",
                approval_mode="always",
            )
            self.assertEqual(paused["status"], "awaiting_human")
            self.assertEqual(len(paused["interrupts"]), 1)
            runtime.close()

            resumed_runtime = self.make_runtime(directory, model)
            try:
                resumed = resumed_runtime.resume(
                    thread_id="human-loop",
                    decision="approve",
                )
                self.assertEqual(resumed["status"], "completed")
                self.assertEqual(resumed["stop_reason"], "quality_threshold_met")
            finally:
                resumed_runtime.close()

    def test_iteration_budget_stops_failed_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            model = DeterministicAgentModel(evaluations=[0.40])
            runtime = self.make_runtime(directory, model)
            try:
                result = runtime.run(
                    task="Describe current system state.",
                    thread_id="budget-loop",
                    approval_mode="never",
                    max_optimization_iterations=0,
                )
                self.assertEqual(result["status"], "completed")
                self.assertEqual(
                    result["stop_reason"],
                    "max_optimization_iterations",
                )
                self.assertEqual(result["optimization_iterations"], 0)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
