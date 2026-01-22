"""CLI entry point for market-drip."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Sequence

from .db.db import init_db
from .sync import sync_markets


def _not_implemented(_: argparse.Namespace) -> int:
    print("Not implemented yet")
    return 0


def _init_db(args: argparse.Namespace) -> int:
    init_db(args.db)
    print(f"Initialized database at {args.db}")
    return 0


def _sync_markets(args: argparse.Namespace) -> int:
    sync_markets(
        db_path=args.db,
        now_ts=args.now_ts,
        limit=args.limit,
        max_pages=args.max_pages,
    )
    print(f"Synced markets into {args.db}")
    return 0


def _add_subcommand(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    handler: Callable[[argparse.Namespace], int],
    configure: Callable[[argparse.ArgumentParser], None] | None = None,
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    if configure is not None:
        configure(parser)
    parser.set_defaults(func=handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-drip")
    subparsers = parser.add_subparsers(dest="command", required=False)

    def _init_db_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )

    _add_subcommand(subparsers, "init-db", "Initialize the database", _init_db, _init_db_args)
    def _sync_markets_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )
        p.add_argument("--now-ts", type=int, default=None, help="Override current epoch seconds")
        p.add_argument("--limit", type=int, default=100, help="Page size for Gamma API")
        p.add_argument("--max-pages", type=int, default=None, help="Limit number of pages")

    _add_subcommand(
        subparsers,
        "sync-markets",
        "Sync market metadata",
        _sync_markets,
        _sync_markets_args,
    )
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
