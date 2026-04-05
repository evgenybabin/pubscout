"""SQLite storage layer for PubScout."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pubscout.core.models import FeedbackSignal, Publication, ScanRun

_DEFAULT_DB_DIR = Path.home() / ".pubscout"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "pubscout.db"

_SCHEMA = """\
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_arxiv_id
    ON publications(arxiv_id) WHERE arxiv_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_doi
    ON publications(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_reported
    ON publications(reported);

CREATE TABLE IF NOT EXISTS scan_runs (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    sources_checked INTEGER,
    items_fetched INTEGER,
    items_scored INTEGER,
    items_reported INTEGER,
    errors TEXT,
    duration_seconds REAL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    signal TEXT NOT NULL CHECK(signal IN ('positive', 'negative')),
    user_notes TEXT,
    FOREIGN KEY (publication_id) REFERENCES publications(id)
);
"""


class PubScoutDB:
    """Thin SQLite wrapper for PubScout persistence."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = _DEFAULT_DB_PATH
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ── Publications ─────────────────────────────────────────────────

    def save_publication(self, pub: Publication) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO publications
                (id, title, authors, abstract, url, doi, arxiv_id,
                 source_label, publication_date, fetch_date,
                 relevance_score, matched_domains, reported)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pub.id,
                pub.title,
                json.dumps(pub.authors),
                pub.abstract,
                pub.url,
                pub.doi,
                pub.arxiv_id,
                pub.source_label,
                pub.publication_date.isoformat() if pub.publication_date else None,
                pub.fetch_date.isoformat(),
                pub.relevance_score,
                json.dumps(pub.matched_domains),
                int(pub.reported),
            ),
        )
        self._conn.commit()

    def get_publication(self, pub_id: str) -> Publication | None:
        row = self._conn.execute(
            "SELECT * FROM publications WHERE id = ?", (pub_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_publication(row)

    def publication_exists(
        self,
        arxiv_id: str | None = None,
        doi: str | None = None,
        title: str | None = None,
    ) -> bool:
        if arxiv_id is not None:
            cur = self._conn.execute(
                "SELECT 1 FROM publications WHERE arxiv_id = ?", (arxiv_id,)
            )
            if cur.fetchone():
                return True
        if doi is not None:
            cur = self._conn.execute(
                "SELECT 1 FROM publications WHERE doi = ?", (doi,)
            )
            if cur.fetchone():
                return True
        if title is not None:
            cur = self._conn.execute(
                "SELECT 1 FROM publications WHERE title = ?", (title,)
            )
            if cur.fetchone():
                return True
        return False

    def get_unreported_publications(self, min_score: float = 0.0) -> list[Publication]:
        rows = self._conn.execute(
            """
            SELECT * FROM publications
            WHERE reported = 0
              AND (relevance_score IS NOT NULL AND relevance_score >= ?)
            ORDER BY relevance_score DESC
            """,
            (min_score,),
        ).fetchall()
        return [self._row_to_publication(r) for r in rows]

    def mark_reported(self, pub_ids: list[str]) -> None:
        if not pub_ids:
            return
        placeholders = ",".join("?" for _ in pub_ids)
        self._conn.execute(
            f"UPDATE publications SET reported = 1 WHERE id IN ({placeholders})",
            pub_ids,
        )
        self._conn.commit()

    # ── Scan Runs ────────────────────────────────────────────────────

    def save_scan_run(self, run: ScanRun) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO scan_runs
                (id, timestamp, sources_checked, items_fetched,
                 items_scored, items_reported, errors, duration_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.timestamp.isoformat(),
                run.sources_checked,
                run.items_fetched,
                run.items_scored,
                run.items_reported,
                json.dumps(run.errors),
                run.duration_seconds,
            ),
        )
        self._conn.commit()

    def get_scan_runs(self, limit: int = 10) -> list[ScanRun]:
        rows = self._conn.execute(
            "SELECT * FROM scan_runs ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_scan_run(r) for r in rows]

    def get_last_scan_time(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT timestamp FROM scan_runs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["timestamp"])

    # ── Feedback ─────────────────────────────────────────────────────

    def save_feedback(self, feedback: FeedbackSignal) -> None:
        self._conn.execute(
            """
            INSERT INTO feedback (publication_id, timestamp, signal, user_notes)
            VALUES (?, ?, ?, ?)
            """,
            (
                feedback.publication_id,
                feedback.timestamp.isoformat(),
                feedback.signal,
                feedback.user_notes,
            ),
        )
        self._conn.commit()

    def get_feedback(self, limit: int = 100) -> list[FeedbackSignal]:
        rows = self._conn.execute(
            "SELECT * FROM feedback ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            FeedbackSignal(
                publication_id=r["publication_id"],
                signal=r["signal"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                user_notes=r["user_notes"],
            )
            for r in rows
        ]

    def get_positive_examples(self, limit: int = 20) -> list[Publication]:
        rows = self._conn.execute(
            """
            SELECT p.* FROM publications p
            JOIN feedback f ON f.publication_id = p.id
            WHERE f.signal = 'positive'
            ORDER BY f.timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_publication(r) for r in rows]

    def get_negative_examples(self, limit: int = 20) -> list[Publication]:
        rows = self._conn.execute(
            """
            SELECT p.* FROM publications p
            JOIN feedback f ON f.publication_id = p.id
            WHERE f.signal = 'negative'
            ORDER BY f.timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_publication(r) for r in rows]

    # ── Aggregate Stats ─────────────────────────────────────────────

    def count_publications(self, since: str | None = None) -> int:
        if since:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM publications WHERE fetch_date >= ?", (since,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM publications").fetchone()
        return row[0] if row else 0

    def count_reported_publications(self, since: str | None = None) -> int:
        if since:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM publications WHERE reported = 1 AND fetch_date >= ?",
                (since,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM publications WHERE reported = 1"
            ).fetchone()
        return row[0] if row else 0

    def count_scans(self, since: str | None = None) -> int:
        if since:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM scan_runs WHERE timestamp >= ?", (since,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()
        return row[0] if row else 0

    def count_feedback_by_signal(self, since: str | None = None) -> dict[str, int]:
        if since:
            rows = self._conn.execute(
                "SELECT signal, COUNT(*) FROM feedback WHERE timestamp >= ? GROUP BY signal",
                (since,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT signal, COUNT(*) FROM feedback GROUP BY signal"
            ).fetchall()
        result: dict[str, int] = {"positive": 0, "negative": 0}
        for r in rows:
            result[r[0]] = r[1]
        return result

    def get_domain_stats(self, since: str | None = None) -> list[tuple[str, int]]:
        """Return (domain_label, count) for reported publications."""
        if since:
            rows = self._conn.execute(
                """SELECT matched_domains FROM publications
                   WHERE reported = 1 AND fetch_date >= ?""",
                (since,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT matched_domains FROM publications WHERE reported = 1"
            ).fetchall()
        domain_counts: dict[str, int] = {}
        for r in rows:
            domains = json.loads(r[0]) if r[0] else []
            for d in domains:
                domain_counts[d] = domain_counts.get(d, 0) + 1
        return sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)

    def get_source_stats(self, since: str | None = None) -> list[tuple[str, int, int]]:
        """Return (source_label, fetched_count, reported_count)."""
        if since:
            rows = self._conn.execute(
                """SELECT source_label,
                          COUNT(*) as total,
                          SUM(CASE WHEN reported = 1 THEN 1 ELSE 0 END) as reported
                   FROM publications WHERE fetch_date >= ?
                   GROUP BY source_label ORDER BY total DESC""",
                (since,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT source_label,
                          COUNT(*) as total,
                          SUM(CASE WHEN reported = 1 THEN 1 ELSE 0 END) as reported
                   FROM publications GROUP BY source_label ORDER BY total DESC"""
            ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_publication(row: sqlite3.Row) -> Publication:
        return Publication(
            id=row["id"],
            title=row["title"],
            authors=json.loads(row["authors"]),
            abstract=row["abstract"],
            url=row["url"],
            doi=row["doi"],
            arxiv_id=row["arxiv_id"],
            source_label=row["source_label"],
            publication_date=(
                datetime.fromisoformat(row["publication_date"])
                if row["publication_date"]
                else None
            ),
            fetch_date=datetime.fromisoformat(row["fetch_date"]),
            relevance_score=row["relevance_score"],
            matched_domains=json.loads(row["matched_domains"]) if row["matched_domains"] else [],
            reported=bool(row["reported"]),
        )

    @staticmethod
    def _row_to_scan_run(row: sqlite3.Row) -> ScanRun:
        return ScanRun(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            sources_checked=row["sources_checked"],
            items_fetched=row["items_fetched"],
            items_scored=row["items_scored"],
            items_reported=row["items_reported"],
            errors=json.loads(row["errors"]) if row["errors"] else [],
            duration_seconds=row["duration_seconds"],
        )
