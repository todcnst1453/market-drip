import argparse
import os
import sqlite3
import pandas as pd

def extract_soccer_data(db_path, output_path):
    """
    Connects to the SQLite database, extracts soccer-related market data,
    and saves it to a Parquet file.
    """
    print(f"Connecting to database: {db_path}")
    con = sqlite3.connect(db_path)
    
    query = """
    SELECT
        m.slug,
        m.question,
        m.status,
        m.end_ts,
        t.outcome_name,
        p.ts AS price_timestamp,
        p.price_bp
    FROM markets m
    JOIN tokens t ON m.market_pk = t.market_pk
    JOIN prices p ON t.token_pk = p.token_pk
    WHERE
        m.slug LIKE '%soccer%' OR
        m.slug LIKE '%football%' OR
        m.slug LIKE '%fc%' OR
        m.slug LIKE '%united%' OR
        m.question LIKE '%soccer%' OR
        m.question LIKE '%football%' OR
        m.question LIKE '%fc%' OR
        m.question LIKE '%united%';
    """
    
    print("Executing query to extract soccer data...")
    df = pd.read_sql_query(query, con)
    con.close()
    
    print(f"Extracted {len(df)} rows of soccer data.")
    
    if not df.empty:
        print(f"Saving data to {output_path} with snappy compression...")
        df.to_parquet(output_path, compression='snappy', index=False)
        print("Data saved successfully.")
    else:
        print("No data to save.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract soccer market data to Parquet.")
    parser.add_argument(
        "--db_path",
        default=os.getenv('PROD_DB_PATH', "tmp/mock_production.db"),
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--output_path",
        default="tmp/soccer_data.parquet",
        help="Path to save the output Parquet file.",
    )
    args = parser.parse_args()
    
    extract_soccer_data(args.db_path, args.output_path)
