#!/usr/bin/env python3
"""
Quick diagnostic test for FlickPick backend.
Run this to verify database connectivity and table setup.
"""
from __future__ import annotations

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lakebase import get_connection

def test_connection():
    """Test database connection."""
    print("Testing database connection...")
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
                print(f"✓ Connected to PostgreSQL: {version}")
                return True
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

def test_tables():
    """Check if all required tables exist and have data."""
    print("\nChecking tables...")
    tables = ['users', 'groups', 'group_members', 'movies', 'watchlist', 'ratings', 'recommendations']
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for table in tables:
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cur.fetchone()[0]
                        print(f"  {table}: {count} rows")
                    except Exception as e:
                        print(f"  {table}: ✗ Error - {e}")
                        return False
        return True
    except Exception as e:
        print(f"✗ Table check failed: {e}")
        return False

def test_groups_endpoint():
    """Test the /api/groups query."""
    print("\nTesting /api/groups query...")
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, created_at FROM groups ORDER BY name")
                groups = cur.fetchall()
                print(f"✓ Found {len(groups)} groups:")
                for g in groups:
                    print(f"  - {g['name']} (id: {g['id']})")
                return True
    except Exception as e:
        print(f"✗ Groups query failed: {e}")
        return False

def test_watchlist_query():
    """Test the watchlist query."""
    print("\nTesting watchlist query...")
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        w.id,
                        w.movie_id,
                        m.title,
                        m.poster_path,
                        w.watched_at
                    FROM watchlist w
                    JOIN movies m ON w.movie_id = m.id
                    JOIN users u ON w.added_by_user_id = u.id
                    WHERE w.group_id = 1
                    ORDER BY w.created_at DESC
                """)
                items = cur.fetchall()
                print(f"✓ Found {len(items)} watchlist items for group 1:")
                for item in items:
                    status = "watched" if item['watched_at'] else "queued"
                    print(f"  - {item['title']} ({status})")
                return True
    except Exception as e:
        print(f"✗ Watchlist query failed: {e}")
        print(f"   This is the main issue causing the 500 error!")
        return False

def main():
    print("=" * 60)
    print("FlickPick Backend Diagnostic Test")
    print("=" * 60)
    
    all_passed = True
    
    all_passed &= test_connection()
    all_passed &= test_tables()
    all_passed &= test_groups_endpoint()
    all_passed &= test_watchlist_query()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed! Backend should work correctly.")
        print("\nNext steps:")
        print("1. If the app is running, restart it for the fixes to take effect")
        print("2. Reload the web page")
    else:
        print("✗ Some tests failed. Fix the issues above first.")
        print("\nTroubleshooting:")
        print("1. Run: python init_db.py --force")
        print("2. Check database connection settings in secrets")
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
