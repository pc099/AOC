from __future__ import annotations

from typing import Any

import requests

from .models import JiraTicket


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, timeout: int = 30, verify_ssl: bool = True) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.auth = (email, api_token)
        self._session.headers.update({"Accept": "application/json"})

    def get_assigned_tickets(self, jql: str, limit: int = 10) -> list[JiraTicket]:
        response = self._session.get(
            f"{self._base_url}/rest/api/3/search/jql",
            params={
                "jql": jql,
                "maxResults": limit,
                "fields": "summary,status,priority,issuetype",
            },
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        issues = payload.get("issues", [])

        tickets: list[JiraTicket] = []
        for issue in issues:
            fields = issue.get("fields", {})
            key = issue.get("key", "")
            tickets.append(
                JiraTicket(
                    key=key,
                    summary=fields.get("summary", ""),
                    status=(fields.get("status") or {}).get("name", "Unknown"),
                    priority=(fields.get("priority") or {}).get("name", "Unknown"),
                    issue_type=(fields.get("issuetype") or {}).get("name", "Unknown"),
                    url=f"{self._base_url}/browse/{key}",
                )
            )
        return tickets
