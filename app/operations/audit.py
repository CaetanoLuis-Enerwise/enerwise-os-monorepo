import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4


def _canonical_json(payload: dict) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


class AuditStore:
    """Append-only local journal with a verifiable hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS control_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        site_id TEXT NOT NULL,
                        execution_mode TEXT NOT NULL,
                        event_payload TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL
                    )
                    """
                )

    def append(
        self,
        *,
        site_id: str,
        execution_mode: str,
        adapter: dict,
        telemetry: dict,
        command: dict,
        safety: dict,
        receipt: dict,
        confirmation: dict | None,
        plan_summary: dict,
    ) -> dict:
        event_id = str(uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        event = {
            "event_id": event_id,
            "created_at": created_at,
            "site_id": site_id,
            "execution_mode": execution_mode,
            "adapter": adapter,
            "telemetry": telemetry,
            "command": command,
            "safety": safety,
            "receipt": receipt,
            "confirmation": confirmation,
            "plan_summary": plan_summary,
        }
        payload = _canonical_json(event)

        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute(
                    """
                    SELECT event_hash
                    FROM control_events
                    ORDER BY sequence DESC
                    LIMIT 1
                    """
                ).fetchone()
                previous_hash = previous["event_hash"] if previous else ""
                event_hash = hashlib.sha256(
                    (previous_hash + payload).encode("utf-8")
                ).hexdigest()
                cursor = connection.execute(
                    """
                    INSERT INTO control_events (
                        event_id,
                        created_at,
                        site_id,
                        execution_mode,
                        event_payload,
                        previous_hash,
                        event_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        created_at,
                        site_id,
                        execution_mode,
                        payload,
                        previous_hash,
                        event_hash,
                    ),
                )
                sequence = cursor.lastrowid

        return {
            **event,
            "sequence": sequence,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
        }

    def recent(self, limit: int = 50) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_payload, previous_hash, event_hash
                FROM control_events
                ORDER BY sequence DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events = []
        for row in rows:
            events.append(
                {
                    **json.loads(row["event_payload"]),
                    "sequence": row["sequence"],
                    "previous_hash": row["previous_hash"],
                    "event_hash": row["event_hash"],
                }
            )
        return events

    def verify_chain(self) -> dict:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_payload, previous_hash, event_hash
                FROM control_events
                ORDER BY sequence ASC
                """
            ).fetchall()

        expected_previous = ""
        for row in rows:
            expected_hash = hashlib.sha256(
                (expected_previous + row["event_payload"]).encode("utf-8")
            ).hexdigest()
            if (
                row["previous_hash"] != expected_previous
                or row["event_hash"] != expected_hash
            ):
                return {
                    "valid": False,
                    "events": len(rows),
                    "first_invalid_sequence": row["sequence"],
                }
            expected_previous = row["event_hash"]
        return {
            "valid": True,
            "events": len(rows),
            "head_hash": expected_previous or None,
        }
