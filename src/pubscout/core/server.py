"""Lightweight local HTTP server for PubScout report viewing and live feedback.

Serves the latest HTML report and exposes a ``/api/feedback`` POST endpoint
that writes ratings directly to the SQLite database — no export/import needed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from pubscout.core.models import FeedbackSignal
from pubscout.storage.database import PubScoutDB

logger = logging.getLogger(__name__)

_REPORTS_DIR = Path.home() / ".pubscout" / "reports"


class FeedbackHandler(SimpleHTTPRequestHandler):
    """HTTP handler: serves reports + accepts live feedback POSTs."""

    db: PubScoutDB  # set via partial/class attribute

    def do_GET(self) -> None:  # noqa: N802
        """Serve the latest report at ``/`` or a specific report by name."""
        if self.path == "/" or self.path == "/index.html":
            self._serve_latest_report()
        elif self.path == "/api/health":
            self._json_response(200, {"status": "ok"})
        else:
            # Serve static files from reports dir
            super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        """Accept feedback at ``/api/feedback``."""
        if self.path == "/api/feedback":
            self._handle_feedback()
        else:
            self._json_response(404, {"error": "not found"})

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight."""
        self.send_response(200)
        self._add_cors_headers()
        self.end_headers()

    # ── Internal ─────────────────────────────────────────────────────

    def _serve_latest_report(self) -> None:
        """Find and serve the most recent report HTML."""
        reports = sorted(_REPORTS_DIR.glob("report_*.html"), reverse=True)
        if not reports:
            self._json_response(404, {"error": "No reports found. Run 'pubscout scan' first."})
            return

        content = reports[0].read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _handle_feedback(self) -> None:
        """Accept a single feedback vote: {publication_id, signal}."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            pub_id = body.get("publication_id")
            signal = body.get("signal")

            if not pub_id or signal not in ("positive", "negative"):
                self._json_response(400, {"error": "Need publication_id and signal (positive/negative)"})
                return

            # Check publication exists
            if not self.db.get_publication(pub_id):
                self._json_response(404, {"error": f"Publication {pub_id} not found in database"})
                return

            feedback = FeedbackSignal(
                publication_id=pub_id,
                signal=signal,
                timestamp=datetime.now(timezone.utc),
            )
            self.db.save_feedback(feedback)
            logger.info("Feedback saved: %s → %s", pub_id[:8], signal)
            self._json_response(200, {"status": "saved", "publication_id": pub_id, "signal": signal})

        except (json.JSONDecodeError, ValueError) as exc:
            self._json_response(400, {"error": str(exc)})

    def _json_response(self, code: int, data: dict) -> None:
        content = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _add_cors_headers(self) -> None:
        """Allow requests from file:// and localhost origins."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt: str, *args: object) -> None:
        """Route access logs through Python logging."""
        logger.debug(fmt, *args)


def run_server(port: int = 8585, db: PubScoutDB | None = None) -> None:
    """Start the feedback server on *port*.

    Serves reports from ``~/.pubscout/reports/`` and writes feedback
    directly to the PubScout SQLite database.
    """
    if db is None:
        db = PubScoutDB()

    FeedbackHandler.db = db
    handler = partial(FeedbackHandler, directory=str(_REPORTS_DIR))

    server = HTTPServer(("127.0.0.1", port), handler)
    logger.info("PubScout feedback server running at http://localhost:%d", port)
    print(f"\n  📡 PubScout server running at http://localhost:{port}")
    print(f"  📄 Serving latest report from {_REPORTS_DIR}")
    print(f"  💾 Feedback saves directly to database")
    print(f"\n  Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
