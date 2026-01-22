"""CLI entry point for market-drip."""

from __future__ import annotations

import argparse
from typing import Callable, Sequence


def _not_implemented(_: argparse.Namespace) -> int:
    print("Not implemented yet")
    return 0


def _add_subcommand(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    handler: Callable[[argparse.Namespace], int],
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(func=handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-drip")
    subparsers = parser.add_subparsers(dest="command", required=False)

    _add_subcommand(subparsers, "init-db", "Initialize the database", _not_implemented)
    _add_subcommand(subparsers, "sync-markets", "Sync market metadata", _not_implemented)
    _add_subcommand(subparsers, "build-tasks", "Build ingestion tasks", _not_implemented)
    _add_subcommand(subparsers, "run", "Run the worker", _not_implemented)
    _add_subcommand(subparsers, "status", "Show status", _not_implemented)
    _add_subcommand(subparsers, "db-checkpoint", "Checkpoint the database", _not_implemented)
    _add_subcommand(subparsers, "db-vacuum", "Vacuum the database", _not_implemented)
    _add_subcommand(subparsers, "export", "Export data", _not_implemented)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 2