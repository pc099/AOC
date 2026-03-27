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
        return cls(
            jira_base_url=jira_base_url,
            jira_email=jira_email,
            jira_api_token=jira_api_token,
            jira_jql=jira_jql,
            jira_verify_ssl=jira_verify_ssl,
        )

    def validate(self) -> None:
        missing_values: list[str] = []
        if not self.jira_base_url:
            missing_values.append("JIRA_BASE_URL")
        if not self.jira_email:
            missing_values.append("JIRA_EMAIL")
        if not self.jira_api_token:
            missing_values.append("JIRA_API_TOKEN")

        if missing_values:
            raise ValueError("Missing configuration: " + ", ".join(missing_values))
