"""保存 crawler 的可追溯稽核紀錄；不保存 Cookie、帳號或完整 HTML。"""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT
from src.db.database import get_connection


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class CrawlerAuditRecorder:
    """每個 Pipeline 共用一個 recorder；每次呼叫各自開 SQLite connection，適用背景執行緒。"""

    def __init__(self, database_path: str, run_id: str, persist_diagnostics: bool = True):
        self.database_path = database_path
        self.run_id = run_id
        self.persist_diagnostics = persist_diagnostics
        self.artifact_root = PROJECT_ROOT / "data" / "crawler-artifacts"

    def start_run(self, context: dict[str, Any]) -> None:
        conn = get_connection(self.database_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO crawler_runs "
                "(run_id, status, context_json, started_at, completed_at, error_message) "
                "VALUES (?, 'RUNNING', ?, CURRENT_TIMESTAMP, NULL, NULL)",
                (self.run_id, _json(context)),
            )
            conn.commit()
        finally:
            conn.close()

    def finish_run(self, status: str, error_message: str | None = None) -> None:
        conn = get_connection(self.database_path)
        try:
            conn.execute(
                "UPDATE crawler_runs SET status=?, completed_at=CURRENT_TIMESTAMP, error_message=? "
                "WHERE run_id=?",
                (status, error_message, self.run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def start_attempt(self, context: dict[str, Any]) -> int:
        conn = get_connection(self.database_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO crawler_attempts
                (run_id, stage, source, query_kind, origin_airport, dest_airport,
                 outbound_date, inbound_date, trip_type, passenger_count, direct_only,
                 source_url, outbound_candidates_json, inbound_candidates_json, attempt_no,
                 status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', CURRENT_TIMESTAMP)
                """,
                (
                    self.run_id, context.get("stage"), context.get("source"),
                    context.get("query_kind"), context.get("origin"), context.get("dest"),
                    context.get("outbound_date"), context.get("inbound_date"), context.get("trip_type"),
                    context.get("passenger_count"), int(bool(context.get("direct_only"))),
                    context.get("source_url"), _json(context.get("outbound_candidates", [])),
                    _json(context.get("inbound_candidates", [])), context.get("attempt_no", 1),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def finish_attempt(
        self, attempt_id: int, status: str, *, result_count: int = 0,
        result_card_count: int | None = None, error: Exception | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        conn = get_connection(self.database_path)
        try:
            conn.execute(
                """
                UPDATE crawler_attempts
                SET status=?, result_count=?, result_card_count=?, error_type=?, error_message=?,
                    completed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, result_count, result_card_count,
                 type(error).__name__ if error else None, str(error) if error else None, attempt_id),
            )
            if diagnostic and self.persist_diagnostics:
                conn.execute(
                    "INSERT INTO crawler_diagnostics (attempt_id, kind, payload_json) VALUES (?, ?, ?)",
                    (attempt_id, diagnostic.get("kind", "STATE"), _json(diagnostic)),
                )
            conn.commit()
        finally:
            conn.close()

    def record_diagnostic(self, attempt_id: int, diagnostic: dict[str, Any]) -> None:
        """額外診斷不可覆蓋 attempt 的最終狀態。"""
        if not self.persist_diagnostics:
            return
        conn = get_connection(self.database_path)
        try:
            conn.execute(
                "INSERT INTO crawler_diagnostics (attempt_id, kind, payload_json) VALUES (?, ?, ?)",
                (attempt_id, diagnostic.get("kind", "STATE"), _json(diagnostic)),
            )
            conn.commit()
        finally:
            conn.close()

    def artifact_path(self, attempt_id: int, filename: str) -> Path:
        """產物一律限制在本機 audit 根目錄下。"""
        directory = self.artifact_root / self.run_id / f"attempt-{attempt_id}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / filename

    def record_artifact(
        self, attempt_id: int, kind: str, path: Path, metadata: dict[str, Any] | None = None,
    ) -> None:
        resolved_root = self.artifact_root.resolve()
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(resolved_root):
            raise ValueError("診斷產物路徑超出 crawler-artifacts 根目錄")
        content = resolved_path.read_bytes()
        relative_path = resolved_path.relative_to(PROJECT_ROOT).as_posix()
        conn = get_connection(self.database_path)
        try:
            conn.execute(
                """INSERT INTO crawler_artifacts
                (attempt_id, kind, relative_path, sha256, byte_size, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (attempt_id, kind, relative_path, sha256(content).hexdigest(), len(content), _json(metadata or {})),
            )
            conn.commit()
        finally:
            conn.close()


def prune_crawler_audit(conn: sqlite3.Connection, retention_days: int) -> int:
    """清除過期 run 及其子資料。SQLite 外鍵不保證每條 connection 都已啟用，故明確刪除。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
    run_ids = [row["run_id"] for row in conn.execute(
        "SELECT run_id FROM crawler_runs WHERE started_at < ?", (cutoff,)
    )]
    if not run_ids:
        return 0
    placeholders = ",".join("?" for _ in run_ids)
    attempt_ids = [row["id"] for row in conn.execute(
        f"SELECT id FROM crawler_attempts WHERE run_id IN ({placeholders})", run_ids,
    )]
    delete_registered_artifact_files(conn, attempt_ids)
    conn.execute(
        f"DELETE FROM crawler_artifacts WHERE attempt_id IN "
        f"(SELECT id FROM crawler_attempts WHERE run_id IN ({placeholders}))", run_ids,
    )
    conn.execute(
        f"DELETE FROM crawler_diagnostics WHERE attempt_id IN "
        f"(SELECT id FROM crawler_attempts WHERE run_id IN ({placeholders}))", run_ids,
    )
    conn.execute(f"DELETE FROM crawler_attempts WHERE run_id IN ({placeholders})", run_ids)
    deleted = conn.execute(f"DELETE FROM crawler_runs WHERE run_id IN ({placeholders})", run_ids).rowcount
    conn.commit()
    return deleted


def delete_registered_artifact_files(
    conn: sqlite3.Connection, attempt_ids: list[int] | None = None,
) -> int:
    """清除已登錄的 artifact 檔，不接受資料庫外的任意路徑。"""
    artifact_root = (PROJECT_ROOT / "data" / "crawler-artifacts").resolve()
    if attempt_ids:
        placeholders = ",".join("?" for _ in attempt_ids)
        rows = conn.execute(
            f"SELECT relative_path FROM crawler_artifacts WHERE attempt_id IN ({placeholders})", attempt_ids,
        ).fetchall()
    else:
        rows = conn.execute("SELECT relative_path FROM crawler_artifacts").fetchall()
    deleted = 0
    for row in rows:
        try:
            path = (PROJECT_ROOT / row["relative_path"]).resolve()
            if path.is_relative_to(artifact_root) and path.is_file():
                path.unlink()
                deleted += 1
        except OSError:
            # DB 清除仍要完成；遺留檔在下次保留期清理時可再處理。
            continue
    return deleted


def fetch_crawler_runs(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    runs = [dict(row) for row in conn.execute(
        "SELECT * FROM crawler_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    )]
    for run in runs:
        run["context"] = json.loads(run.pop("context_json") or "{}")
        attempts = [dict(row) for row in conn.execute(
            "SELECT * FROM crawler_attempts WHERE run_id=? ORDER BY id", (run["run_id"],)
        )]
        for attempt in attempts:
            attempt["outbound_candidates"] = json.loads(attempt.pop("outbound_candidates_json") or "[]")
            attempt["inbound_candidates"] = json.loads(attempt.pop("inbound_candidates_json") or "[]")
            diagnostics = [dict(row) for row in conn.execute(
                "SELECT kind, payload_json, created_at FROM crawler_diagnostics WHERE attempt_id=? ORDER BY id",
                (attempt["id"],),
            )]
            attempt["diagnostics"] = [
                {"kind": item["kind"], "payload": json.loads(item["payload_json"] or "{}"), "created_at": item["created_at"]}
                for item in diagnostics
            ]
            artifacts = [dict(row) for row in conn.execute(
                "SELECT id, kind, byte_size, metadata_json, created_at FROM crawler_artifacts "
                "WHERE attempt_id=? ORDER BY id", (attempt["id"],)
            )]
            attempt["artifacts"] = [
                {**item, "metadata": json.loads(item.pop("metadata_json") or "{}")}
                for item in artifacts
            ]
        run["attempts"] = attempts
    return runs
