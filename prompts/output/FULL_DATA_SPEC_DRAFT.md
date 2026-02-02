# Market Drip: Full Data Specification Draft

This document provides a comprehensive overview of the data infrastructure for the `market-drip` project, covering data capture, storage, and specific characteristics of the recorded price paths.

## 1. Database & Schema Analysis

The application uses a **SQLite** database to store all collected data.

### Table Schemas

#### `markets`
Stores core information about each prediction market.

| Column          | Data Type | Description                                     |
|-----------------|-----------|-------------------------------------------------|
| `market_pk`     | `INTEGER` | **Primary Key**                                 |
| `gamma_market_id` | `TEXT`    | **Unique.** The market's ID from the Gamma API.   |
| `slug`          | `TEXT`    | URL-friendly market identifier.                 |
| `question`      | `TEXT`    | The full question/title of the market.          |
| `status`        | `TEXT`    | The market's current status (e.g., "open", "closed"). |
| `end_ts`        | `INTEGER` | Unix timestamp of when the market is scheduled to end. |
| `updated_ts`    | `INTEGER` | Unix timestamp of the last update to this record. |

#### `tokens`
Stores information about the outcome tokens for each market.

| Column         | Data Type | Description                                                          |
|----------------|-----------|----------------------------------------------------------------------|
| `token_pk`     | `INTEGER` | **Primary Key**                                                      |
| `clob_token_id`| `TEXT`    | **Unique.** The token's ID from the CLOB API.                          |
| `market_pk`    | `INTEGER` | **Foreign Key** to `markets.market_pk`.                              |
| `outcome_name` | `TEXT`    | The name of the outcome (e.g., "Yes", "No").                         |
| `is_short_cycle`| `INTEGER` | Boolean flag (0 or 1) indicating if the market is a "short cycle" market, meaning it's near its resolution time and warrants higher frequency data collection. |
| `updated_ts`   | `INTEGER` | Unix timestamp of the last update to this record.                    |

#### `prices`
Stores the time-series price data for each outcome token.

| Column       | Data Type | Description                                                     |
|--------------|-----------|-----------------------------------------------------------------|
| `token_pk`   | `INTEGER` | **Composite Primary Key.** **Foreign Key** to `tokens.token_pk`.    |
| `ts`         | `INTEGER` | **Composite Primary Key.** Unix timestamp of the price point.       |
| `resolution` | `INTEGER` | **Composite Primary Key.** The resolution of the price data (e.g., 1 for 1-minute, 15 for 15-minute). |
| `price_bp`   | `INTEGER` | The price in basis points (e.g., a price of 0.50 is stored as 500000). |

#### `fetch_tasks`
A queue of tasks for the worker to fetch price data.

| Column        | Data Type | Description                                                        |
|---------------|-----------|--------------------------------------------------------------------|
| `task_pk`     | `INTEGER` | **Primary Key**                                                    |
| `token_pk`    | `INTEGER` | **Foreign Key** to `tokens.token_pk`.                                |
| `resolution`  | `INTEGER` | The resolution to fetch (1 or 15).                                 |
| `start_ts`    | `INTEGER` | The start timestamp for the data fetching window.                  |
| `end_ts`      | `INTEGER` | The end timestamp for the data fetching window.                    |
| `status`      | `TEXT`    | The status of the task (e.g., "pending", "running", "done", "error"). |
| `attempts`    | `INTEGER` | The number of times the task has been attempted.                     |
| `next_run_at` | `INTEGER` | The timestamp when the task should be run next (for deferred tasks). |
| `last_error`  | `TEXT`    | The last error message if the task failed.                         |
| `updated_at`  | `INTEGER` | The timestamp of the last update to this task.                     |

*A `UNIQUE` constraint exists on `(token_pk, resolution, start_ts, end_ts)`.*

#### `run_state`
A simple key-value store for application state.

| Column  | Data Type | Description                 |
|---------|-----------|-----------------------------|
| `key`   | `TEXT`    | **Primary Key**             |
| `value` | `TEXT`    | The value for the given key. |

## 2. Ingestion & Capture Logic

### Data Sources
The system uses two public, unauthenticated APIs from Polymarket:
-   **Gamma API (`https://gamma-api.polymarket.com`)**: Used to discover and list markets.
-   **CLOB API (`https://clob.polymarket.com`)**: Used to fetch historical price data for individual outcome tokens.

### Ingestion Process

The data ingestion is a multi-step process orchestrated by the CLI:

1.  **`sync-markets`**: This command fetches a list of markets from the Gamma API and populates the `markets` table.
2.  **`sync-tokens`**: This command iterates through the markets in the database, fetches detailed market information from the Gamma API, and populates the `tokens` table with the outcome tokens for each market.
3.  **`build-tasks`**: This is the core of the data capture strategy. It creates tasks in the `fetch_tasks` table based on the following logic:
    *   **15-Minute Resolution**: For all tokens, it creates tasks to fetch data in 7-day chunks over a 30-day rolling window.
    *   **1-Minute Resolution**: For "short cycle" markets (markets near their resolution date), it creates tasks to fetch higher-resolution data in 2-hour chunks, from 6 hours before to 1 hour after the market's `end_ts`.
4.  **`run-worker`**: This command starts a worker process that continuously polls the `fetch_tasks` table for pending tasks. For each task, it calls the CLOB API's `prices-history` endpoint to get the price data and stores it in the `prices` table.

### Capture Frequency

The capture frequency is determined by the `resolution` parameter in the `fetch_tasks` table, which is set during the `build-tasks` step. The system is designed to collect data at two frequencies:
-   **15-minute intervals** for general historical data.
-   **1-minute intervals** for the period around a market's resolution.

## 3. Data Quality & Density Inspection

-   **Record Count**: The number of records in the `prices` table will grow over time as the worker processes tasks.
-   **Time Range**: The time range of the data is determined by the `rolling_days` parameter in the `build-tasks` command and the `end_ts` of the markets being tracked.
-   **Data Gaps**: Data gaps can occur for several reasons:
    -   If the `run-worker` process is not running, no data will be collected.
    -   If the Polymarket APIs are unavailable or return errors, the worker will back off and retry, which can lead to gaps.
    -   For historical markets that are no longer active, the CLOB API may not return any price data for the requested time windows, resulting in empty price data for those tasks. This is a key characteristic of the system: it is primarily designed to collect data for markets that are currently active or have been active recently.

