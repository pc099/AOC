# Jira Bot

This project provides a small Python bot that:

- connects to Jira Cloud using an API token
- fetches tickets assigned to the authenticated user
- prints a summary or JSON payload

## Project layout

- `mail_jira_bot/__main__.py` - CLI entrypoint
- `mail_jira_bot/bot.py` - orchestration layer
- `mail_jira_bot/jira_client.py` - Jira REST integration
- `.env.example` - required environment variables

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
python -m mail_jira_bot
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `JIRA_BASE_URL` | Jira Cloud site URL, for example `https://acme.atlassian.net` |
| `JIRA_EMAIL` | Jira account email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_JQL` | JQL used for fetching assigned issues |
| `JIRA_VERIFY_SSL` | Set to `false` only if local certificate validation fails; otherwise keep `true` |

## Usage

Human-readable summary:

```powershell
python -m mail_jira_bot --ticket-limit 5
```

JSON output:

```powershell
python -m mail_jira_bot --json
```

## Notes

- Jira access uses HTTP basic authentication with your email address and API token.
- If you use `JIRA_VERIFY_SSL=false`, requests will work around local certificate issues but TLS verification is disabled for that Jira connection.
- This bot currently reads data only. It does not modify Jira tickets.
