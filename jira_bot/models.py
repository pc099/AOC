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
    description: str
    url: str


@dataclass(slots=True)
class TicketExplanation:
    ticket_key: str
    explanation: str
    comment_posted: bool


@dataclass(slots=True)
class JiraIssueReference:
    key: str
    url: str


@dataclass(slots=True)
class JiraComment:
    comment_id: str
    body: str
    author_name: str
    created_at: str


@dataclass(slots=True)
class ImplementationResult:
    source_ticket_key: str
    approval_detected: bool
    story_created: bool
    story_key: str | None
    story_url: str | None
    artifact_path: str | None
    status: str


@dataclass(slots=True)
class ExecutionTaskPlan:
    summary: str
    description: str
    artifact_file_name: str
    artifact_content: str


@dataclass(slots=True)
class ExecutionRequestResult:
    source_ticket_key: str
    source_comment_id: str | None
    status: str
    created_ticket_keys: list[str]
    artifact_paths: list[str]
