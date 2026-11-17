"""Notifications: Telegram, a generic JSON webhook, e-mail, and always the audit log.

Every alert also goes to the audit log, so a broken notification channel never loses information.
Credentials are read from environment variables named in the config, never from the config file.
Identical alerts are rate-limited (one per 60 s) so a stuck condition cannot flood your phone.
"""
from __future__ import annotations

import os
import smtplib
import threading
import time
from email.message import EmailMessage

import requests


class Alerter:
    def __init__(self, cfg, audit, sender=None):
        self.cfg = cfg
        self.audit = audit
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.sent: list[tuple[str, str]] = []           # (level, text) kept for the dashboard/tests
        self._sender = sender                          # injectable for tests

    def send(self, text: str, level: str = "INFO", key: str | None = None) -> None:
        key = key or text
        with self._lock:
            now = time.monotonic()
            if now - self._last.get(key, -1e9) < 60:
                return
            self._last[key] = now
            self.sent.append((level, text))
            self.sent = self.sent[-200:]
        self.audit.log("alert", level, text=text)
        if self._sender is not None:
            self._sender(level, text)
            return
        threading.Thread(target=self._dispatch, args=(level, text), daemon=True).start()

    def _dispatch(self, level: str, text: str) -> None:
        msg = f"NB3 bot [{level}] {text}"
        token = os.environ.get(self.cfg.telegram_bot_token_env, "")
        if token and self.cfg.telegram_chat_id:
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": self.cfg.telegram_chat_id, "text": msg}, timeout=10)
            except requests.RequestException as e:
                self.audit.log("alert_channel_failed", "WARN", channel="telegram", error=str(e))
        if self.cfg.webhook_url:
            try:
                requests.post(self.cfg.webhook_url, json={"level": level, "text": msg}, timeout=10)
            except requests.RequestException as e:
                self.audit.log("alert_channel_failed", "WARN", channel="webhook", error=str(e))
        if self.cfg.email_smtp_host and self.cfg.email_to:
            try:
                m = EmailMessage()
                m["Subject"], m["To"] = f"NB3 bot {level}", self.cfg.email_to
                user = os.environ.get(self.cfg.email_user_env, "")
                m["From"] = user or self.cfg.email_to
                m.set_content(msg)
                with smtplib.SMTP_SSL(self.cfg.email_smtp_host, 465, timeout=15) as s:
                    if user:
                        s.login(user, os.environ.get(self.cfg.email_password_env, ""))
                    s.send_message(m)
            except Exception as e:  # noqa: BLE001 - any mail failure is logged, never raised
                self.audit.log("alert_channel_failed", "WARN", channel="email", error=str(e))
