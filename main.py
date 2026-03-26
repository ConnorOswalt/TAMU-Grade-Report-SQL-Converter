#!/usr/bin/env python3
"""
TAMU Grade Report SQL Converter + Spark/Parquet Writer
With graceful Ctrl+C handling
"""

import os
import logging
import signal
import sys
from pathlib import Path

import pandas as pd

# Project modules
from converter import grd_to_df
from sql_handler import append_df_to_db
from spark_handler import write_partitioned   # ← NEW

# ====================== GRACEFUL SHUTDOWN ======================
def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully and cleanly."""
    print("\n\n⚠️  Interrupt received (Ctrl+C). Shutting down gracefully...")

    # Add any cleanup here if needed (e.g. close Spark session)
    print("Program terminated by user.")
    sys.exit(0)


# Register the signal handler at the very beginning
signal.signal(signal.SIGINT, signal_handler)
# ============================================================


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

pdf_folder = Path('./data/pdfs/grd')
pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]


def parse_grd_filename(filename: str) -> list[str]:
    """Parse grd_YYYY_S_COLLEGE.pdf → [College, Year, Semester]"""
    base = os.path.basename(filename).removesuffix('.pdf').removesuffix('.PDF')
    parts = base.split('_')

    if len(parts) != 4 or parts[0].lower() != 'grd':
        logging.warning(f"Unexpected filename format: {filename}")
        return ["Unknown", "Unknown", "Unknown"]

    year = parts[1]
    semester_code = parts[2]
    college_code = parts[3].upper()

    semester_map = {'1': 'Spring', '2': 'Summer', '3': 'Fall'}
    semester = semester_map.get(semester_code, semester_code)

    college_map = {
        'MD': 'Medicine', 'NU': 'Nursing', 'EN': 'Engineering', 'BA': 'Business',
        'ED': 'Education', 'LA': 'Liberal Arts', 'SC': 'Science', 'AG': 'Agriculture',
        'AR': 'Architecture', 'GB': 'Bush School', 'GE': 'Geosciences',
        'GV': 'Galveston', 'QT': 'Qatar', 'VM': 'Veterinary Medicine',
    }
    college = college_map.get(college_code, college_code)

    return [college, year, semester]


def prepend_columns_with_values(df: pd.DataFrame, new_headers: list, new_values: list) -> pd.DataFrame:
    """Prepends new columns at the left with constant values."""
    if len(new_headers) != len(new_values):
        raise ValueError("new_headers and new_values must have the same length")

    if df.empty:
        return pd.DataFrame([new_values], columns=new_headers)

    new_data = pd.Series(new_values, index=new_headers)
    missing = [h for h in new_headers if h not in df.columns]

    if missing:
        new_cols = pd.DataFrame({h: [new_data[h]] * len(df) for h in missing}, index=df.index)
        df = pd.concat([new_cols, df], axis=1)

    for h in new_headers:
        if h in df.columns:
            df[h] = new_data[h]

    return df


def replace_section_with_split(df: pd.DataFrame, section_col: str = 'Section') -> pd.DataFrame:
    """Splits 'Section' into 'Class Code' and 'Section'."""
    df = df.copy()
    if section_col not in df.columns:
        return df

    col_position = df.columns.get_loc(section_col)
    split = df[section_col].astype(str).str.rsplit('-', n=1, expand=True)

    class_code = split[0].str.strip()
    new_section = split[1].str.strip().replace('', pd.NA)

    df = df.drop(columns=[section_col])
    df.insert(col_position, 'Class Code', class_code)
    df.insert(col_position + 1, 'Section', new_section)

    return df


if __name__ == "__main__":
    if not pdf_files:
        logging.error(f"No PDF files found in: {pdf_folder}")
        sys.exit(1)

    logging.info(f"Found {len(pdf_files)} PDF file(s) in {pdf_folder}")
    pdf_files.sort()

    for idx, pdf_filename in enumerate(pdf_files, 1):
        pdf_path = pdf_folder / pdf_filename
        logging.info(f"[{idx}/{len(pdf_files)}] Processing: {pdf_filename}")

        try:
            # === Original conversion logic ===
            df = grd_to_df(pdf_path)

            if df.empty:
                logging.warning("  → Empty DataFrame — skipping")
                continue

            # Add metadata columns
            df = prepend_columns_with_values(
                df,
                ["College", "Year", "Semester"],
                parse_grd_filename(pdf_filename)
            )

            # Split Section column
            df = replace_section_with_split(df, section_col='Section')

            # === SQLite append ===
            success = append_df_to_db(df, table_name="all_grade_distributions")

            if success:
                logging.info(f"  → SQLite: {len(df)} rows appended")
            else:
                logging.warning("  → SQLite append failed")

            # === Spark / Parquet / Delta Lake write ===
            write_partitioned(
                df=df,
                table_name="grade_distribution",
                mode="append"
            )

        except KeyboardInterrupt:
            logging.warning(f"  → Processing interrupted by user during {pdf_filename}")
            print("\nProgram interrupted by user (Ctrl+C). Exiting gracefully...")
            sys.exit(0)
        except Exception as e:
            logging.error(f"  → Error processing {pdf_filename}: {e}")

    logging.info("\nAll PDFs processed successfully!")