"""Pluggable notification system — fires when research jobs complete or fail.

Add providers by subclassing NotificationProvider and registering them with
the global `notification_manager`.

Bundled providers:
  InAppProvider   — stores notifications in memory; served via /api/notifications
  (stubs)         — Discord webhook, Telegram, Email (implement and register)
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Event types ───────────────────────────────────────────────────────────────

JOB_DONE   = "job_done"
JOB_FAILED = "job_failed"
JOB_START  = "job_start"


# ── Base provider ─────────────────────────────────────────────────────────────

@dataclass
class NotificationEvent:
    event_type: str
    title: str
    body: str
    job_id: str = ""
    session_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    extra: dict = field(default_factory=dict)


class NotificationProvider(ABC):
    """Abstract base — implement send() to add a new channel."""

    @abstractmethod
    def send(self, event: NotificationEvent) -> None: ...


# ── In-app provider (always enabled) ─────────────────────────────────────────

class InAppProvider(NotificationProvider):
    """Keeps the last 200 notifications in memory for the browser UI."""

    def __init__(self, maxlen: int = 200) -> None:
        self._events: deque[NotificationEvent] = deque(maxlen=maxlen)
        self._lock   = threading.Lock()

    def send(self, event: NotificationEvent) -> None:
        with self._lock:
            self._events.appendleft(event)

    def list(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "event_type": e.event_type,
                    "title":      e.title,
                    "body":       e.body,
                    "job_id":     e.job_id,
                    "session_id": e.session_id,
                    "created_at": e.created_at,
                }
                for e in self._events
            ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# ── Stub providers (wire up externally) ──────────────────────────────────────

class DiscordWebhookProvider(NotificationProvider):
    """Post a message to a Discord webhook URL."""

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    def send(self, event: NotificationEvent) -> None:
        try:
            import requests
            payload = {"content": f"**{event.title}**\n{event.body}"}
            requests.post(self._url, json=payload, timeout=5)
        except Exception:
            pass


class TelegramProvider(NotificationProvider):
    """Send a Telegram message via bot API."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token   = token
        self._chat_id = chat_id

    def send(self, event: NotificationEvent) -> None:
        try:
            import requests
            url  = f"https://api.telegram.org/bot{self._token}/sendMessage"
            text = f"*{event.title}*\n{event.body}"
            requests.post(url, json={"chat_id": self._chat_id, "text": text,
                                     "parse_mode": "Markdown"}, timeout=5)
        except Exception:
            pass


# ── Manager ───────────────────────────────────────────────────────────────────

class NotificationManager:
    """Dispatch events to all registered providers."""

    def __init__(self) -> None:
        self._providers: list[NotificationProvider] = []
        self.in_app = InAppProvider()
        self._providers.append(self.in_app)

    def register(self, provider: NotificationProvider) -> None:
        self._providers.append(provider)

    def notify(
        self,
        event_type: str,
        title: str,
        body: str,
        job_id: str = "",
        session_id: str = "",
        **extra: Any,
    ) -> None:
        event = NotificationEvent(
            event_type=event_type,
            title=title,
            body=body,
            job_id=job_id,
            session_id=session_id,
            extra=extra,
        )
        for provider in self._providers:
            try:
                provider.send(event)
            except Exception:
                pass


# ── Singleton ─────────────────────────────────────────────────────────────────

notification_manager = NotificationManager()
