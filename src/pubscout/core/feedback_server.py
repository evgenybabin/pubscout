"""Lightweight HTTP feedback server for PubScout email links."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pubscout.core.models import FeedbackSignal

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = Path.home() / ".pubscout"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "pubscout.db"

_THANKS_HTML = """\
<!DOCTYPE html><html><head><title>Thanks!</title></head>
<body style="font-family:Arial;text-align:center;padding:60px;">
<h2>Thank you for your feedback!</h2>
<p>Your {signal} signal for this publication has been recorded.</p>
<p style="color:#777;font-size:13px;">You can close this tab.</p>
</body></html>"""

_ERROR_HTML = """\
<!DOCTYPE html><html><head><title>Error</title></head>
<body style="font-family:Arial;text-align:center;padding:60px;">
<h2>Error</h2><p>{message}</p>
</body></html>"""


class FeedbackHandler(BaseHTTPRequestHandler):
    """Handle GET /feedback and GET /health."""

    server: FeedbackServer  # type: ignore[assignment]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._respond_json(200, {"status": "ok"})
        elif parsed.path == "/feedback":
            self._handle_feedback(parsed.query)
        else:
            self._respond_html(404, _ERROR_HTML.format(message="Not found"))

    def _handle_feedback(self, query_string: str) -> None:
        params = parse_qs(query_string)
        pub_id = params.get("id", [None])[0]
        signal = params.get("signal", [None])[0]

        if not pub_id:
            self._respond_html(400, _ERROR_HTML.format(message="Missing 'id' parameter"))
            return
        if not signal:
            self._respond_html(400, _ERROR_HTML.format(message="Missing 'signal' parameter"))
            return
        if signal not in ("positive", "negative"):
            self._respond_html(
                400,
                _ERROR_HTML.format(message=f"Invalid signal '{signal}'. Use 'positive' or 'negative'."),
            )
            return

        # Check publication exists
        if not self._publication_exists(pub_id):
            self._respond_html(
                404,
                _ERROR_HTML.format(message=f"Publication '{pub_id}' not found. It may have been removed."),
            )
            return

        # Save feedback
        fb = FeedbackSignal(publication_id=pub_id, signal=signal)
        self._save_feedback(fb)
        self.server.last_activity = time.time()
        self._respond_html(200, _THANKS_HTML.format(signal=signal))

    def _publication_exists(self, pub_id: str) -> bool:
        conn = sqlite3.connect(str(self.server.db_path))
        try:
            row = conn.execute(
                "SELECT 1 FROM publications WHERE id = ?", (pub_id,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def _save_feedback(self, fb: FeedbackSignal) -> None:
        conn = sqlite3.connect(str(self.server.db_path))
        try:
            conn.execute(
                "INSERT INTO feedback (publication_id, timestamp, signal, user_notes) VALUES (?, ?, ?, ?)",
                (fb.publication_id, fb.timestamp.isoformat(), fb.signal, fb.user_notes),
            )
            conn.commit()
        finally:
            conn.close()

    def _respond_html(self, code: int, html: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _respond_json(self, code: int, data: dict) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug(fmt, *args)


class FeedbackServer(HTTPServer):
    """HTTPServer subclass carrying db_path and inactivity tracking."""

    def __init__(
        self,
        port: int = 8230,
        db_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.last_activity = time.time()
        super().__init__(("127.0.0.1", port), FeedbackHandler)

    def start(self, timeout: int = 3600) -> None:
        """Serve until *timeout* seconds of inactivity."""
        logger.info("Feedback server listening on port %d (timeout=%ds)", self.server_port, timeout)
        self.last_activity = time.time()
        self.timeout = 1.0  # check every second

        try:
            while True:
                self.handle_request()
                if time.time() - self.last_activity > timeout:
                    logger.info("Inactivity timeout reached — shutting down")
                    break
        finally:
            self.server_close()

    def start_background(self, ready: threading.Event | None = None) -> threading.Thread:
        """Start server in a daemon thread.  Sets *ready* once listening."""
        def _run() -> None:
            if ready:
                ready.set()
            self.start(timeout=3600)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PubScout feedback server")
    parser.add_argument("--port", type=int, default=8230)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    server = FeedbackServer(port=args.port)
    logger.info("Feedback server listening on http://127.0.0.1:%d", args.port)
    server.start(timeout=args.timeout)
