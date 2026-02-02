# market-drip

**market-drip** is a research-oriented, low-frequency data collector for prediction markets.

It is designed to quietly and continuously record **public market price paths** over extended periods of time, with an emphasis on robustness, reproducibility, and long-running stability.

This project is intended for **market behavior research**, not for trading, arbitrage, or real-time decision making.

---

## Motivation

Understanding prediction markets requires observing how prices actually evolve in the wild.

Rather than focusing on theoretical models or simulated liquidity, `market-drip` exists to support empirical questions such as:

- How do market prices move over time?
- How does price behavior change near event resolution?
- What does real-world liquidity “feel like” under different market conditions?

To answer these questions, the system deliberately favors **slow, persistent observation** over speed or aggressiveness.

---

## What This Project Is

- A **passive, read-only data collector**
- Uses **public, unauthenticated APIs** only
- Designed for **low-frequency, non-intrusive access**
- Optimized for **long-running execution** (days at a time)
- Stores data in a **structured local database** for offline analysis

---

## What This Project Is NOT

- ❌ Not a trading bot
- ❌ Not an arbitrage system
- ❌ Not a signal generator
- ❌ Not a real-time execution engine
- ❌ Does not place orders or interact with user accounts
- ❌ Does not use private keys, wallets, or authenticated endpoints

---

## Data Collection Philosophy

`market-drip` follows a deliberately conservative approach:

- **Low frequency** by default  
- **Evenly distributed requests** over time  
- **No burst traffic or scraping behavior**  
- **Graceful backoff** on errors or rate limits  

The goal is to observe markets without disturbing them.

Data completeness is not guaranteed; continuity and stability are prioritized instead.

---

## Storage Model

All collected data is stored locally in a SQLite database.

Key design principles:
- Structured relational storage (no raw JSON dumps)
- Idempotent writes
- Resumable execution after interruption
- Bounded growth using rolling time windows

This makes the dataset suitable for reproducible offline analysis using standard data tools.

---

## Usage & Responsibility

This software accesses **publicly available market data**.

Users are responsible for:
- Complying with the terms and usage policies of data providers
- Running the tool in a low-frequency, non-disruptive manner
- Understanding that collected data may be incomplete or delayed

The authors do not encourage or endorse high-frequency scraping or commercial data harvesting.

---

## Intended Audience

- Researchers studying prediction markets
- Developers exploring market microstructure
- Analysts interested in empirical price dynamics
- Anyone seeking reproducible historical market data for offline study

---

## Project Status

This is an **active research tool**.

Interfaces and internal details may evolve, but the core philosophy—  
**slow, robust, and unobtrusive observation**—is stable.

---

## Disclaimer

This project is provided for research and educational purposes only.  
It makes no guarantees regarding data accuracy, completeness, or fitness for any particular use.

---

## Runbook

Typical flow:

```
python -m market_drip sync-markets --db <path>
python -m market_drip sync-tokens --db <path> --limit 1000
python -m market_drip build-tasks --db <path>
python -m market_drip run --db <path>
```

---

## AI Integration

This project is managed by the Gemini CLI.