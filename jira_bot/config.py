from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
PACKAGE_ENV_FILE = Path(__file__).resolve().parent / ".env"

load_dotenv(ROOT_ENV_FILE)
load_dotenv(PACKAGE_ENV_FILE)


@dataclass(slots=True)
class Settings:
    jira_base_url: str
    jira_email: str
    jira_api_token: str
    jira_jql: str
    jira_verify_ssl: bool
    autonomous_poll_seconds: int
    autonomous_ticket_limit: int
    asahio_api_key: str
    asahio_verify_ssl: bool
    asahio_model: str
    asahio_routing_mode: str
    asahio_intervention_mode: str

    @classmethod
    def from_env(cls) -> "Settings":
        jira_base_url = os.getenv("JIRA_BASE_URL", "").rstrip("/")
        jira_email = os.getenv("JIRA_EMAIL", "")
        jira_api_token = os.getenv("JIRA_API_TOKEN", "")
        jira_jql = os.getenv(
            "JIRA_JQL",
            "assignee=currentUser() AND resolution = Unresolved ORDER BY updated DESC",
        )
        jira_verify_ssl = os.getenv("JIRA_VERIFY_SSL", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        autonomous_poll_seconds = int(os.getenv("AUTONOMOUS_POLL_SECONDS", "300"))
        autonomous_ticket_limit = int(os.getenv("AUTONOMOUS_TICKET_LIMIT", "10"))
        asahio_api_key = os.getenv("ASAHIO_API_KEY", "")
        asahio_verify_ssl = os.getenv("ASAHIO_VERIFY_SSL", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        asahio_model = os.getenv("ASAHIO_MODEL", "gpt-4o")
        asahio_routing_mode = os.getenv("ASAHIO_ROUTING_MODE", "AUTO")
        asahio_intervention_mode = os.getenv("ASAHIO_INTERVENTION_MODE", "ASSISTED")
        return cls(
            jira_base_url=jira_base_url,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
            jira_jql=jira_jql,
            jira_verify_ssl=jira_verify_ssl,
            autonomous_poll_seconds=autonomous_poll_seconds,
            autonomous_ticket_limit=autonomous_ticket_limit,
            asahio_api_key=asahio_api_key,
            asahio_verify_ssl=asahio_verify_ssl,
            asahio_model=asahio_model,
            asahio_routing_mode=asahio_routing_mode,
            asahio_intervention_mode=asahio_intervention_mode,
        )

    def validate(self, require_asahio: bool = False) -> None:
        missing_values: list[str] = []
        if not self.jira_base_url:
            missing_values.append("JIRA_BASE_URL")
        if not self.jira_email:
            missing_values.append("JIRA_EMAIL")
        if not self.jira_api_token:
            missing_values.append("JIRA_API_TOKEN")
        if require_asahio and not self.asahio_api_key:
            missing_values.append("ASAHIO_API_KEY")

        if missing_values:
            raise ValueError("Missing configuration: " + ", ".join(missing_values))
