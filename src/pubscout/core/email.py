"""SMTP email sender for PubScout digest delivery."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pubscout.core.models import EmailConfig

logger = logging.getLogger(__name__)


class SmtpEmailSender:
    """Send HTML emails via SMTP (STARTTLS or SSL)."""

    def send(self, html_content: str, subject: str, config: EmailConfig) -> bool:
        """Send *html_content* as an email.  Returns ``True`` on success."""
        password = self._resolve_password(config)
        if password is None:
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = config.from_addr
        msg["To"] = config.to_addr
        msg.attach(MIMEText(html_content, "html"))

        try:
            if config.smtp_port == 465:
                return self._send_ssl(msg, config, password)
            return self._send_starttls(msg, config, password)
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "SMTP authentication failed for %s — check password env var '%s'",
                config.smtp_host,
                config.smtp_password_env,
            )
            return False
        except (smtplib.SMTPConnectError, ConnectionRefusedError, OSError) as exc:
            logger.error("SMTP connection refused: %s", exc)
            return False
        except Exception as exc:
            logger.error("SMTP error: %s", exc)
            return False

    # ── private helpers ──────────────────────────────────────

    @staticmethod
    def _resolve_password(config: EmailConfig) -> str | None:
        if not config.smtp_password_env:
            logger.warning("No smtp_password_env configured — cannot send email")
            return None
        password = os.environ.get(config.smtp_password_env)
        if not password:
            logger.warning(
                "Environment variable '%s' not set — cannot send email",
                config.smtp_password_env,
            )
            return None
        return password

    @staticmethod
    def _send_starttls(
        msg: MIMEMultipart, config: EmailConfig, password: str
    ) -> bool:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as server:
            if config.smtp_use_tls:
                server.starttls()
            server.login(config.smtp_username or config.from_addr, password)
            server.sendmail(config.from_addr, [config.to_addr], msg.as_string())
        logger.info("Email sent via STARTTLS to %s", config.to_addr)
        return True

    @staticmethod
    def _send_ssl(msg: MIMEMultipart, config: EmailConfig, password: str) -> bool:
        with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as server:
            server.login(config.smtp_username or config.from_addr, password)
            server.sendmail(config.from_addr, [config.to_addr], msg.as_string())
        logger.info("Email sent via SSL to %s", config.to_addr)
        return True
