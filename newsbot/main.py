"""Command line interface for newsbot."""

import argparse

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
    parser = build_parser()
    args = parser.parse_args()

    if args.loop:
        bot.run_loop(dry_run=args.dry_run, use_mock=args.mock)
    else:
        bot.run_once(dry_run=args.dry_run, use_mock=args.mock)


if __name__ == "__main__":
    main()
