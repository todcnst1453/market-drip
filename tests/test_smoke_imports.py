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

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "market_drip",
                "build-tasks",
                "--db",
                f"{tmp_dir}/test.sqlite",
                "--now-ts",
                "1700000000",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Build tasks complete" in result.stdout

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "market_drip",
                "run",
                "--db",
                f"{tmp_dir}/test.sqlite",
                "--now-ts",
                "1700000000",
                "--max-tasks",
                "1",
                "--no-sleep",
                "--no-jitter",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Run worker complete" in result.stdout

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "market_drip",
                "status",
                "--db",
                f"{tmp_dir}/test.sqlite",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "counts: markets=" in result.stdout

    for command in commands:
        result = subprocess.run(
            [sys.executable, "-m", "market_drip", command],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Not implemented yet" in result.stdout
