from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from agent.asahio_agent import AsahioTicketExplainer
from .config import Settings
from .jira_client import JiraClient
from .models import ExecutionRequestResult, ImplementationResult, JiraComment, TicketExplanation


APPROVAL_PATTERN = re.compile(
    r"(?:this looks good[\s,;:-]*)?proceed with(?: the)? implementation|this looks good.*proceed with(?: the)? implementation",
    re.IGNORECASE,
)
IMPLEMENTATION_STORY_PATTERN = re.compile(r"Implementation story created:\s*([A-Z][A-Z0-9_]+-\d+)")
IMPLEMENTATION_DIR = Path(__file__).resolve().parent.parent / "generated_implementation"
WORK_DIR = Path(__file__).resolve().parent.parent / "generated_work"
AGENT_ANALYSIS_MARKER = "[jira-bot-analysis]"
AGENT_REVIEW_MARKER = "[jira-bot-review]"
AGENT_IMPLEMENTATION_MARKER = "[jira-bot-implementation]"
AGENT_TASK_MARKER = "[jira-bot-task]"
AGENT_WORK_MARKER = "[jira-bot-work]"
EXECUTION_REQUEST_PATTERN = re.compile(
    r"create (?:a |new )?(?:ticket|story|task)|build .*code|write .*code|implement .*code|cdktf|starter template|generate .*code",
    re.IGNORECASE,
)


class MailJiraBot:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jira_client = JiraClient(
            base_url=settings.jira_base_url,
            email=settings.jira_email,
            api_token=settings.jira_api_token,
            verify_ssl=settings.jira_verify_ssl,
        )

    def collect(self, ticket_limit: int = 10, ticket_key: str | None = None) -> dict[str, object]:
        if ticket_key:
            tickets = [self._jira_client.get_ticket(ticket_key)]
        else:
            tickets = self._jira_client.get_assigned_tickets(self._settings.jira_jql, limit=ticket_limit)
        return {
            "tickets": [asdict(ticket) for ticket in tickets],
        }

    def explain_and_update(
        self,
        ticket_limit: int = 10,
        dry_run: bool = False,
        ticket_key: str | None = None,
    ) -> dict[str, object]:
        snapshot = self.collect(ticket_limit=ticket_limit, ticket_key=ticket_key)
        explainer = AsahioTicketExplainer(self._settings)
        updates: list[dict[str, object]] = []

        for ticket in snapshot["tickets"]:
            explanation = explainer.explain_ticket(ticket=ticket, snapshot=snapshot)
            comment_posted = False
            if explanation and not dry_run:
                self._jira_client.add_comment(ticket["key"], explanation)
                comment_posted = True
            updates.append(
                asdict(
                    TicketExplanation(
                        ticket_key=ticket["key"],
                        explanation=explanation,
                        comment_posted=comment_posted,
                    )
                )
            )

        return {
            "agent": {
                "id": explainer.agent_id,
                "name": explainer.agent_name,
            },
            "tickets": snapshot["tickets"],
            "updates": updates,
            "dry_run": dry_run,
        }

    def render_summary(self, ticket_limit: int = 10, ticket_key: str | None = None) -> str:
        snapshot = self.collect(ticket_limit=ticket_limit, ticket_key=ticket_key)
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

    def render_json(self, ticket_limit: int = 10, ticket_key: str | None = None) -> str:
        return json.dumps(
            self.collect(ticket_limit=ticket_limit, ticket_key=ticket_key),
            indent=2,
        )

    def render_explanations(
        self,
        ticket_limit: int = 10,
        dry_run: bool = False,
        ticket_key: str | None = None,
    ) -> str:
        payload = self.explain_and_update(ticket_limit=ticket_limit, dry_run=dry_run, ticket_key=ticket_key)
        lines = [
            f"ASAHIO agent: {payload['agent']['name']} ({payload['agent']['id']})",
            "",
        ]
        for update in payload["updates"]:
            status = "posted" if update["comment_posted"] else "generated"
            lines.append(f"{update['ticket_key']}: {status}")
            lines.append(update["explanation"] or "No explanation generated.")
            lines.append("")

        if not lines:
            lines.append("No assigned tickets found.")

        return "\n".join(lines).rstrip()

    def process_implementation_approvals(
        self,
        ticket_limit: int = 10,
        dry_run: bool = False,
        ticket_key: str | None = None,
    ) -> dict[str, object]:
        snapshot = self.collect(ticket_limit=ticket_limit, ticket_key=ticket_key)
        explainer = AsahioTicketExplainer(self._settings)
        results: list[dict[str, object]] = []

        for ticket in snapshot["tickets"]:
            comments = self._jira_client.get_ticket_comments(ticket["key"])
            results.append(self._process_single_ticket_implementation(ticket, comments, explainer, dry_run=dry_run))

        return {
            "agent": {
                "id": explainer.agent_id,
                "name": explainer.agent_name,
            },
            "tickets": snapshot["tickets"],
            "results": results,
            "dry_run": dry_run,
        }

    def run_ticket_feedback_loop(
        self,
        ticket_limit: int = 10,
        dry_run: bool = False,
        ticket_key: str | None = None,
    ) -> dict[str, object]:
        snapshot = self.collect(ticket_limit=ticket_limit, ticket_key=ticket_key)
        explainer = AsahioTicketExplainer(self._settings)
        results: list[dict[str, object]] = []

        for ticket in snapshot["tickets"]:
            comments = self._jira_client.get_ticket_comments(ticket["key"])
            latest_agent_comment = _find_latest_agent_feedback(comments)
            approval_comment = _find_approval_comment(comments)
            execution_request = _find_latest_execution_request(comments, latest_agent_comment)

            if approval_comment is not None:
                results.append(self._process_single_ticket_implementation(ticket, comments, explainer, dry_run=dry_run))
                continue

            if execution_request is not None:
                results.append(self._process_execution_request(ticket, comments, execution_request, explainer, dry_run=dry_run))
                continue

            if latest_agent_comment is None:
                explanation = explainer.explain_ticket(ticket=ticket, snapshot=snapshot)
                if explanation and not dry_run:
                    self._jira_client.add_comment(
                        ticket["key"],
                        _format_agent_comment(marker=AGENT_ANALYSIS_MARKER, body=explanation),
                    )
                results.append(
                    {
                        "source_ticket_key": ticket["key"],
                        "status": "initial-analysis" if explanation else "no-analysis",
                        "story_key": None,
                        "story_url": None,
                        "artifact_path": None,
                    }
                )
                continue

            review_comment = _find_latest_unaddressed_review(comments, latest_agent_comment)
            if review_comment is not None:
                revised_comment = explainer.revise_ticket_comment(
                    ticket=ticket,
                    snapshot=snapshot,
                    current_comment=_strip_agent_metadata(latest_agent_comment.body),
                    review_comment=review_comment.body,
                    existing_comments=[comment.body for comment in comments],
                )
                if revised_comment and _normalize_comment_text(revised_comment) == _normalize_comment_text(_strip_agent_metadata(latest_agent_comment.body)):
                    results.append(
                        {
                            "source_ticket_key": ticket["key"],
                            "status": "review-no-change",
                            "story_key": None,
                            "story_url": None,
                            "artifact_path": None,
                        }
                    )
                    continue
                if revised_comment and not dry_run:
                    self._jira_client.add_comment(
                        ticket["key"],
                        _format_agent_comment(
                            marker=AGENT_REVIEW_MARKER,
                            body=revised_comment,
                            source_comment_id=review_comment.comment_id,
                        ),
                    )
                results.append(
                    {
                        "source_ticket_key": ticket["key"],
                        "status": "review-addressed" if revised_comment else "review-detected",
                        "story_key": None,
                        "story_url": None,
                        "artifact_path": None,
                    }
                )
                continue

            results.append(
                {
                    "source_ticket_key": ticket["key"],
                    "status": "waiting-for-review-or-approval",
                    "story_key": None,
                    "story_url": None,
                    "artifact_path": None,
                }
            )

        return {
            "agent": {"id": explainer.agent_id, "name": explainer.agent_name},
            "results": results,
            "dry_run": dry_run,
        }

    def render_ticket_feedback_loop(
        self,
        ticket_limit: int = 10,
        dry_run: bool = False,
        ticket_key: str | None = None,
    ) -> str:
        payload = self.run_ticket_feedback_loop(ticket_limit=ticket_limit, dry_run=dry_run, ticket_key=ticket_key)
        lines = [f"ASAHIO agent: {payload['agent']['name']} ({payload['agent']['id']})", ""]
        for result in payload["results"]:
            lines.append(f"{result['source_ticket_key']}: {result['status']}")
            if result.get("story_key"):
                lines.append(f"Story: {result['story_key']} | {result['story_url']}")
            if result.get("artifact_path"):
                lines.append(f"Implementation brief: {result['artifact_path']}")
            lines.append("")

        if len(lines) == 2:
            lines.append("No assigned tickets found.")

        return "\n".join(lines).rstrip()

    def _process_execution_request(
        self,
        ticket: dict[str, object],
        comments: list[JiraComment],
        execution_request: JiraComment,
        explainer: AsahioTicketExplainer,
        dry_run: bool,
    ) -> dict[str, object]:
        tasks = explainer.plan_execution_tasks(
            ticket=ticket,
            request_comment=execution_request.body,
            existing_comments=[comment.body for comment in comments],
        )
        if not tasks:
            return asdict(
                ExecutionRequestResult(
                    source_ticket_key=ticket["key"],
                    source_comment_id=execution_request.comment_id,
                    status="execution-no-tasks",
                    created_ticket_keys=[],
                    artifact_paths=[],
                )
            )

        created_ticket_keys: list[str] = []
        artifact_paths: list[str] = []

        if not dry_run:
            for task in tasks:
                story = self._jira_client.create_story(
                    source_issue_key=ticket["key"],
                    summary=task["summary"],
                    description=task["description"],
                )
                created_ticket_keys.append(story.key)
                artifact_paths.append(str(self._write_named_artifact(story.key, task["artifact_file_name"], task["artifact_content"])))

            self._jira_client.add_comment(
                ticket["key"],
                _format_agent_comment(
                    marker=AGENT_TASK_MARKER,
                    body=(
                        "Execution tasks created:\n"
                        + "\n".join(f"- {ticket_key}" for ticket_key in created_ticket_keys)
                    ),
                    source_comment_id=execution_request.comment_id,
                ),
            )

        return asdict(
            ExecutionRequestResult(
                source_ticket_key=ticket["key"],
                source_comment_id=execution_request.comment_id,
                status="execution-planned" if dry_run else "execution-created",
                created_ticket_keys=created_ticket_keys,
                artifact_paths=artifact_paths,
            )
        )

    def _process_single_ticket_implementation(
        self,
        ticket: dict[str, object],
        comments: list[JiraComment],
        explainer: AsahioTicketExplainer,
        dry_run: bool,
    ) -> dict[str, object]:
        approval_comment = _find_approval_comment(comments)
        if approval_comment is None:
            return asdict(
                ImplementationResult(
                    source_ticket_key=ticket["key"],
                    approval_detected=False,
                    story_created=False,
                    story_key=None,
                    story_url=None,
                    artifact_path=None,
                    status="no-approval",
                )
            )

        existing_story_key = _find_existing_story_key(comments)
        existing_story_url = None
        story_created = False

        package = explainer.generate_implementation_package(
            ticket=ticket,
            approval_comment=approval_comment.body,
            existing_comments=[comment.body for comment in comments],
        )

        if existing_story_key is not None:
            story_key = existing_story_key
            existing_story_url = f"{self._settings.jira_base_url}/browse/{story_key}"
            status = "story-exists"
        elif dry_run:
            story_key = None
            status = "approved-preview"
        else:
            story = self._jira_client.create_story(
                source_issue_key=ticket["key"],
                summary=package["story_summary"],
                description=package["story_description"],
            )
            story_key = story.key
            existing_story_url = story.url
            story_created = True
            self._jira_client.add_comment(
                ticket["key"],
                _format_agent_comment(
                    marker=AGENT_IMPLEMENTATION_MARKER,
                    body=f"Implementation story created: {story.key}\n{story.url}",
                    source_comment_id=approval_comment.comment_id,
                ),
            )
            status = "story-created"

        artifact_path = None
        if not dry_run:
            artifact_path = str(
                self._write_implementation_brief(
                    source_ticket=ticket,
                    story_key=story_key or ticket["key"],
                    package=package,
                    approval_comment=approval_comment.body,
                )
            )

        return asdict(
            ImplementationResult(
                source_ticket_key=ticket["key"],
                approval_detected=True,
                story_created=story_created,
                story_key=story_key,
                story_url=existing_story_url,
                artifact_path=artifact_path,
                status=status,
            )
        )

    def render_implementation_approvals(
        self,
        ticket_limit: int = 10,
        dry_run: bool = False,
        ticket_key: str | None = None,
    ) -> str:
        payload = self.process_implementation_approvals(ticket_limit=ticket_limit, dry_run=dry_run, ticket_key=ticket_key)
        lines = [
            f"ASAHIO agent: {payload['agent']['name']} ({payload['agent']['id']})",
            "",
        ]
        for result in payload["results"]:
            lines.append(f"{result['source_ticket_key']}: {result['status']}")
            if result["story_key"]:
                lines.append(f"Story: {result['story_key']} | {result['story_url']}")
            if result["artifact_path"]:
                lines.append(f"Implementation brief: {result['artifact_path']}")
            lines.append("")

        if len(lines) == 2:
            lines.append("No assigned tickets found.")

        return "\n".join(lines).rstrip()

    def _write_implementation_brief(
        self,
        source_ticket: dict[str, object],
        story_key: str,
        package: dict[str, str],
        approval_comment: str,
    ) -> Path:
        IMPLEMENTATION_DIR.mkdir(parents=True, exist_ok=True)
        artifact_path = IMPLEMENTATION_DIR / f"{story_key}.md"
        artifact_path.write_text(
            "\n".join(
                [
                    f"# {package['story_summary']}",
                    "",
                    f"Source ticket: {source_ticket['key']}",
                    f"Approval comment: {approval_comment}",
                    "",
                    "## Story Description",
                    package["story_description"],
                    "",
                    "## Implementation Brief",
                    package["implementation_brief"],
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return artifact_path

    def _write_named_artifact(self, story_key: str, file_name: str, content: str) -> Path:
        IMPLEMENTATION_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", file_name).strip("._") or "artifact.md"
        artifact_path = IMPLEMENTATION_DIR / f"{story_key}_{safe_name}"
        artifact_path.write_text(content, encoding="utf-8")
        return artifact_path

    def _write_work_artifact(self, ticket_key: str, file_name: str, content: str) -> Path:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", file_name).strip("._") or "artifact.md"
        artifact_path = WORK_DIR / f"{ticket_key}_{safe_name}"
        artifact_path.write_text(content, encoding="utf-8")
        return artifact_path

    def _deliver_ticket_work(
        self,
        ticket: dict[str, object],
        comments: list[JiraComment],
        explainer: AsahioTicketExplainer,
        dry_run: bool,
    ) -> dict[str, object]:
        package = explainer.plan_ticket_work(ticket=ticket, existing_comments=[comment.body for comment in comments])
        artifact_paths: list[str] = []
        if not dry_run:
            for artifact in package["artifacts"]:
                artifact_paths.append(str(self._write_work_artifact(ticket["key"], artifact["file_name"], artifact["content"])))

            comment_body = package["update_comment"].strip()
            if artifact_paths:
                comment_body = "\n\n".join(
                    [
                        comment_body,
                        "Artifacts created:",
                        "\n".join(f"- {path}" for path in artifact_paths),
                    ]
                )

            self._jira_client.add_comment(
                ticket["key"],
                _format_agent_comment(marker=AGENT_WORK_MARKER, body=comment_body),
            )

        return {
            "source_ticket_key": ticket["key"],
            "status": "work-planned" if dry_run else "work-delivered",
            "story_key": None,
            "story_url": None,
            "artifact_path": None,
            "artifact_paths": artifact_paths,
        }

    def run_employee_ticket_cycle(self, ticket_key: str, dry_run: bool = False) -> dict[str, object]:
        snapshot = self.collect(ticket_limit=1, ticket_key=ticket_key)
        explainer = AsahioTicketExplainer(self._settings)
        results: list[dict[str, object]] = []

        for ticket in snapshot["tickets"]:
            comments = self._jira_client.get_ticket_comments(ticket["key"])
            latest_work_comment = _find_latest_work_comment(comments)
            approval_comment = _find_approval_comment(comments)

            if approval_comment is not None and latest_work_comment is not None:
                results.append(self._process_single_ticket_implementation(ticket, comments, explainer, dry_run=dry_run))
                continue

            if latest_work_comment is None:
                results.append(self._deliver_ticket_work(ticket, comments, explainer, dry_run=dry_run))
                continue

            review_comment = _find_latest_unaddressed_review(comments, latest_work_comment)
            if review_comment is not None:
                revised_comment = explainer.revise_ticket_comment(
                    ticket=ticket,
                    snapshot=snapshot,
                    current_comment=_strip_agent_metadata(latest_work_comment.body),
                    review_comment=review_comment.body,
                    existing_comments=[comment.body for comment in comments],
                )
                if revised_comment and not dry_run:
                    self._jira_client.add_comment(
                        ticket["key"],
                        _format_agent_comment(
                            marker=AGENT_WORK_MARKER,
                            body=revised_comment,
                            source_comment_id=review_comment.comment_id,
                        ),
                    )
                results.append(
                    {
                        "source_ticket_key": ticket["key"],
                        "status": "work-updated" if revised_comment else "review-detected",
                        "story_key": None,
                        "story_url": None,
                        "artifact_path": None,
                        "artifact_paths": [],
                    }
                )
                continue

            results.append(
                {
                    "source_ticket_key": ticket["key"],
                    "status": "waiting-for-approval",
                    "story_key": None,
                    "story_url": None,
                    "artifact_path": None,
                    "artifact_paths": [],
                }
            )

        return {
            "agent": {"id": explainer.agent_id, "name": explainer.agent_name},
            "results": results,
            "dry_run": dry_run,
        }

    def run_autonomous_ticket(self, ticket_key: str, dry_run: bool = False) -> str:
        payload = self.run_employee_ticket_cycle(ticket_key=ticket_key, dry_run=dry_run)
        result = payload["results"][0] if payload["results"] else {
            "source_ticket_key": ticket_key,
            "status": "not-found",
        }
        lines = [
            f"ASAHIO agent: {payload['agent']['name']} ({payload['agent']['id']})",
            f"Ticket: {result['source_ticket_key']}",
            f"Decision: {result['status']}",
        ]
        if result.get("story_key"):
            lines.append(f"Story: {result['story_key']} | {result['story_url']}")
        if result.get("artifact_path"):
            lines.append(f"Implementation brief: {result['artifact_path']}")
        if result.get("artifact_paths"):
            lines.append("Work artifacts:")
            for artifact_path in result["artifact_paths"]:
                lines.append(f"- {artifact_path}")
        return "\n".join(lines)

    def run_autonomous_worker(
        self,
        poll_seconds: int | None = None,
        ticket_limit: int | None = None,
        once: bool = False,
        dry_run: bool = False,
    ) -> str:
        effective_poll_seconds = poll_seconds or self._settings.autonomous_poll_seconds
        effective_ticket_limit = ticket_limit or self._settings.autonomous_ticket_limit
        cycles: list[str] = []

        while True:
            snapshot = self.collect(ticket_limit=effective_ticket_limit)
            cycle_lines = [f"Worker cycle: {len(snapshot['tickets'])} ticket(s)"]
            for ticket in snapshot["tickets"]:
                cycle_lines.append(self.run_autonomous_ticket(ticket_key=ticket["key"], dry_run=dry_run))
                cycle_lines.append("")

            cycles.append("\n".join(cycle_lines).rstrip())
            if once:
                break

            time.sleep(effective_poll_seconds)

        return "\n\n".join(cycles).rstrip()


def _find_approval_comment(comments: list[str]) -> str | None:
    for comment in reversed(comments):
        if APPROVAL_PATTERN.search(comment.body) and not _is_agent_managed_comment(comment):
            return comment
    return None


def _find_existing_story_key(comments: list[JiraComment]) -> str | None:
    for comment in comments:
        match = IMPLEMENTATION_STORY_PATTERN.search(comment.body)
        if match:
            return match.group(1)
    return None


def _find_latest_agent_feedback(comments: list[JiraComment]) -> JiraComment | None:
    for comment in reversed(comments):
        if _is_agent_managed_comment(comment):
            return comment
    return None


def _find_latest_work_comment(comments: list[JiraComment]) -> JiraComment | None:
    for comment in reversed(comments):
        if comment.body.startswith(AGENT_WORK_MARKER) or comment.body.startswith(AGENT_REVIEW_MARKER):
            return comment
    return None


def _find_latest_unaddressed_review(
    comments: list[JiraComment],
    latest_agent_comment: JiraComment,
) -> JiraComment | None:
    for comment in reversed(comments):
        if comment.comment_id == latest_agent_comment.comment_id:
            break
        if _is_agent_managed_comment(comment):
            continue
        if APPROVAL_PATTERN.search(comment.body):
            continue
        if _is_comment_addressed(comments, comment.comment_id):
            continue
        if comment.body.strip():
            return comment
    return None


def _find_latest_execution_request(
    comments: list[JiraComment],
    latest_agent_comment: JiraComment | None,
) -> JiraComment | None:
    stop_comment_id = latest_agent_comment.comment_id if latest_agent_comment else None
    for comment in reversed(comments):
        if stop_comment_id and comment.comment_id == stop_comment_id:
            break
        if _is_agent_managed_comment(comment):
            continue
        if _is_comment_addressed(comments, comment.comment_id):
            continue
        if EXECUTION_REQUEST_PATTERN.search(comment.body):
            return comment
    return None


def _is_agent_managed_comment(comment: JiraComment) -> bool:
    return (
        comment.body.startswith(AGENT_ANALYSIS_MARKER)
        or comment.body.startswith(AGENT_REVIEW_MARKER)
        or comment.body.startswith(AGENT_IMPLEMENTATION_MARKER)
        or comment.body.startswith(AGENT_TASK_MARKER)
        or comment.body.startswith(AGENT_WORK_MARKER)
    )


def _is_comment_addressed(comments: list[JiraComment], source_comment_id: str) -> bool:
    marker = f"source-comment-id: {source_comment_id}"
    for comment in comments:
        if _is_agent_managed_comment(comment) and marker in comment.body:
            return True
    return False


def _format_agent_comment(marker: str, body: str, source_comment_id: str | None = None) -> str:
    lines = [marker]
    if source_comment_id:
        lines.append(f"source-comment-id: {source_comment_id}")
    lines.append("")
    lines.append(body.strip())
    return "\n".join(lines).strip()


def _strip_agent_metadata(body: str) -> str:
    lines = body.splitlines()
    filtered: list[str] = []
    skipping_header = True
    for line in lines:
        if skipping_header and (line.startswith("[jira-bot-") or line.startswith("source-comment-id:")):
            continue
        if skipping_header and not line.strip():
            continue
        skipping_header = False
        filtered.append(line)
    return "\n".join(filtered).strip()


def _normalize_comment_text(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip().casefold()
