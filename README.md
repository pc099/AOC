# Jira Bot

This project provides a small Python bot that:

- connects to Jira Cloud using an API token
- fetches tickets assigned to the authenticated user
- prints a summary or JSON payload
- can use ASAHIO to generate an explanation for each fetched ticket and post that result back to Jira as a comment
- automatically ensures a reusable ASAHIO agent named `Jira Agent` exists before generating explanations
- can detect an approval comment such as `this looks good proceed with the implementation`, create a follow-up Jira story, and save a local implementation brief
- can run a comment loop that posts the initial analysis, revises the analysis when users leave review feedback, and only advances to implementation after explicit approval
- supports a single-ticket autonomous workflow so decisions are made for one Jira ticket at a time instead of the whole assigned queue
- supports an autonomous worker loop that polls assigned tickets and runs the per-ticket decision engine continuously

## Project layout

- `main.py` - top-level orchestrator entrypoint
- `agent/asahio_agent.py` - ASAHIO explanation agent
- `jira_bot/bot.py` - orchestration layer
- `jira_bot/jira_client.py` - Jira REST integration
- `jira_bot/config.py` - environment-backed settings
- `jira_bot/.env` - local environment variables

## Prerequisites

- Python 3.11 or newer
- A Jira Cloud account, email address, and API token

## Setup

1. Create a virtual environment.
2. Install dependencies.
3. Copy `.env.example` to `.env` and fill in the Jira values.
4. If your machine has corporate or incomplete CA trust and Jira TLS verification fails, set `JIRA_VERIFY_SSL=false` in `.env` temporarily.
5. Run the bot.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m jira_bot
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `JIRA_BASE_URL` | Jira Cloud site URL, for example `https://acme.atlassian.net` |
| `JIRA_EMAIL` | Jira account email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_JQL` | JQL used for fetching assigned issues |
| `JIRA_VERIFY_SSL` | Set to `false` only if local certificate validation fails; otherwise keep `true` |
| `ASAHIO_API_KEY` | ASAHIO API key, required for explanation mode |
| `ASAHIO_VERIFY_SSL` | Set to `false` only if local certificate validation fails for ASAHIO; otherwise keep `true` |
| `ASAHIO_MODEL` | Requested model name, default `gpt-4o` |
| `ASAHIO_ROUTING_MODE` | ASAHIO routing mode, default `AUTO` |
| `ASAHIO_INTERVENTION_MODE` | ASAHIO intervention mode, default `ASSISTED` |
| `AUTONOMOUS_POLL_SECONDS` | Worker polling interval in seconds, default `300` |
| `AUTONOMOUS_TICKET_LIMIT` | Number of assigned tickets the worker checks each cycle, default `10` |

## Usage

Human-readable summary:

```powershell
python -m jira_bot --ticket-limit 5
```

JSON output:

```powershell
python -m jira_bot --json
```

Generate explanations and post them as Jira comments:

```powershell
python -m jira_bot --explain-and-update --ticket-limit 5
```

Generate explanations without updating Jira:

```powershell
python -m jira_bot --explain-and-update --dry-run --ticket-limit 5
```

Process implementation approvals from ticket comments:

```powershell
python main.py --process-implementation-approval --ticket-limit 5
```

Run the full feedback loop:

```powershell
python main.py --run-feedback-loop --ticket-limit 5
```

Run one ticket autonomously:

```powershell
python main.py --run-autonomous-ticket --ticket-key SCRUM-2
```

Run the autonomous worker continuously:

```powershell
python main.py --run-autonomous-worker
```

Run one worker cycle and exit:

```powershell
python main.py --run-autonomous-worker --once
```

Preview implementation approval processing without creating the story or artifact:

```powershell
python main.py --process-implementation-approval --dry-run --ticket-limit 5
```

## Notes

- Jira access uses HTTP basic authentication with your email address and API token.
- If you use `JIRA_VERIFY_SSL=false`, requests will work around local certificate issues but TLS verification is disabled for that Jira connection.
- Explanation mode posts generated text back to Jira as issue comments.
- The explanation only uses fields fetched by this bot: summary, status, priority, issue type, description, and ticket URL.
- On each explanation run, the orchestrator checks ASAHIO for an existing `Jira Agent`. If found, it reuses that agent; otherwise it creates it once and continues.
- The implementation workflow looks for approval text in Jira comments, reuses an existing follow-up story if one was already recorded on the ticket, and writes a local brief under `generated_implementation/`.
- The feedback loop posts marker-prefixed Jira comments so later runs can detect which user review comment was already addressed and avoid duplicate responses.
- The recommended operational mode is `python main.py --run-autonomous-ticket --ticket-key <KEY>` so the agent makes decisions for one Jira ticket at a time.
- Full autonomy still requires a host process. Run `python main.py --run-autonomous-worker` in a persistent terminal, service, container, or Windows Task Scheduler wrapper so the agent can keep polling without manual triggers.
