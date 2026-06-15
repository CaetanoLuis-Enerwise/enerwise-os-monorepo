import json
from pathlib import Path

from agentic_loops.config import PROJECT_ROOT
from agentic_loops.memory import AgentMemoryStore
from app.operations.audit import AuditStore


MAX_TEXT_CHARS = 12000


def _read_text(path: Path) -> str:
    if not path.exists():
        return f"Missing file: {path.relative_to(PROJECT_ROOT)}"
    return path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]


class EnerwiseTools:
    def __init__(self, memory: AgentMemoryStore) -> None:
        self.memory = memory

    def execute(self, name: str, query: str) -> dict:
        handlers = {
            "inspect_project": self.inspect_project,
            "inspect_benchmark": self.inspect_benchmark,
            "inspect_operations": self.inspect_operations,
            "recall_memory": self.recall_memory,
        }
        if name not in handlers:
            return {
                "tool": name,
                "ok": False,
                "error": "Tool is not allowlisted.",
            }
        return handlers[name](query)

    def inspect_project(self, query: str) -> dict:
        files = {
            "readme": _read_text(PROJECT_ROOT / "README.md"),
            "architecture": _read_text(PROJECT_ROOT / "docs" / "ARCHITECTURE.md"),
            "ot_integration": _read_text(
                PROJECT_ROOT / "docs" / "OT_INTEGRATION.md"
            ),
        }
        return {
            "tool": "inspect_project",
            "ok": True,
            "query": query,
            "files": files,
        }

    def inspect_benchmark(self, query: str) -> dict:
        path = (
            PROJECT_ROOT
            / "enterprise"
            / "evidence"
            / "benchmark_summary.json"
        )
        if not path.exists():
            return {
                "tool": "inspect_benchmark",
                "ok": False,
                "error": "Benchmark summary is missing.",
            }
        return {
            "tool": "inspect_benchmark",
            "ok": True,
            "query": query,
            "evidence": json.loads(path.read_text(encoding="utf-8")),
        }

    def inspect_operations(self, query: str) -> dict:
        audit_path = PROJECT_ROOT / "runtime" / "enerwise_audit.sqlite3"
        audit = (
            AuditStore(audit_path).verify_chain()
            if audit_path.exists()
            else {"valid": True, "events": 0, "head_hash": None}
        )
        return {
            "tool": "inspect_operations",
            "ok": True,
            "query": query,
            "physical_dispatch_available": False,
            "registered_adapter": {
                "adapter_id": "enerwise-simulator-v1",
                "physical": False,
            },
            "audit": audit,
            "security_posture": _read_text(
                PROJECT_ROOT / "enterprise" / "SECURITY_AND_SAFETY.md"
            ),
        }

    def recall_memory(self, query: str) -> dict:
        return {
            "tool": "recall_memory",
            "ok": True,
            "query": query,
            "episodes": self.memory.search(query, limit=5),
        }
