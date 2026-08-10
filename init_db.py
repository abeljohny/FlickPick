#!/usr/bin/env python3
"""
Initialize FlickPick database with sample data.

Usage:
    python init_db.py              # Run initialization
    python init_db.py --check      # Check if data exists without inserting
    python init_db.py --force      # Drop all data and reinitialize
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Add parent directory to path to import lakebase
# In Databricks, __file__ is not defined, so use current working directory
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Running in Databricks notebook context
    script_dir = "/Workspace/Users/abel.johny@proton.me/FlickPick"

sys.path.insert(0, script_dir)

import lakebase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def check_data_exists() -> dict:
    """Check if tables have data."""
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            counts = {}
            tables = ['users', 'groups', 'group_members', 'movies', 'watchlist', 'ratings', 'recommendations']
            
            for table in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = cur.fetchone()[0]
                except Exception as e:
                    logger.warning(f"Could not check {table}: {e}")
                    counts[table] = None
            
            return counts


def clear_all_data():
    """Clear all data from tables (keeps schema)."""
    logger.info("Clearing all existing data...")
    
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            # Delete in reverse order of dependencies
            tables = ['recommendations', 'ratings', 'watchlist', 'group_members', 
                     'movies', 'groups', 'users']
            
            for table in tables:
                try:
                    cur.execute(f"DELETE FROM {table}")
                    logger.info(f"  Cleared {table}")
                except Exception as e:
                    logger.warning(f"  Could not clear {table}: {e}")
            
            conn.commit()


def load_initial_data():
    """Load initial data from SQL file."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = "/Workspace/Users/abel.johny@proton.me/FlickPick"
    
    sql_file = os.path.join(script_dir, 'initial_data.sql')
    
    if not os.path.exists(sql_file):
        logger.error(f"SQL file not found: {sql_file}")
        return False
    
    logger.info(f"Loading data from {sql_file}...")
    
    with open(sql_file, 'r') as f:
        sql = f.read()
    
    # Split into individual statements (skip comments and empty lines)
    statements = []
    current = []
    
    for line in sql.split('\n'):
        stripped = line.strip()
        
        # Skip comment-only lines and section separators
        if not stripped or stripped.startswith('--'):
            continue
        
        current.append(line)
        
        # Execute when we hit a semicolon
        if stripped.endswith(';'):
            stmt = '\n'.join(current).strip()
            if stmt and not stmt.startswith('--'):
                statements.append(stmt)
            current = []
    
    with lakebase.get_connection() as conn:
        with conn.cursor() as cur:
            success_count = 0
            skip_count = 0
            
            for stmt in statements:
                try:
                    cur.execute(stmt)
                    conn.commit()
                    success_count += 1
                except Exception as e:
                    # Expected for ON CONFLICT DO NOTHING when data exists
                    skip_count += 1
                    logger.debug(f"Statement skipped (likely duplicate): {str(e)[:100]}")
                    conn.rollback()
            
            logger.info(f"  Executed {success_count} statements, {skip_count} skipped")
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Initialize FlickPick database")
    parser.add_argument('--check', action='store_true', help='Check data without inserting')
    parser.add_argument('--force', action='store_true', help='Clear existing data first')
    args = parser.parse_args()
    
    # Ensure schema exists
    logger.info("Ensuring database schema exists...")
    lakebase.ensure_flickpick_tables()
    lakebase.ensure_movie_tables()
    
    # Check current state
    counts = check_data_exists()
    logger.info("Current data counts:")
    for table, count in counts.items():
        if count is not None:
            logger.info(f"  {table}: {count} rows")
        else:
            logger.info(f"  {table}: N/A (table may not exist)")
    
    if args.check:
        return
    
    # Clear data if --force
    if args.force:
        clear_all_data()
    
    # Load data
    logger.info("Loading initial data...")
    if load_initial_data():
        logger.info("✓ Database initialized successfully")
        
        # Show final counts
        counts = check_data_exists()
        logger.info("\nFinal data counts:")
        for table, count in counts.items():
            if count is not None:
                logger.info(f"  {table}: {count} rows")
    else:
        logger.error("✗ Failed to initialize database")
        sys.exit(1)


if __name__ == "__main__":
    main()
