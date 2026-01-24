"""CLI entry point for market-drip."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable, Sequence

from .db.db import init_db
from .sync import sync_markets
from .sync_tokens import sync_tokens
from .tasks.build_tasks import build_tasks
from .worker.run_worker import run_worker
from .status import get_status
from .db.maintenance import wal_checkpoint, vacuum


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


def _build_tasks(args: argparse.Namespace) -> int:
    now_ts = args.now_ts if args.now_ts is not None else int(time.time())
    stats = build_tasks(
        db_path=args.db,
        now_ts=now_ts,
        rolling_days=args.rolling_days,
        res15_chunk_days=args.res15_chunk_days,
        close_start_hours=args.close_start_hours,
        close_end_hours=args.close_end_hours,
        res1_chunk_hours=args.res1_chunk_hours,
    )
    print(
        "Build tasks complete: total={total}, 15m={m15}, 1m={m1}".format(
            total=stats.total_inserted,
            m15=stats.inserted_15m,
            m1=stats.inserted_1m,
        )
    )
    return 0


def _sync_tokens(args: argparse.Namespace) -> int:
    sync_tokens(
        db_path=args.db,
        limit=args.limit,
        offset=args.offset,
        rolling_days=args.rolling_days,
        statuses=args.status,
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
    )
    return 0


def _run_worker(args: argparse.Namespace) -> int:
    now_ts = args.now_ts if args.now_ts is not None else int(time.time())
    stats = run_worker(
        db_path=args.db,
        now_ts=now_ts,
        max_tasks=args.max_tasks,
        no_sleep=args.no_sleep,
        no_jitter=args.no_jitter,
    )
    print(
        "Run worker complete: processed={processed}, done={done}, deferred={deferred}, error={error}, prices={prices}".format(
            processed=stats["tasks_processed"],
            done=stats["tasks_done"],
            deferred=stats["tasks_deferred"],
            error=stats["tasks_error"],
            prices=stats["prices_inserted"],
        )
    )
    return 0


def _status(args: argparse.Namespace) -> int:
    status = get_status(args.db)
    print(f"db_path: {status['db_path']}")
    print(f"db_size_bytes: {status['db_size_bytes']}")
    print(
        "counts: markets={m} tokens={t} prices={p}".format(
            m=status["counts"]["markets"],
            t=status["counts"]["tokens"],
            p=status["counts"]["prices"],
        )
    )
    print(
        "tasks: pending={p} running={r} deferred={d} done={dn} error={e}".format(
            p=status["tasks"]["pending"],
            r=status["tasks"]["running"],
            d=status["tasks"]["deferred"],
            dn=status["tasks"]["done"],
            e=status["tasks"]["error"],
        )
    )
    print(f"heartbeat_ts: {status['heartbeat_ts']}")
    if status["recent_errors"]:
        print("recent_errors:")
        for item in status["recent_errors"]:
            print("  - {count} x {message}".format(count=item["count"], message=item["message"]))
    else:
        print("recent_errors: none")
    return 0


def _db_checkpoint(args: argparse.Namespace) -> int:
    result = wal_checkpoint(args.db)
    print("WAL checkpoint complete: mode={mode} result={result}".format(**result))
    return 0


def _db_vacuum(args: argparse.Namespace) -> int:
    vacuum(args.db)
    print("VACUUM complete")
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
    def _sync_tokens_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )
        p.add_argument("--limit", type=int, default=1000, help="Limit number of markets to process")
        p.add_argument("--offset", type=int, default=0, help="Offset for market selection")
        p.add_argument("--rolling-days", type=int, default=90, help="Select markets within rolling days")
        p.add_argument(
            "--status",
            action="append",
            default=None,
            help="Market status filter (repeatable)",
        )
        p.add_argument("--concurrency", type=int, default=10, help="Concurrent HTTP fetches")
        p.add_argument("--max-attempts", type=int, default=5, help="Max attempts per market")

    _add_subcommand(
        subparsers,
        "sync-tokens",
        "Sync token metadata from Gamma detail endpoint",
        _sync_tokens,
        _sync_tokens_args,
    )
    def _build_tasks_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )
        p.add_argument("--now-ts", type=int, default=None, help="Override current epoch seconds")
        p.add_argument("--rolling-days", type=int, default=30, help="Rolling window days")
        p.add_argument("--res15-chunk-days", type=int, default=7, help="Chunk size in days")
        p.add_argument("--close-start-hours", type=int, default=6, help="Hours before end_ts")
        p.add_argument("--close-end-hours", type=int, default=1, help="Hours after end_ts")
        p.add_argument("--res1-chunk-hours", type=int, default=2, help="Chunk size in hours")

    _add_subcommand(
        subparsers,
        "build-tasks",
        "Build ingestion tasks",
        _build_tasks,
        _build_tasks_args,
    )
    def _run_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )
        p.add_argument("--now-ts", type=int, default=None, help="Override current epoch seconds")
        p.add_argument("--max-tasks", type=int, default=None, help="Limit number of tasks")
        p.add_argument("--no-sleep", action="store_true", help="Disable inter-task sleep")
        p.add_argument("--no-jitter", action="store_true", help="Disable jitter for backoff and sleep")

    _add_subcommand(subparsers, "run", "Run the worker", _run_worker, _run_args)
    def _status_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )

    _add_subcommand(subparsers, "status", "Show status", _status, _status_args)
    def _db_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--db",
            default=str(Path("./market-drip.sqlite")),
            help="Path to the SQLite database file",
        )

    _add_subcommand(subparsers, "db-checkpoint", "Checkpoint the database", _db_checkpoint, _db_args)
    _add_subcommand(subparsers, "db-vacuum", "Vacuum the database", _db_vacuum, _db_args)
    _add_subcommand(subparsers, "export", "Export data", _not_implemented)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 2
