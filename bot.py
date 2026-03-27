from __future__ import annotations

import json
from dataclasses import asdict

from .config import Settings
from .jira_client import JiraClient


class MailJiraBot:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jira_client = JiraClient(
            base_url=settings.jira_base_url,
            email=settings.jira_email,
            api_token=settings.jira_api_token,
            verify_ssl=settings.jira_verify_ssl,
        )

    def collect(self, ticket_limit: int = 10) -> dict[str, object]:
        tickets = self._jira_client.get_assigned_tickets(self._settings.jira_jql, limit=ticket_limit)
        return {
            "tickets": [asdict(ticket) for ticket in tickets],
        }

    def render_summary(self, ticket_limit: int = 10) -> str:
        snapshot = self.collect(ticket_limit=ticket_limit)
        ticket_lines = ["Assigned Jira tickets:"]
        for index, ticket in enumerate(snapshot["tickets"], start=1):
            ticket_lines.append(
                f"{index}. {ticket['key']} [{ticket['status']}] {ticket['summary']}"
            )
            ticket_lines.append(
                f"   Type: {ticket['issue_type']} | Priority: {ticket['priority']} | {ticket['url']}"
            )

        if len(snapshot["tickets"]) == 0:
            ticket_lines.append("No assigned tickets found.")

        return "\n".join(ticket_lines)

    def render_json(self, ticket_limit: int = 10) -> str:
        return json.dumps(
            self.collect(ticket_limit=ticket_limit),
            indent=2,
        )
