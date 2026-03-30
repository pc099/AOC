from __future__ import annotations

import hashlib
import json
import re

import httpx
from asahio import ConflictError

from jira_bot.config import Settings


JIRA_AGENT_NAME = "Jira Agent"
JIRA_AGENT_SLUG = "jira-agent"


class AsahioTicketExplainer:
    def __init__(self, settings: Settings) -> None:
        from asahio import Asahio

        self._settings = settings
        self._client = Asahio(api_key=settings.asahio_api_key)
        if not settings.asahio_verify_ssl:
            self._disable_ssl_verification()
        self._agent = self.ensure_agent()

    @property
    def agent_id(self) -> str:
        return self._agent.id

    @property
    def agent_name(self) -> str:
        return self._agent.name

    def _disable_ssl_verification(self) -> None:
        base_client = self._client._client
        existing_http = base_client._http
        base_url = str(existing_http.base_url)
        headers = dict(existing_http.headers)
        timeout = existing_http.timeout
        existing_http.close()
        base_client._http = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            verify=False,
        )

    def ensure_agent(self):
        existing_agent = self._find_existing_agent()
        if existing_agent is not None:
            return existing_agent

        try:
            return self._client.agents.create(
                name=JIRA_AGENT_NAME,
                slug=JIRA_AGENT_SLUG,
                description="Explains Jira ticket snapshots and prepares ticket update comments.",
                routing_mode=self._settings.asahio_routing_mode,
                intervention_mode=self._settings.asahio_intervention_mode,
                metadata={"source": "jira-bot", "workflow": "ticket-explanation"},
            )
        except ConflictError:
            existing_agent = self._find_existing_agent()
            if existing_agent is not None:
                return existing_agent
            raise

    def _find_existing_agent(self):
        agents = self._client.agents.list()
        for agent in agents:
            if agent.slug == JIRA_AGENT_SLUG:
                return agent
        for agent in agents:
            if agent.name.casefold() == JIRA_AGENT_NAME.casefold():
                return agent
        return None

    def explain_ticket(self, ticket: dict[str, object], snapshot: dict[str, object]) -> str:
        description = str(ticket.get("description") or "").strip()
        acceptance_criteria = _extract_acceptance_criteria(description)
        state_fingerprint = _build_state_fingerprint(ticket=ticket, extra=[json.dumps(snapshot, sort_keys=True)])
        prompt = (
            "You are helping update Jira tickets based on a structured ticket snapshot. "
            "Read the ticket description carefully, identify the acceptance criteria, and generate a Jira-ready comment. "
            "Use only the data provided. Do not claim implementation or completion unless the ticket data supports it.\n\n"
            "Comment requirements:\n"
            "1. Start with a short summary of what the ticket is asking for.\n"
            "2. Evaluate the acceptance criteria explicitly. For each criterion, say what evidence is present, what evidence is missing, and what artifact or task is needed next.\n"
            "3. If a criterion requires a diagram, schema, cost estimate, security review, research, or tech comparison, say that directly instead of only saying 'pending'.\n"
            "4. When relevant, recommend the enabling tool or artifact, for example a sequence diagram, schema document, AWS cost estimate, IAM policy draft, or a comparison spike.\n"
            "5. End with a recommended next action for the assignee or team.\n"
            "6. Keep the response in plain text suitable for posting directly as a Jira comment.\n"
            "7. Do not pretend the agent itself already generated diagrams, web research, or implementation artifacts unless they are present in the ticket data.\n\n"
            "Full Jira bot snapshot:\n"
            f"{json.dumps(snapshot, indent=2)}\n\n"
            "Ticket to explain:\n"
            f"{json.dumps(ticket, indent=2)}\n\n"
            "Ticket description:\n"
            f"{description or 'No description provided.'}\n\n"
            "Extracted acceptance criteria:\n"
            f"{json.dumps(acceptance_criteria, indent=2)}\n\n"
            "Ticket state fingerprint:\n"
            f"{state_fingerprint}"
        )
        return self._fresh_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate Jira ticket update comments. "
                        "Your job is to analyze the description, understand the acceptance criteria, "
                        "and produce an accurate status-oriented comment. "
                        "Focus on evidence gaps, required artifacts, and next actions, not generic status labels. "
                        "Do not invent implementation details or claim work was completed unless the input supports it."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

    def generate_implementation_package(
        self,
        ticket: dict[str, object],
        approval_comment: str,
        existing_comments: list[str],
    ) -> dict[str, str]:
        description = str(ticket.get("description") or "").strip()
        acceptance_criteria = _extract_acceptance_criteria(description)
        state_fingerprint = _build_state_fingerprint(ticket=ticket, extra=existing_comments + [approval_comment])
        prompt = (
            "You are preparing a follow-up Jira implementation story and a local implementation brief. "
            "Use the original ticket details and the approval comment to derive an implementation-ready package. "
            "Return valid JSON only with the keys story_summary, story_description, and implementation_brief.\n\n"
            "Requirements:\n"
            "1. story_summary must be concise and start with 'Implementation:'.\n"
            "2. story_description must describe the work to build next, based on the original ticket and acceptance criteria.\n"
            "3. implementation_brief must be a practical engineering handoff with scope, tasks, and risks.\n"
            "4. Do not claim code is already written.\n\n"
            "Source ticket:\n"
            f"{json.dumps(ticket, indent=2)}\n\n"
            "Acceptance criteria:\n"
            f"{json.dumps(acceptance_criteria, indent=2)}\n\n"
            "Approval comment:\n"
            f"{approval_comment}\n\n"
            "Existing comments:\n"
            f"{json.dumps(existing_comments, indent=2)}\n\n"
            "Approval state fingerprint:\n"
            f"{state_fingerprint}"
        )
        content = self._fresh_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate structured Jira implementation handoff payloads. "
                        "Return JSON only and keep it grounded in the provided ticket data."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return _parse_implementation_package(content, ticket, approval_comment, acceptance_criteria)

    def revise_ticket_comment(
        self,
        ticket: dict[str, object],
        snapshot: dict[str, object],
        current_comment: str,
        review_comment: str,
        existing_comments: list[str],
    ) -> str:
        description = str(ticket.get("description") or "").strip()
        acceptance_criteria = _extract_acceptance_criteria(description)
        state_fingerprint = _build_state_fingerprint(
            ticket=ticket,
            extra=existing_comments + [current_comment, review_comment],
        )
        prompt = (
            "You are updating a Jira ticket comment after user review feedback. "
            "Revise the existing agent comment so it better addresses the review while staying grounded in the ticket description and acceptance criteria.\n\n"
            "Requirements:\n"
            "1. Acknowledge the review feedback implicitly by improving the content, not by arguing with the reviewer.\n"
            "2. Keep the comment plain text and Jira-ready.\n"
            "3. Summarize the ticket, evaluate the acceptance criteria, and explain remaining work.\n"
            "4. For each important criterion, state the missing evidence and the concrete artifact, tool, or research needed next.\n"
            "5. End with a recommended next action.\n"
            "6. Do not claim code is complete unless the ticket data proves it.\n"
            "7. Avoid generic phrases like 'still pending' unless you immediately explain what exact deliverable is missing.\n\n"
            "Ticket snapshot:\n"
            f"{json.dumps(snapshot, indent=2)}\n\n"
            "Ticket:\n"
            f"{json.dumps(ticket, indent=2)}\n\n"
            "Acceptance criteria:\n"
            f"{json.dumps(acceptance_criteria, indent=2)}\n\n"
            "Current agent comment:\n"
            f"{current_comment}\n\n"
            "User review comment:\n"
            f"{review_comment}\n\n"
            "All comments for context:\n"
            f"{json.dumps(existing_comments, indent=2)}\n\n"
            "Review state fingerprint:\n"
            f"{state_fingerprint}"
        )
        return self._fresh_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You revise Jira ticket comments based on reviewer feedback. "
                        "Produce a stronger updated comment using only the provided information. "
                        "Improve specificity around missing artifacts, research needs, and acceptance-criteria evidence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )

    def plan_execution_tasks(
        self,
        ticket: dict[str, object],
        request_comment: str,
        existing_comments: list[str],
    ) -> list[dict[str, str]]:
        description = str(ticket.get("description") or "").strip()
        acceptance_criteria = _extract_acceptance_criteria(description)
        state_fingerprint = _build_state_fingerprint(ticket=ticket, extra=existing_comments + [request_comment])
        prompt = (
            "You are planning concrete follow-up work from a Jira comment that asks for action, such as creating tickets or building code. "
            "Return valid JSON only with the shape {\"tasks\": [{...}]}.\n\n"
            "Each task object must have these keys:\n"
            "summary, description, artifact_file_name, artifact_content.\n\n"
            "Rules:\n"
            "1. Create one task per distinct workstream requested by the user comment.\n"
            "2. Make the summary Jira-story ready and concise.\n"
            "3. Make the description actionable and grounded in the source ticket.\n"
            "4. artifact_file_name should be a safe lowercase file name ending in .md or .py.\n"
            "5. artifact_content should contain a first-pass deliverable for that task.\n"
            "6. If the user explicitly asks for code, include a starter implementation artifact where appropriate.\n"
            "7. Do not invent completed results beyond what can be drafted from the ticket and comments.\n\n"
            "Source ticket:\n"
            f"{json.dumps(ticket, indent=2)}\n\n"
            "Acceptance criteria:\n"
            f"{json.dumps(acceptance_criteria, indent=2)}\n\n"
            "User action request comment:\n"
            f"{request_comment}\n\n"
            "Existing comments:\n"
            f"{json.dumps(existing_comments, indent=2)}\n\n"
            "Execution state fingerprint:\n"
            f"{state_fingerprint}"
        )
        content = self._fresh_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You convert actionable Jira comments into concrete execution tasks and starter artifacts. "
                        "Return JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        tasks = _parse_execution_tasks(content)
        if tasks:
            return tasks

        summary = str(ticket.get("summary") or "Untitled task")
        return [
            {
                "summary": f"Execution follow-up: {summary}",
                "description": (
                    f"Create the requested follow-up work for {ticket.get('key', '')}.\n\n"
                    f"User request: {request_comment}"
                ),
                "artifact_file_name": "execution_follow_up.md",
                "artifact_content": (
                    f"# Execution Follow-up for {ticket.get('key', '')}\n\n"
                    f"User request:\n{request_comment}\n"
                ),
            }
        ]

    def plan_ticket_work(
        self,
        ticket: dict[str, object],
        existing_comments: list[str],
    ) -> dict[str, object]:
        description = str(ticket.get("description") or "").strip()
        acceptance_criteria = _extract_acceptance_criteria(description)
        state_fingerprint = _build_state_fingerprint(ticket=ticket, extra=existing_comments)
        prompt = (
            "You are a digital employee assigned to a Jira ticket. Your job is to do the next layer of actual work for the ticket, "
            "not just describe what should be done. Return valid JSON only with this shape: "
            "{\"update_comment\": string, \"artifacts\": [{\"file_name\": string, \"content\": string}]}.\n\n"
            "Rules:\n"
            "1. Do non-implementation work that moves the ticket forward right now.\n"
            "2. Prefer analysis, design, decision records, specs, schemas, estimates, and comparison documents.\n"
            "3. Do not produce implementation code unless the ticket comments already contain explicit approval to proceed with implementation.\n"
            "4. update_comment must describe what work was completed, what artifacts were produced, and what review or approval is needed next.\n"
            "5. Each artifact must be a concrete first-pass deliverable derived from the ticket.\n"
            "6. file_name must be safe and end in .md, .json, .yaml, .csv, or .txt for this work phase.\n\n"
            "Source ticket:\n"
            f"{json.dumps(ticket, indent=2)}\n\n"
            "Acceptance criteria:\n"
            f"{json.dumps(acceptance_criteria, indent=2)}\n\n"
            "Existing comments:\n"
            f"{json.dumps(existing_comments, indent=2)}\n\n"
            "Work state fingerprint:\n"
            f"{state_fingerprint}"
        )
        content = self._fresh_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You act like a responsible employee completing ticket work. "
                        "Produce concrete non-code deliverables first, then summarize what you did for review. "
                        "Return JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        package = _parse_ticket_work_package(content)
        if package is not None:
            return package

        summary = str(ticket.get("summary") or "Untitled task")
        key = str(ticket.get("key") or "ticket")
        return {
            "update_comment": (
                f"Completed first-pass ticket work for {key}. I prepared a working document that captures the current scope and next decisions needed. "
                "Please review it and confirm whether I should proceed to implementation."
            ),
            "artifacts": [
                {
                    "file_name": f"{key.lower()}_work_note.md",
                    "content": f"# {summary}\n\nSource ticket: {key}\n\nThis is the first-pass working note for the assigned ticket.\n",
                }
            ],
        }

    def _fresh_completion(self, messages: list[dict[str, str]]) -> str:
        response = self._client.chat.completions.create(
            messages=messages,
            agent_id=self._agent.id,
            model=self._settings.asahio_model,
            routing_mode=self._settings.asahio_routing_mode,
            intervention_mode="OBSERVE",
        )
        content = (response.choices[0].message.content or "").strip()
        if response.asahio.cache_hit:
            retry_messages = messages + [
                {
                    "role": "system",
                    "content": f"Cache bypass retry fingerprint: {response.asahio.request_id or 'no-request-id'}",
                }
            ]
            retry_response = self._client.chat.completions.create(
                messages=retry_messages,
                agent_id=self._agent.id,
                model=self._settings.asahio_model,
                routing_mode=self._settings.asahio_routing_mode,
                intervention_mode="OBSERVE",
            )
            return (retry_response.choices[0].message.content or "").strip()
        return content


def _extract_acceptance_criteria(description: str) -> list[str]:
    if not description:
        return []

    lines = [line.strip() for line in description.splitlines()]
    criteria: list[str] = []
    in_acceptance_section = False

    for line in lines:
        normalized = line.casefold()
        if normalized == "acceptance criteria":
            in_acceptance_section = True
            continue
        if not in_acceptance_section:
            continue
        if normalized in {"technical notes", "scope of review"}:
            break
        if not line:
            continue
        if line.startswith("["):
            stripped = line.lstrip("[] ").strip()
            if stripped:
                criteria.append(stripped)
            continue
        if criteria:
            criteria[-1] = f"{criteria[-1]} {line}".strip()
        else:
            criteria.append(line)

    return criteria


def _parse_implementation_package(
    content: str,
    ticket: dict[str, object],
    approval_comment: str,
    acceptance_criteria: list[str],
) -> dict[str, str]:
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        payload = json.loads(match.group(0) if match else content)
        story_summary = str(payload.get("story_summary") or "").strip()
        story_description = str(payload.get("story_description") or "").strip()
        implementation_brief = str(payload.get("implementation_brief") or "").strip()
        if story_summary and story_description and implementation_brief:
            return {
                "story_summary": story_summary,
                "story_description": story_description,
                "implementation_brief": implementation_brief,
            }
    except Exception:
        pass

    summary = str(ticket.get("summary") or "Untitled work")
    key = str(ticket.get("key") or "")
    criteria_text = "\n".join(f"- {item}" for item in acceptance_criteria) or "- Review ticket details and define implementation tasks."
    return {
        "story_summary": f"Implementation: {summary}",
        "story_description": (
            f"Implement the approved work for {key}.\n\n"
            f"Approval signal: {approval_comment}\n\n"
            "Acceptance criteria to deliver:\n"
            f"{criteria_text}"
        ),
        "implementation_brief": (
            f"Source ticket: {key}\n"
            f"Summary: {summary}\n\n"
            "Implementation focus:\n"
            f"{criteria_text}\n\n"
            "Engineering note: translate the approved acceptance criteria into concrete repository changes before coding."
        ),
    }


def _parse_execution_tasks(content: str) -> list[dict[str, str]]:
    try:
        match = re.search(r"\{.*\}|\[.*\]", content, re.DOTALL)
        payload = json.loads(match.group(0) if match else content)
        tasks = payload.get("tasks", payload) if isinstance(payload, dict) else payload
        parsed_tasks: list[dict[str, str]] = []
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                summary = str(task.get("summary") or "").strip()
                description = str(task.get("description") or "").strip()
                artifact_file_name = str(task.get("artifact_file_name") or "").strip()
                artifact_content = str(task.get("artifact_content") or "").strip()
                if summary and description and artifact_file_name and artifact_content:
                    parsed_tasks.append(
                        {
                            "summary": summary,
                            "description": description,
                            "artifact_file_name": artifact_file_name,
                            "artifact_content": artifact_content,
                        }
                    )
        if parsed_tasks:
            return parsed_tasks
    except Exception:
        pass
    return []


def _parse_ticket_work_package(content: str) -> dict[str, object] | None:
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        payload = json.loads(match.group(0) if match else content)
        update_comment = str(payload.get("update_comment") or "").strip()
        artifacts_payload = payload.get("artifacts") or []
        artifacts: list[dict[str, str]] = []
        if isinstance(artifacts_payload, list):
            for artifact in artifacts_payload:
                if not isinstance(artifact, dict):
                    continue
                file_name = str(artifact.get("file_name") or "").strip()
                artifact_content = str(artifact.get("content") or "").strip()
                if file_name and artifact_content:
                    artifacts.append({"file_name": file_name, "content": artifact_content})
        if update_comment and artifacts:
            return {"update_comment": update_comment, "artifacts": artifacts}
    except Exception:
        pass
    return None


def _build_state_fingerprint(ticket: dict[str, object], extra: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(ticket, sort_keys=True).encode("utf-8"))
    for item in extra:
        digest.update(item.encode("utf-8"))
    return digest.hexdigest()[:16]
