"""Custom URL protocol handler for PubScout feedback.

Registers ``pubscout://`` as a URL scheme so that clicking feedback
buttons in the HTML report writes directly to the SQLite database
without any background server.

URL format:
    pubscout://feedback?id=<publication_id>&signal=<positive|negative>

The browser opens the URL, the OS dispatches it to
``pubscout protocol-handle <url>``, which parses the query string
and records the feedback.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


def handle_url(url: str) -> dict:
    """Parse a ``pubscout://`` URL and record feedback.

    Returns a dict with the result: {status, publication_id, signal}
    or {error}.
    """
    from datetime import datetime, timezone

    from pubscout.core.models import FeedbackSignal
    from pubscout.storage.database import PubScoutDB

    parsed = urlparse(url)
    if parsed.scheme != "pubscout":
        return {"error": f"Unknown scheme: {parsed.scheme}"}

    if parsed.netloc != "feedback" and parsed.path.lstrip("/") != "feedback":
        return {"error": f"Unknown action: {parsed.netloc or parsed.path}"}

    params = parse_qs(parsed.query)
    pub_id = params.get("id", [None])[0]
    signal = params.get("signal", [None])[0]

    if not pub_id or signal not in ("positive", "negative"):
        return {"error": f"Invalid params: id={pub_id}, signal={signal}"}

    db = PubScoutDB()

    if not db.get_publication(pub_id):
        db.close()
        return {"error": f"Publication {pub_id} not found"}

    feedback = FeedbackSignal(
        publication_id=pub_id,
        signal=signal,
        timestamp=datetime.now(timezone.utc),
    )
    db.save_feedback(feedback)
    db.close()
    logger.info("Feedback recorded: %s → %s", pub_id[:8], signal)
    return {"status": "saved", "publication_id": pub_id, "signal": signal}


def _get_pubscout_exe() -> str:
    """Find the full path to the pubscout executable."""
    exe = shutil.which("pubscout")
    if exe:
        return str(Path(exe).resolve())
    # Fallback: use the Python entry point
    return f'"{sys.executable}" -m pubscout.cli.main'


def register_protocol() -> bool:
    """Register the ``pubscout://`` URL scheme on the current OS.

    Returns True on success, False on failure.
    """
    system = platform.system()
    if system == "Windows":
        return _register_windows()
    elif system == "Darwin":
        return _register_macos()
    else:
        return _register_linux()


def unregister_protocol() -> bool:
    """Remove the ``pubscout://`` URL scheme registration."""
    system = platform.system()
    if system == "Windows":
        return _unregister_windows()
    elif system == "Darwin":
        logger.info("macOS: remove PubScout.app from ~/Applications to unregister")
        return True
    else:
        return _unregister_linux()


# ── Windows ──────────────────────────────────────────────────────────


def _register_windows() -> bool:
    """Register via Windows Registry (HKCU, no admin needed)."""
    try:
        import winreg

        exe_path = _get_pubscout_exe()
        command = f'"{exe_path}" protocol-handle "%1"'

        key_path = r"Software\Classes\pubscout"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "PubScout Feedback Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

        shell_path = rf"{key_path}\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, shell_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)

        logger.info("Registered pubscout:// protocol (Windows Registry)")
        return True

    except Exception as exc:
        logger.error("Failed to register protocol on Windows: %s", exc)
        return False


def _unregister_windows() -> bool:
    """Remove the Windows Registry entries."""
    try:
        import winreg

        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\pubscout\shell\open\command",
        )
        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\pubscout\shell\open",
        )
        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\pubscout\shell",
        )
        winreg.DeleteKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Classes\pubscout",
        )
        logger.info("Unregistered pubscout:// protocol (Windows)")
        return True
    except Exception as exc:
        logger.error("Failed to unregister protocol on Windows: %s", exc)
        return False


# ── macOS ────────────────────────────────────────────────────────────


def _register_macos() -> bool:
    """Register via a minimal .app bundle with CFBundleURLTypes."""
    try:
        exe_path = _get_pubscout_exe()
        app_dir = Path.home() / "Applications" / "PubScout.app" / "Contents"
        macos_dir = app_dir / "MacOS"
        macos_dir.mkdir(parents=True, exist_ok=True)

        # Info.plist
        plist = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>com.pubscout.feedback</string>
  <key>CFBundleName</key>
  <string>PubScout</string>
  <key>CFBundleExecutable</key>
  <string>pubscout-handler</string>
  <key>CFBundleURLTypes</key>
  <array>
    <dict>
      <key>CFBundleURLSchemes</key>
      <array><string>pubscout</string></array>
      <key>CFBundleURLName</key>
      <string>PubScout Feedback</string>
    </dict>
  </array>
</dict>
</plist>"""
        (app_dir / "Info.plist").write_text(plist)

        # Launcher script
        launcher = f"#!/bin/sh\n{exe_path} protocol-handle \"$1\"\n"
        launcher_path = macos_dir / "pubscout-handler"
        launcher_path.write_text(launcher)
        launcher_path.chmod(0o755)

        # Register with Launch Services
        subprocess.run(
            ["/System/Library/Frameworks/CoreServices.framework/Versions/A/"
             "Frameworks/LaunchServices.framework/Versions/A/Support/lsregister",
             "-R", str(app_dir.parent)],
            capture_output=True,
        )

        logger.info("Registered pubscout:// protocol (macOS app bundle)")
        return True

    except Exception as exc:
        logger.error("Failed to register protocol on macOS: %s", exc)
        return False


# ── Linux ────────────────────────────────────────────────────────────


def _register_linux() -> bool:
    """Register via XDG .desktop file."""
    try:
        exe_path = _get_pubscout_exe()
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        desktop_dir.mkdir(parents=True, exist_ok=True)

        desktop = f"""\
[Desktop Entry]
Name=PubScout Feedback
Exec={exe_path} protocol-handle %u
Type=Application
NoDisplay=true
MimeType=x-scheme-handler/pubscout;
"""
        (desktop_dir / "pubscout-handler.desktop").write_text(desktop)

        subprocess.run(
            ["xdg-mime", "default", "pubscout-handler.desktop",
             "x-scheme-handler/pubscout"],
            capture_output=True,
        )

        logger.info("Registered pubscout:// protocol (XDG)")
        return True

    except Exception as exc:
        logger.error("Failed to register protocol on Linux: %s", exc)
        return False


def _unregister_linux() -> bool:
    """Remove the XDG .desktop file."""
    try:
        desktop = Path.home() / ".local" / "share" / "applications" / "pubscout-handler.desktop"
        if desktop.exists():
            desktop.unlink()
        logger.info("Unregistered pubscout:// protocol (Linux)")
        return True
    except Exception as exc:
        logger.error("Failed to unregister protocol on Linux: %s", exc)
        return False
