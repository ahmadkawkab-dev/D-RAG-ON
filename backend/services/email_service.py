"""SMTP delivery for account security messages."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from backend.core.config import Settings


logger = logging.getLogger(__name__)


class EmailConfigurationError(RuntimeError):
    """Email delivery is unavailable in the current environment."""


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_available(self) -> None:
        if self.settings.smtp_host:
            return
        if self.settings.environment == "production":
            raise EmailConfigurationError("SMTP is not configured")

    async def send_password_reset_code(
        self,
        email: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        self.ensure_available()
        if not self.settings.smtp_host:
            logger.warning(
                "Development password reset code for %s: %s",
                email,
                code,
            )
            return
        await asyncio.to_thread(
            self._send_password_reset_code,
            email,
            code,
            expires_in_minutes,
        )

    def _send_password_reset_code(
        self,
        email: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = "Your Pixel Mind password reset code"
        message["From"] = self.settings.smtp_from_email
        message["To"] = email
        message.set_content(
            "Use this code to reset your Pixel Mind password:\n\n"
            f"{code}\n\n"
            f"The code expires in {expires_in_minutes} minutes. "
            "If you did not request this, you can ignore this email."
        )

        smtp_class = smtplib.SMTP_SSL if self.settings.smtp_use_ssl else smtplib.SMTP
        with smtp_class(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=self.settings.smtp_timeout_seconds,
        ) as client:
            if self.settings.smtp_starttls and not self.settings.smtp_use_ssl:
                client.starttls()
            if self.settings.smtp_username:
                password = (
                    self.settings.smtp_password.get_secret_value()
                    if self.settings.smtp_password
                    else ""
                )
                client.login(self.settings.smtp_username, password)
            client.send_message(message)
