from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EmailItem:
    message_id: str
    subject: str
    sender: str
    received_at: str
    snippet: str


@dataclass(slots=True)
class JiraTicket:
    key: str
    summary: str
    status: str
    priority: str
    issue_type: str
    url: str
