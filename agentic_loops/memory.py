import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_]{3,}", value.lower())
        if token not in {"the", "and", "for", "with", "this", "that"}
    }


class AgentMemoryStore:
    """Small durable episodic memory with deterministic lexical retrieval."""

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
                    CREATE TABLE IF NOT EXISTS agent_memories (
                        run_id TEXT PRIMARY KEY,
                        thread_id TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        task TEXT NOT NULL,
                        answer TEXT NOT NULL,
                        score REAL NOT NULL,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_agent_memories_thread
                    ON agent_memories(thread_id, created_at DESC)
                    """
                )

    def save_episode(
        self,
        *,
        run_id: str,
        thread_id: str,
        task: str,
        answer: str,
        score: float,
        metadata: dict,
    ) -> None:
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO agent_memories (
                        run_id,
                        thread_id,
                        created_at,
                        task,
                        answer,
                        score,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        answer = excluded.answer,
                        score = excluded.score,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        run_id,
                        thread_id,
                        datetime.now(timezone.utc).isoformat(),
                        task,
                        answer,
                        score,
                        json.dumps(metadata, sort_keys=True),
                    ),
                )

    def search(self, query: str, limit: int = 5) -> list[dict]:
        query_tokens = _tokens(query)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT run_id, thread_id, created_at, task, answer, score,
                       metadata_json
                FROM agent_memories
                ORDER BY created_at DESC
                LIMIT 200
                """
            ).fetchall()

        ranked = []
        for row in rows:
            haystack = _tokens(f"{row['task']} {row['answer']}")
            overlap = len(query_tokens & haystack)
            if overlap == 0 and query_tokens:
                continue
            ranked.append(
                (
                    overlap,
                    row["created_at"],
                    {
                        "run_id": row["run_id"],
                        "thread_id": row["thread_id"],
                        "created_at": row["created_at"],
                        "task": row["task"],
                        "answer": row["answer"],
                        "score": row["score"],
                        "metadata": json.loads(row["metadata_json"]),
                    },
                )
            )
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]]

    def recent(self, limit: int = 20) -> list[dict]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT run_id, thread_id, created_at, task, answer, score,
                       metadata_json
                FROM agent_memories
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "thread_id": row["thread_id"],
                "created_at": row["created_at"],
                "task": row["task"],
                "answer": row["answer"],
                "score": row["score"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]
