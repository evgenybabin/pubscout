"""Tests for the SMTP email sender."""

from __future__ import annotations

import os
import smtplib
from unittest.mock import MagicMock, patch

import pytest

from pubscout.core.email import SmtpEmailSender
from pubscout.core.models import EmailConfig


@pytest.fixture()
def smtp_config() -> EmailConfig:
    return EmailConfig(
        transport="smtp",
        from_addr="user@example.com",
        to_addr="recipient@example.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_username="user@example.com",
        smtp_password_env="TEST_SMTP_PASS",
    )


@pytest.fixture()
def ssl_config() -> EmailConfig:
    return EmailConfig(
        transport="smtp",
        from_addr="user@example.com",
        to_addr="recipient@example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_use_tls=True,
        smtp_username="user@example.com",
        smtp_password_env="TEST_SMTP_PASS",
    )


class TestSmtpEmailSender:
    def test_send_starttls_success(self, smtp_config, monkeypatch):
        monkeypatch.setenv("TEST_SMTP_PASS", "secret")
        mock_smtp = MagicMock()
        with patch("pubscout.core.email.smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)

            sender = SmtpEmailSender()
            result = sender.send("<html>test</html>", "Subject", smtp_config)

        assert result is True
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once()
        mock_smtp.sendmail.assert_called_once()

    def test_send_ssl_success(self, ssl_config, monkeypatch):
        monkeypatch.setenv("TEST_SMTP_PASS", "secret")
        mock_smtp = MagicMock()
        with patch("pubscout.core.email.smtplib.SMTP_SSL", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)

            sender = SmtpEmailSender()
            result = sender.send("<html>test</html>", "Subject", ssl_config)

        assert result is True
        mock_smtp.login.assert_called_once()

    def test_connection_refused_returns_false(self, smtp_config, monkeypatch):
        monkeypatch.setenv("TEST_SMTP_PASS", "secret")
        with patch(
            "pubscout.core.email.smtplib.SMTP",
            side_effect=ConnectionRefusedError("refused"),
        ):
            sender = SmtpEmailSender()
            result = sender.send("<html>test</html>", "Subject", smtp_config)

        assert result is False

    def test_auth_failure_returns_false(self, smtp_config, monkeypatch):
        monkeypatch.setenv("TEST_SMTP_PASS", "wrong")
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")
        with patch("pubscout.core.email.smtplib.SMTP", return_value=mock_smtp):
            sender = SmtpEmailSender()
            result = sender.send("<html>test</html>", "Subject", smtp_config)

        assert result is False

    def test_missing_password_env_returns_false(self, smtp_config, monkeypatch):
        monkeypatch.delenv("TEST_SMTP_PASS", raising=False)
        sender = SmtpEmailSender()
        result = sender.send("<html>test</html>", "Subject", smtp_config)
        assert result is False

    def test_no_password_env_configured(self):
        config = EmailConfig(
            transport="smtp",
            from_addr="user@example.com",
            to_addr="recipient@example.com",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_password_env="",
        )
        sender = SmtpEmailSender()
        result = sender.send("<html>test</html>", "Subject", config)
        assert result is False

    def test_subject_formatting(self, smtp_config, monkeypatch):
        """Subject is passed through correctly."""
        monkeypatch.setenv("TEST_SMTP_PASS", "secret")
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        with patch("pubscout.core.email.smtplib.SMTP", return_value=mock_smtp):
            sender = SmtpEmailSender()
            sender.send("<html>test</html>", "PubScout Digest 5 papers", smtp_config)
        mock_smtp.sendmail.assert_called_once()
        sent_msg = mock_smtp.sendmail.call_args[0][2]
        assert "PubScout Digest 5 papers" in sent_msg
