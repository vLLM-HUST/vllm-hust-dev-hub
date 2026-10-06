from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .common import PRIORITIES, canonical_json, sha256_bytes


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    started_at INTEGER,
                    finished_at INTEGER,
                    assigned_npus TEXT,
                    worker_id TEXT,
                    exit_code INTEGER,
                    artifact_path TEXT,
                    artifact_sha256 TEXT,
                    error TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS jobs_queue
                ON jobs(status, priority, created_at);
                """
            )

    def submit(
        self, idempotency_key: str, request: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        request_bytes = canonical_json(request)
        request_sha = sha256_bytes(request_bytes)
        now = int(time.time())
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                if existing["request_sha256"] != request_sha:
                    raise ValueError(
                        "idempotency key was already used for another request"
                    )
                return dict(existing), False
            job_id = f"eval-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(now))}-{uuid.uuid4().hex[:12]}"
            connection.execute(
                """INSERT INTO jobs(
                    id, idempotency_key, request_sha256, request_json, priority,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (
                    job_id,
                    idempotency_key,
                    request_sha,
                    request_bytes.decode(),
                    PRIORITIES[request["priority"]],
                    now,
                    now,
                ),
            )
        return self.get(job_id), True

    def get(self, job_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        if result["assigned_npus"] is not None:
            result["assigned_npus"] = json.loads(result["assigned_npus"])
        return result

    def cancel(self, job_id: str) -> dict[str, Any]:
        now = int(time.time())
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] == "queued":
                connection.execute(
                    "UPDATE jobs SET status='cancelled', cancel_requested=1, updated_at=?, finished_at=? WHERE id=?",
                    (now, now, job_id),
                )
            elif row["status"] == "running":
                connection.execute(
                    "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=?",
                    (now, job_id),
                )
        return self.get(job_id)

    def next_queued(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM jobs WHERE status='queued' AND cancel_requested=0 ORDER BY priority, created_at LIMIT 1"
            ).fetchone()
        return None if row is None else self.get(row["id"])

    def claim(
        self, job_id: str, worker_id: str, npus: list[int]
    ) -> dict[str, Any] | None:
        now = int(time.time())
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM jobs WHERE id=? AND status='queued' AND cancel_requested=0",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE jobs SET status='running', worker_id=?, assigned_npus=?,
                    started_at=?, updated_at=? WHERE id=? AND status='queued'""",
                (worker_id, json.dumps(npus), now, now, row["id"]),
            )
            if connection.total_changes != 1:
                return None
        return self.get(job_id)

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        exit_code: int,
        artifact_path: str,
        artifact_sha256: str,
        error: str | None,
    ) -> None:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError(status)
        now = int(time.time())
        with self.connect() as connection:
            connection.execute(
                """UPDATE jobs SET status=?, exit_code=?, artifact_path=?, artifact_sha256=?,
                    error=?, updated_at=?, finished_at=? WHERE id=? AND status='running'""",
                (
                    status,
                    exit_code,
                    artifact_path,
                    artifact_sha256,
                    error,
                    now,
                    now,
                    job_id,
                ),
            )
