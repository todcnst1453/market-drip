import subprocess
import sys
import tempfile


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
        "sync-markets",
        "build-tasks",
        "run",
        "status",
        "db-checkpoint",
        "db-vacuum",
        "export",
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "market_drip",
                "init-db",
                "--db",
                f"{tmp_dir}/test.sqlite",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Initialized database at" in result.stdout

    for command in commands:
        result = subprocess.run(
            [sys.executable, "-m", "market_drip", command],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Not implemented yet" in result.stdout
