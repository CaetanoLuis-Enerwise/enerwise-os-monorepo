import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4


class AgentEventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def write(
        self,
        event_type: str,
        *,
        run_id: str,
        thread_id: str,
        payload: dict | None = None,
    ) -> None:
        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "thread_id": thread_id,
            "payload": payload or {},
        }
        line = json.dumps(event, sort_keys=True, ensure_ascii=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as destination:
                destination.write(line + "\n")
