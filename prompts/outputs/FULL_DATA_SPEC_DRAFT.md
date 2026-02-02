# Market Drip Data Specification Draft

This document outlines the data infrastructure of the `market-drip` project, including the database schema, data ingestion logic, and data characteristics.

## 1. Database & Schema Analysis

The project uses **SQLite** as its database. The schema is defined in `market_drip/db/schema.py` and is as follows:

### `markets` Table

Stores metadata about the prediction markets.

| Column          | Data Type | Constraints         | Description                                     |
|-----------------|-----------|---------------------|-------------------------------------------------|
| `market_pk`     | INTEGER   | PRIMARY KEY         | Unique identifier for the market.               |
| `gamma_market_id` | TEXT      | UNIQUE NOT NULL     | The market ID from the Polymarket Gamma API.    |
| `slug`          | TEXT      |                     | URL-friendly slug for the market question.      |
| `question`      | TEXT      |                     | The question of the prediction market.          |
| `status`        | TEXT      |                     | The current status of the market (e.g., active, resolved). |
| `end_ts`        | INTEGER   |                     | Unix timestamp of when the market is expected to end. |
| `updated_ts`    | INTEGER   |                     | Unix timestamp of when the record was last updated. |

### `tokens` Table

Stores information about the outcome tokens for each market.

| Column           | Data Type | Constraints                     | Description                                     |
|------------------|-----------|---------------------------------|-------------------------------------------------|
| `token_pk`       | INTEGER   | PRIMARY KEY                     | Unique identifier for the token.                |
| `clob_token_id`  | TEXT      | UNIQUE NOT NULL                 | The token ID from the Polymarket CLOB API.      |
| `market_pk`      | INTEGER   | NOT NULL, FOREIGN KEY (markets) | Foreign key to the `markets` table.             |
| `outcome_name`   | TEXT      |                                 | The name of the outcome (e.g., "Yes", "No").    |
| `is_short_cycle` | INTEGER   | NOT NULL DEFAULT 0              | A flag indicating if the market is a short-cycle market. |
| `updated_ts`     | INTEGER   |                                 | Unix timestamp of when the record was last updated. |

### `prices` Table

Stores the historical price data for each outcome token.

| Column       | Data Type | Constraints               | Description                                           |
|--------------|-----------|---------------------------|-------------------------------------------------------|
| `token_pk`   | INTEGER   | NOT NULL, FOREIGN KEY (tokens) | Foreign key to the `tokens` table.                    |
| `ts`         | INTEGER   | NOT NULL                  | Unix timestamp of the price point.                    |
| `resolution` | INTEGER   | NOT NULL                  | The resolution of the data point (e.g., 1 for 1 minute). |
| `price_bp`   | INTEGER   | NOT NULL                  | The price in basis points (price * 1,000,000).        |
| *Composite PK* |           | (`token_pk`, `resolution`, `ts`) | Ensures uniqueness of price points.                   |

### `fetch_tasks` Table

A queue of tasks for the worker to fetch historical price data.

| Column        | Data Type | Constraints                | Description                                       |
|---------------|-----------|----------------------------|---------------------------------------------------|
| `task_pk`     | INTEGER   | PRIMARY KEY                | Unique identifier for the task.                   |
| `token_pk`    | INTEGER   | NOT NULL, FOREIGN KEY (tokens) | Foreign key to the `tokens` table.                |
| `resolution`  | INTEGER   | NOT NULL                   | The resolution to fetch.                          |
| `start_ts`    | INTEGER   | NOT NULL                   | Unix timestamp for the start of the fetch window. |
| `end_ts`      | INTEGER   | NOT NULL                   | Unix timestamp for the end of the fetch window.   |
| `status`      | TEXT      | NOT NULL                   | The status of the task (pending, running, done, error, deferred). |
| `attempts`    | INTEGER   | NOT NULL DEFAULT 0         | The number of times the task has been attempted.  |
| `next_run_at` | INTEGER   | NOT NULL DEFAULT 0         | Unix timestamp for when the task should be run next. |
| `last_error`  | TEXT      |                            | The last error message if the task failed.        |
| `updated_at`  | INTEGER   | NOT NULL                   | Unix timestamp of when the task was last updated. |
| *Unique*      |           | (`token_pk`, `resolution`, `start_ts`, `end_ts`) | Prevents duplicate tasks. |

### `run_state` Table

A key-value store for storing the application's state.

| Column  | Data Type | Constraints | Description                       |
|---------|-----------|-------------|-----------------------------------|
| `key`   | TEXT      | PRIMARY KEY | The key for the state variable.   |
| `value` | TEXT      | NOT NULL    | The value of the state variable.  |

## 2. Ingestion & Capture Logic

The data ingestion process is split into two main parts: market discovery and price history fetching.

### Data Sources

*   **Polymarket Gamma API** (`https://gamma-api.polymarket.com`): Used to discover markets and their associated outcome tokens.
*   **Polymarket CLOB API** (`https://clob.polymarket.com`): Used to fetch historical price data for individual outcome tokens.

### Ingestion Flow

1.  **Market Discovery**:
    *   The `sync_markets` script in `market_drip/sync.py` is executed.
    *   It calls the Gamma API's `/markets` endpoint to get a list of prediction markets.
    *   It then populates the `markets` and `tokens` tables in the local SQLite database with this information.

2.  **Task Creation**:
    *   A separate process (likely `market_drip/tasks/build_tasks.py`) creates tasks in the `fetch_tasks` table. Each task specifies a token and a time range for which to fetch price data.

3.  **Price History Fetching**:
    *   The `run_worker` script in `market_drip/worker/run_worker.py` runs as a continuous worker process.
    *   It polls the `fetch_tasks` table for pending tasks.
    *   For each task, it uses the `ClobClient` to call the CLOB API's `/prices-history` endpoint with the specified token and time range.
    *   The returned price data is then stored in the `prices` table.
    *   The worker includes robust error handling, including exponential backoff and retries for API errors, and deferring tasks when rate limited.

### Capture Frequency

*   The data capture is **not real-time**. It's a batch-oriented system designed to build a historical dataset.
*   The `sync_markets` script is run periodically to discover new markets.
*   The `run_worker` processes a queue of tasks. The frequency of data updates depends on how often the worker is run and how many tasks are in the queue.
*   The actual granularity of the price data is determined by the Polymarket CLOB API. The system fetches all available data points within the requested time range for a task.

## 3. Data Quality & Density Inspection

A direct inspection of the data was not possible as the database was empty. However, the code provides insights into the expected data quality and density.

### Expected Data Quality

*   The system is designed to be resilient. The worker's retry and backoff mechanisms suggest a focus on ensuring data is eventually fetched, even if the API is temporarily unavailable.
*   Permanent data loss for a given period could occur if a `fetch_task` is repeatedly retried and then marked as an `error`, or if the Polymarket API itself has missing data.

### Expected Data Density

*   The density of the data will be variable and will match what is available from the Polymarket API.
*   Since the system is task-based, there may be periods with no data if no tasks have been created or processed for those periods.
*   Data gaps could be identified by querying the `prices` table and looking for periods with no data for a given `token_pk`. For example, one could write a script to check for gaps larger than a certain threshold (e.g., 1 hour) between consecutive `ts` values for each token.