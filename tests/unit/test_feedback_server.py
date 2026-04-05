"""Tests for the HTTP feedback server."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import httpx
import pytest

from pubscout.core.feedback_server import FeedbackServer


@pytest.fixture()
def _feedback_db(tmp_path: Path):
    """Create a test database with schema and a sample publication."""
    db_path = tmp_path / "pubscout.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """\
        CREATE TABLE IF NOT EXISTS publications (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            authors TEXT NOT NULL,
            abstract TEXT NOT NULL,
            url TEXT NOT NULL,
            doi TEXT,
            arxiv_id TEXT,
            source_label TEXT NOT NULL,
            publication_date TEXT,
            fetch_date TEXT NOT NULL,
            relevance_score REAL,
            matched_domains TEXT,
            reported INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            publication_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            signal TEXT NOT NULL,
            user_notes TEXT
        );
        INSERT INTO publications (id, title, authors, abstract, url, source_label, fetch_date)
        VALUES ('pub-001', 'Test Paper', '["Alice"]', 'Abstract', 'https://example.com/p1', 'arXiv', '2024-01-01');
        """
    )
    conn.close()
    return db_path


@pytest.fixture()
def feedback_server(_feedback_db: Path):
    """Start a feedback server in a background thread and yield its base URL."""
    # Use port 0 to let OS assign a free port
    server = FeedbackServer(port=0, db_path=_feedback_db)
    port = server.server_port
    ready = threading.Event()
    thread = threading.Thread(target=_run_server, args=(server, ready), daemon=True)
    thread.start()
    ready.wait(timeout=5)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


def _run_server(server: FeedbackServer, ready: threading.Event) -> None:
    ready.set()
    server.serve_forever()


class TestFeedbackServer:
    def test_health_endpoint(self, feedback_server):
        resp = httpx.get(f"{feedback_server}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_positive_feedback(self, feedback_server, _feedback_db):
        resp = httpx.get(f"{feedback_server}/feedback?id=pub-001&signal=positive")
        assert resp.status_code == 200
        assert "Thank you" in resp.text
        # Verify in DB
        conn = sqlite3.connect(str(_feedback_db))
        row = conn.execute(
            "SELECT signal FROM feedback WHERE publication_id = 'pub-001'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "positive"

    def test_negative_feedback(self, feedback_server, _feedback_db):
        resp = httpx.get(f"{feedback_server}/feedback?id=pub-001&signal=negative")
        assert resp.status_code == 200
        conn = sqlite3.connect(str(_feedback_db))
        row = conn.execute(
            "SELECT signal FROM feedback WHERE publication_id = 'pub-001'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "negative"

    def test_missing_id_param(self, feedback_server):
        resp = httpx.get(f"{feedback_server}/feedback?signal=positive")
        assert resp.status_code == 400
        assert "Missing" in resp.text

    def test_missing_signal_param(self, feedback_server):
        resp = httpx.get(f"{feedback_server}/feedback?id=pub-001")
        assert resp.status_code == 400
        assert "Missing" in resp.text

    def test_invalid_signal_value(self, feedback_server):
        resp = httpx.get(f"{feedback_server}/feedback?id=pub-001&signal=maybe")
        assert resp.status_code == 400
        assert "Invalid" in resp.text

    def test_unknown_publication_id(self, feedback_server):
        resp = httpx.get(f"{feedback_server}/feedback?id=nonexistent&signal=positive")
        assert resp.status_code == 404
        assert "not found" in resp.text

    def test_not_found_path(self, feedback_server):
        resp = httpx.get(f"{feedback_server}/unknown")
        assert resp.status_code == 404
