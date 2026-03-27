from __future__ import annotations

import argparse
import sys

from jira_bot.bot import MailJiraBot
from jira_bot.config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Jira tickets assigned to the authenticated user."
    )
    parser.add_argument("--ticket-limit", type=int, default=10, help="Number of Jira tickets to fetch")
    parser.add_argument("--ticket-key", help="Specific Jira ticket key to operate on, for example SCRUM-2")
    parser.add_argument("--json", action="store_true", help="Print output as JSON")
    parser.add_argument(
        "--explain-and-update",
        action="store_true",
        help="Use ASAHIO to generate ticket explanations and post them back to Jira as comments",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate explanations without posting comments back to Jira",
    )
    parser.add_argument(
        "--process-implementation-approval",
        action="store_true",
        help="If a ticket comment says to proceed with implementation, create a follow-up Jira story and a local implementation brief",
    )
    parser.add_argument(
        "--run-feedback-loop",
        action="store_true",
        help="Run the ticket comment loop: post initial analysis, respond to review feedback, and advance to implementation only after approval",
    )
    parser.add_argument(
        "--run-autonomous-ticket",
        action="store_true",
        help="Run the single-ticket autonomous decision workflow on one Jira ticket",
    )
    parser.add_argument(
        "--run-autonomous-worker",
        action="store_true",
        help="Run the autonomous Jira worker continuously against assigned tickets",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        help="Polling interval in seconds for the autonomous worker",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one autonomous worker cycle and exit",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        settings = Settings.from_env()
        settings.validate(
            require_asahio=(
                args.explain_and_update
                or args.process_implementation_approval
                or args.run_feedback_loop
                or args.run_autonomous_ticket
                or args.run_autonomous_worker
            )
        )
        bot = MailJiraBot(settings)
        if args.run_autonomous_worker:
            print(
                bot.run_autonomous_worker(
                    poll_seconds=args.poll_seconds,
                    ticket_limit=args.ticket_limit,
                    once=args.once,
                    dry_run=args.dry_run,
                )
            )
        elif args.run_autonomous_ticket:
            if not args.ticket_key:
                raise ValueError("--run-autonomous-ticket requires --ticket-key")
            print(bot.run_autonomous_ticket(ticket_key=args.ticket_key, dry_run=args.dry_run))
        elif args.run_feedback_loop:
            print(
                bot.render_ticket_feedback_loop(
                    ticket_limit=args.ticket_limit,
                    dry_run=args.dry_run,
                    ticket_key=args.ticket_key,
                )
            )
        elif args.process_implementation_approval:
            print(
                bot.render_implementation_approvals(
                    ticket_limit=args.ticket_limit,
                    dry_run=args.dry_run,
                    ticket_key=args.ticket_key,
                )
            )
        elif args.explain_and_update:
            print(
                bot.render_explanations(
                    ticket_limit=args.ticket_limit,
                    dry_run=args.dry_run,
                    ticket_key=args.ticket_key,
                )
            )
        elif args.json:
            print(bot.render_json(ticket_limit=args.ticket_limit, ticket_key=args.ticket_key))
        else:
            print(bot.render_summary(ticket_limit=args.ticket_limit, ticket_key=args.ticket_key))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())