import subprocess
import sys


def test_import_package() -> None:
    import market_drip  # noqa: F401


def test_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "market_drip", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_cli_subcommands_exist() -> None:
    commands = [
        "init-db",
        "sync-markets",
        "build-tasks",
        "run",
        "status",
        "db-checkpoint",
        "db-vacuum",
        "export",
    ]

    for command in commands:
        result = subprocess.run(
            [sys.executable, "-m", "market_drip", command],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Not implemented yet" in result.stdout