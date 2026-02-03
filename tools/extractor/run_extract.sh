#!/bin/bash
# Set the path to your massive production DB here
export PROD_DB_PATH="/path/to/your/real_production_database.sqlite3"
     
echo "Starting Soccer Data Extraction..."
python3 soccer_harvester.py
echo "Extraction Complete. Check tmp/soccer_data.parquet"
