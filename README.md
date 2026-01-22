# market-drip

market-drip is a research-oriented, low-frequency data ingestion tool for prediction markets.

Goals:
- Collect public market price paths slowly and reliably
- Store data in a local SQLite database
- Support long-running, reproducible research workflows

Status: Step 0 provides a CLI skeleton, logging stub, tests, and CI.
Status: Step 1 adds an idempotent SQLite schema and init-db command.

Disclaimer: This tool is for research and education only.
