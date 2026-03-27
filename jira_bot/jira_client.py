from __future__ import annotations

from typing import Any

import requests

from .models import JiraComment, JiraIssueReference, JiraTicket


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
                "fields": "summary,status,priority,issuetype,description",
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
                    description=_extract_jira_text(fields.get("description")),
                    url=f"{self._base_url}/browse/{key}",
                )
            )
        return tickets

    def get_ticket(self, issue_key: str) -> JiraTicket:
        response = self._session.get(
            f"{self._base_url}/rest/api/3/issue/{issue_key}",
            params={"fields": "summary,status,priority,issuetype,description"},
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        response.raise_for_status()
        issue: dict[str, Any] = response.json()
        fields = issue.get("fields", {})
        key = issue.get("key", issue_key)
        return JiraTicket(
            key=key,
            summary=fields.get("summary", ""),
            status=(fields.get("status") or {}).get("name", "Unknown"),
            priority=(fields.get("priority") or {}).get("name", "Unknown"),
            issue_type=(fields.get("issuetype") or {}).get("name", "Unknown"),
            description=_extract_jira_text(fields.get("description")),
            url=f"{self._base_url}/browse/{key}",
        )

    def add_comment(self, issue_key: str, comment: str) -> None:
        response = self._session.post(
            f"{self._base_url}/rest/api/2/issue/{issue_key}/comment",
            json={"body": comment},
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        response.raise_for_status()

    def get_ticket_comments(self, issue_key: str, limit: int = 50) -> list[JiraComment]:
        response = self._session.get(
            f"{self._base_url}/rest/api/3/issue/{issue_key}/comment",
            params={"maxResults": limit},
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

        comments: list[JiraComment] = []
        for comment in payload.get("comments", []):
            body = _extract_jira_text(comment.get("body"))
            if body:
                comments.append(
                    JiraComment(
                        comment_id=str(comment.get("id", "")),
                        body=body,
                        author_name=((comment.get("author") or {}).get("displayName") or "Unknown"),
                        created_at=str(comment.get("created", "")),
                    )
                )
        return comments

    def create_story(self, source_issue_key: str, summary: str, description: str) -> JiraIssueReference:
        project_key = source_issue_key.split("-", 1)[0]
        response = self._session.post(
            f"{self._base_url}/rest/api/3/issue",
            json={
                "fields": {
                    "project": {"key": project_key},
                    "summary": summary,
                    "issuetype": {"name": "Story"},
                    "description": _to_adf(description),
                }
            },
            verify=self._verify_ssl,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        key = payload["key"]
        return JiraIssueReference(key=key, url=f"{self._base_url}/browse/{key}")


def _extract_jira_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_jira_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        if "text" in value and isinstance(value["text"], str):
            return value["text"].strip()
        parts = [_extract_jira_text(item) for item in value.get("content", [])]
        return "\n".join(part for part in parts if part).strip()
    return ""


def _to_adf(text: str) -> dict[str, Any]:
    paragraphs = []
    for block in text.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "\n".join(lines),
                    }
                ],
            }
        )

    if not paragraphs:
        paragraphs.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text.strip() or "No description provided."}],
            }
        )

    return {"type": "doc", "version": 1, "content": paragraphs}
