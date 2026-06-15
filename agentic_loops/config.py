import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "agentic"


@dataclass(frozen=True)
class AgenticSettings:
    model: str
    temperature: float
    checkpoint_db: Path
    memory_db: Path
    event_log: Path

    @classmethod
    def from_env(cls) -> "AgenticSettings":
        runtime_root = Path(
            os.getenv("ENERWISE_AGENT_RUNTIME_DIR", str(RUNTIME_ROOT))
        )
        return cls(
            model=os.getenv("ENERWISE_AGENT_MODEL", "gpt-5-mini"),
            temperature=float(os.getenv("ENERWISE_AGENT_TEMPERATURE", "0")),
            checkpoint_db=Path(
                os.getenv(
                    "ENERWISE_AGENT_CHECKPOINT_DB",
                    str(runtime_root / "checkpoints.sqlite3"),
                )
            ),
            memory_db=Path(
                os.getenv(
                    "ENERWISE_AGENT_MEMORY_DB",
                    str(runtime_root / "memory.sqlite3"),
                )
            ),
            event_log=Path(
                os.getenv(
                    "ENERWISE_AGENT_EVENT_LOG",
                    str(runtime_root / "events.jsonl"),
                )
            ),
        )
