from __future__ import annotations

import argparse
import sys

from .bot import MailJiraBot
from .config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Jira tickets assigned to the authenticated user."
    )
    parser.add_argument("--ticket-limit", type=int, default=10, help="Number of Jira tickets to fetch")
    parser.add_argument("--json", action="store_true", help="Print output as JSON")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        settings = Settings.from_env()
        settings.validate()
        bot = MailJiraBot(settings)
        if args.json:
            print(bot.render_json(ticket_limit=args.ticket_limit))
        else:
            print(bot.render_summary(ticket_limit=args.ticket_limit))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
