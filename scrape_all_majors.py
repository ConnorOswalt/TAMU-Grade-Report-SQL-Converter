"""
scrape_all_majors.py - Discover and scrape ALL TAMU undergraduate majors
from the official catalog (catalog.tamu.edu), then parse and store in SQLite.

This script:
1. Dynamically discovers all bachelor program URLs from the TAMU catalog index
2. Fetches the HTML for each program
3. Parses the degree-plan grids into a tidy DataFrame
4. Stores the results in SQLite (degree_plan_courses and degree_plan_footnotes tables)
5. Exports to Parquet for Databricks

No hardcoded DEGREE_PLAN_SOURCES needed -- this script scales to 140+ majors.
"""

import logging
import sqlite3
from typing import Optional

import pandas as pd

from config import SQLITE_DB_PATH, PARQUET_DIR
from degree_plan_normalizer import parse_multiple
from degree_plan_scraper import discover_bachelor_programs, fetch_all
from sql_handler import connect_to_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def store_degree_plans_in_db(
    plan_df: pd.DataFrame,
    footnotes_df: pd.DataFrame,
    db_path: str = str(SQLITE_DB_PATH),
) -> None:
    """Insert degree plan courses and footnotes into SQLite database."""
    conn = connect_to_db(db_path)
    cursor = conn.cursor()

    try:
        # Create tables if they don't exist
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS degree_plan_courses (
                major TEXT,
                year_label TEXT,
                term TEXT,
                row_order INTEGER,
                row_type TEXT,
                choice_group_id INTEGER,
                course_subject TEXT,
                course_number TEXT,
                course_code_raw TEXT,
                title TEXT,
                footnote_refs TEXT,
                credit_hours_raw TEXT,
                credit_hours_min REAL,
                credit_hours_max REAL,
                credit_hours REAL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS degree_plan_footnotes (
                major TEXT,
                footnote_number TEXT,
                footnote_text TEXT
            )
            """
        )

        # Clear existing data for the majors we're inserting
        majors_to_insert = list(plan_df["major"].unique()) if not plan_df.empty else []
        if len(majors_to_insert) > 0:
            placeholders = ",".join(["?"] * len(majors_to_insert))
            cursor.execute(f"DELETE FROM degree_plan_courses WHERE major IN ({placeholders})", majors_to_insert)
            cursor.execute(f"DELETE FROM degree_plan_footnotes WHERE major IN ({placeholders})", majors_to_insert)

        # Insert degree plans
        if not plan_df.empty:
            plan_df.to_sql("degree_plan_courses", conn, if_exists="append", index=False)
            logger.info(f"Inserted {len(plan_df)} course rows into degree_plan_courses")

        # Insert footnotes
        if not footnotes_df.empty:
            footnotes_df.to_sql("degree_plan_footnotes", conn, if_exists="append", index=False)
            logger.info(f"Inserted {len(footnotes_df)} footnote rows into degree_plan_footnotes")

        conn.commit()
        logger.info("Successfully committed degree plan data to database")

    except Exception as e:
        conn.rollback()
        logger.error(f"Error storing degree plans: {e}")
        raise
    finally:
        conn.close()


def export_degree_plans_to_parquet(
    plan_df: pd.DataFrame,
    footnotes_df: pd.DataFrame,
) -> None:
    """Export parsed degree plans to partitioned Parquet files."""
    if plan_df.empty:
        logger.warning("Degree plan DataFrame is empty -- skipping Parquet export")
        return

    # Export courses partitioned by major
    out_dir_courses = PARQUET_DIR / "degree_plan_courses"
    plan_df.to_parquet(out_dir_courses, partition_cols=["major"], index=False)
    logger.info(f"Exported {len(plan_df)} degree plan rows to {out_dir_courses}")

    # Export footnotes
    if not footnotes_df.empty:
        out_dir_footnotes = PARQUET_DIR / "degree_plan_footnotes"
        footnotes_df.to_parquet(out_dir_footnotes, index=False)
        logger.info(f"Exported {len(footnotes_df)} footnote rows to {out_dir_footnotes}")


def main(force_refresh: bool = False) -> None:
    """
    Main pipeline: discover, fetch, parse, and store all TAMU undergraduate majors.
    
    Args:
        force_refresh: If True, re-download all HTML even if cached. Default: False (use cache).
    """
    logger.info("=" * 80)
    logger.info("TAMU All-Majors Scraper Pipeline")
    logger.info("=" * 80)

    # Step 1: Discover all bachelor programs
    logger.info("\n[Step 1/4] Discovering all bachelor programs from catalog.tamu.edu...")
    try:
        discovered_programs = discover_bachelor_programs()
        logger.info(f"✓ Discovered {len(discovered_programs)} bachelor programs")
        for major, url in sorted(discovered_programs.items()):
            logger.info(f"  - {major}")
    except Exception as e:
        logger.error(f"Failed to discover programs: {e}")
        raise

    # Step 2: Fetch HTML for all majors
    logger.info(f"\n[Step 2/4] Fetching degree plan HTML for {len(discovered_programs)} majors...")
    try:
        pages = fetch_all(sources=discovered_programs, force_refresh=force_refresh)
        logger.info(f"✓ Successfully fetched {len(pages)} of {len(discovered_programs)} degree plan pages")
        if len(pages) < len(discovered_programs):
            failed = set(discovered_programs.keys()) - set(pages.keys())
            logger.warning(f"  Failed to fetch: {failed}")
    except Exception as e:
        logger.error(f"Failed to fetch degree plans: {e}")
        raise

    # Step 3: Parse HTML into structured DataFrames
    logger.info(f"\n[Step 3/4] Parsing degree plan HTML for {len(pages)} majors...")
    try:
        plan_df, footnotes_dict = parse_multiple(pages)
        
        # Convert footnotes dictionary to DataFrame: {major: {number: text}}
        footnotes_rows = []
        for major, footnotes in footnotes_dict.items():
            for number, text in footnotes.items():
                footnotes_rows.append({"major": major, "footnote_number": number, "footnote_text": text})
        footnotes_df = pd.DataFrame(footnotes_rows)
        
        logger.info(f"✓ Parsed {len(plan_df)} course rows and {len(footnotes_df)} footnote rows")
        logger.info(f"  Majors in plan_df: {sorted(plan_df['major'].unique())}")
    except Exception as e:
        logger.error(f"Failed to parse degree plans: {e}")
        raise

    # Step 4a: Store in SQLite
    logger.info(f"\n[Step 4/4a] Storing parsed degree plans in SQLite database...")
    try:
        store_degree_plans_in_db(plan_df, footnotes_df)
        logger.info("✓ Successfully stored in SQLite")
    except Exception as e:
        logger.error(f"Failed to store in SQLite: {e}")
        raise

    # Step 4b: Export to Parquet for Databricks
    logger.info(f"\n[Step 4/4b] Exporting parsed degree plans to Parquet...")
    try:
        export_degree_plans_to_parquet(plan_df, footnotes_df)
        logger.info("✓ Successfully exported to Parquet")
    except Exception as e:
        logger.error(f"Failed to export to Parquet: {e}")
        raise

    logger.info("\n" + "=" * 80)
    logger.info(f"✓ PIPELINE COMPLETE: {len(pages)} majors scraped, parsed, and stored")
    logger.info("=" * 80)
    logger.info(f"\nNext steps:")
    logger.info(f"  1. Query SQLite: sqlite3 {SQLITE_DB_PATH} 'SELECT DISTINCT major FROM degree_plan_courses'")
    logger.info(f"  2. Run ranking & optimizer: python export_for_databricks.py")
    logger.info(f"  3. Upload Parquet to Databricks: {PARQUET_DIR}")


if __name__ == "__main__":
    import sys
    force_refresh = "--force-refresh" in sys.argv
    main(force_refresh=force_refresh)
