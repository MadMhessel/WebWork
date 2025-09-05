"""Command line interface for newsbot."""

import argparse
import logging
import os

from dotenv import load_dotenv

from . import bot


def build_parser() -> argparse.ArgumentParser:
    """Create argument parser for the CLI."""
    parser = argparse.ArgumentParser(description="Newsbot CLI")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run a single iteration")
    mode.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--dry-run", action="store_true", help="Do not publish messages")
    parser.add_argument("--mock", action="store_true", help="Use mock data instead of fetching")
    return parser


def main() -> None:
    """Entry point for the CLI."""
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    log_level = os.getenv("LOG_LEVEL", "INFO")
    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))

    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    if args.loop:
        bot.run_loop(
            dry_run=args.dry_run,
            use_mock=args.mock,
            interval=poll_interval,
            log_level=log_level,
        )
    else:
        bot.run_once(
            dry_run=args.dry_run,
            use_mock=args.mock,
            log_level=log_level,
        )


if __name__ == "__main__":
    main()
