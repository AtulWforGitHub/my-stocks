"""SMTP email. Credentials come from environment variables / GitHub Secrets only."""
from __future__ import annotations
import smtplib
import ssl
from email.message import EmailMessage
from .config import secret, redact


def send_email(subject: str, html_body: str, text_body: str, to_addr: str, attachments: list[tuple[str, bytes, str]] | None = None) -> tuple[bool, str]:
    user = secret("GMAIL_ADDRESS") or to_addr
    pw = secret("GMAIL_APP_PASSWORD")
    if not pw:
        return False, "GMAIL_APP_PASSWORD not set - email skipped (see README step 4)"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to_addr
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    for name, data, mime in attachments or []:
        mt, st = mime.split("/")
        msg.add_attachment(data, maintype=mt, subtype=st, filename=name)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
        return True, "sent"
    except Exception as e:  # noqa: BLE001
        return False, redact(f"email failed: {type(e).__name__}: {e}")
