"""Durable, isolated mappings between OpenCode sessions and FS chats."""

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from config.config import SESSION_DB_FILE


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def short_id(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


class SessionStore:
    def __init__(self, path=None):
        self.path = str(path or SESSION_DB_FILE)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 10000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS opencode_sessions (
                    session_id TEXT PRIMARY KEY,
                    fs_chat_id TEXT,
                    agent_id TEXT,
                    model_name TEXT,
                    tools_hash TEXT,
                    seen_user_count INTEGER NOT NULL DEFAULT 0,
                    last_user_hash TEXT,
                    seen_tool_results TEXT NOT NULL DEFAULT '[]',
                    pending_tool_calls TEXT NOT NULL DEFAULT '{}',
                    last_request_hash TEXT,
                    last_request_state TEXT,
                    last_response TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )

    @contextmanager
    def lock(self, session_id):
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(session_id, threading.RLock())
        with lock:
            yield

    def get(self, session_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM opencode_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["seen_tool_results"] = json.loads(result["seen_tool_results"] or "[]")
        result["pending_tool_calls"] = json.loads(result["pending_tool_calls"] or "{}")
        result["last_response"] = json.loads(result["last_response"]) if result["last_response"] else None
        return result

    def latest_chat(self):
        """Return the most recently used France Student conversation.

        Used as a fallback when France Student refuses to create a new
        conversation because the daily limit is reached.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_id, fs_chat_id, model_name FROM opencode_sessions "
                "WHERE fs_chat_id IS NOT NULL AND fs_chat_id != '' "
                "ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def mark_inflight(self, session_id, request_hash, agent_id, model_name):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO opencode_sessions (
                    session_id, agent_id, model_name, last_request_hash,
                    last_request_state, updated_at
                ) VALUES (?, ?, ?, ?, 'inflight', ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id = excluded.agent_id,
                    model_name = excluded.model_name,
                    last_request_hash = excluded.last_request_hash,
                    last_request_state = 'inflight',
                    last_response = NULL,
                    updated_at = excluded.updated_at
                """,
                (session_id, str(agent_id), model_name, request_hash, time.time()),
            )

    def mark_ambiguous(self, session_id):
        with self._connect() as connection:
            connection.execute(
                "UPDATE opencode_sessions SET last_request_state = 'ambiguous', updated_at = ? WHERE session_id = ?",
                (time.time(), session_id),
            )

    def mark_failed(self, session_id):
        with self._connect() as connection:
            connection.execute(
                "UPDATE opencode_sessions SET last_request_state = 'failed', updated_at = ? WHERE session_id = ?",
                (time.time(), session_id),
            )

    def mark_completed(self, session_id, *, chat_id, agent_id, model_name, tools_hash,
                       seen_user_count, last_user_hash, seen_tool_results,
                       pending_tool_calls, request_hash, response):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO opencode_sessions (
                    session_id, fs_chat_id, agent_id, model_name, tools_hash,
                    seen_user_count, last_user_hash, seen_tool_results,
                    pending_tool_calls, last_request_hash, last_request_state,
                    last_response, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    fs_chat_id = excluded.fs_chat_id,
                    agent_id = excluded.agent_id,
                    model_name = excluded.model_name,
                    tools_hash = excluded.tools_hash,
                    seen_user_count = excluded.seen_user_count,
                    last_user_hash = excluded.last_user_hash,
                    seen_tool_results = excluded.seen_tool_results,
                    pending_tool_calls = excluded.pending_tool_calls,
                    last_request_hash = excluded.last_request_hash,
                    last_request_state = 'completed',
                    last_response = excluded.last_response,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    chat_id,
                    str(agent_id),
                    model_name,
                    tools_hash,
                    seen_user_count,
                    last_user_hash,
                    json.dumps(sorted(set(seen_tool_results)), ensure_ascii=False),
                    json.dumps(pending_tool_calls, ensure_ascii=False),
                    request_hash,
                    json.dumps(response, ensure_ascii=False),
                    time.time(),
                ),
            )


session_store = SessionStore()
