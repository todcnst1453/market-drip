# market-drip

**market-drip** is a research-oriented, low-frequency data ingestion tool for prediction markets.

It is designed to **quietly and continuously record public market price paths** over long periods of time, with an emphasis on:

- robustness over speed
- low-frequency, non-intrusive API usage
- reproducible datasets
- structured storage for downstream analysis

This project is intended for **market behavior research**, not for trading, arbitrage, or live decision-making.

---

## Motivation

Understanding market dynamics—such as price discovery, volatility, and liquidity effects—requires **real historical price paths**, not just theoretical models.

`market-drip` was built to support questions like:

- How do prediction market prices evolve over time?
- How does price behavior differ near resolution or information release?
- What does real-world liquidity "feel like" under different market conditions?

Rather than scraping aggressively or reacting in real time, `market-drip` takes a **slow, persistent, and observational approach**.

---

## What This Project Is

- ✅ A **passive data collector** using public APIs
- ✅ Designed for **long-running execution** (days at a time)
- ✅ Low-frequency, rate-limited by default
- ✅ Focused on **research and empirical analysis**
- ✅ Uses a local **SQLite database** for structured storage

---

## What This Project Is NOT

- ❌ Not a trading bot
- ❌ Not an arbitrage system
- ❌ Not a real-time market signal generator
- ❌ Not a high-frequency scraper
- ❌ Does not interact with user accounts or private keys

---

## Data Collection Strategy (Current Scope)

The current implementation targets a **rolling 30-day window** with adaptive granularity:

### 1. Coarse-Grained Coverage (All Selected Markets)
- Resolution: **15-minute**
- Window: **last 30 days**
- Purpose: macro trends, market comparison, sample selection

### 2. Fine-Grained Event Windows (Short-Cycle / Sports Markets)
- Resolution: **1-minute**
- Window: **around market close / event end**
- Purpose: microstructure, jump behavior, response timing

This layered approach balances **information density** with **storage efficiency**.

---

## Storage Model

All data is stored locally in a single SQLite database:

- Market metadata
- Outcome/token mapping
- Time-series price data (integer-quantized)
- Task and fetch state for resumability

Key design goals:
- idempotent writes
- resumable execution
- bounded database growth

No JSON or flat files are used for primary storage.

---

## Reliability & Long-Running Design

`market-drip` is explicitly designed to run unattended for extended periods:

- conservative rate limiting
- exponential backoff with jitter
- task-based state machine
- resumable after interruption or restart
- single-process, low-complexity execution model

The system favors **predictable behavior** over maximum throughput.

---

## Usage Policy & Responsibility

This project accesses **publicly available market data**.

Users of this software are responsible for:

- complying with the API usage policies of data providers
- running the tool in a low-frequency, non-disruptive manner
- understanding that data completeness is not guaranteed

The authors do not endorse or encourage high-frequency scraping or commercial data harvesting.

---

## Intended Audience

- Researchers studying prediction markets
- Developers building market simulations or pricing models
- Analysts interested in empirical market behavior
- Anyone seeking a clean historical dataset for offline analysis

---

## Project Status

This is an **active research tool**.

Interfaces, schemas, and defaults may evolve as new empirical questions arise, but the core philosophy—**slow, robust observation**—is stable.

---

## License

[Choose your license here — e.g. MIT / Apache-2.0]

---

## Disclaimer

This project is provided for research and educational purposes only.  
It makes no guarantees about data accuracy, completeness, or fitness for any particular use.
