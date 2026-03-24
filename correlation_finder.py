# correlation_finder.py
"""
Finds interesting correlations and associations in TAMU grade distribution data.

Dependencies:
    pip install pandas numpy scipy pingouin phik seaborn matplotlib dython

Usage:
    python correlation_finder.py --db tamu_grades.db --table all_grade_distributions
"""

import argparse
import sqlite3
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.stats import spearmanr, pearsonr, kendalltau
import pingouin as pg
from phik import phik_matrix
from dython.nominal import associations


def load_grades(db_path: str, table_name: str = "tamu_grades") -> pd.DataFrame:
    """Load the grades table from SQLite into a pandas DataFrame."""
    try:
        conn = sqlite3.connect(db_path)
        query = f"SELECT * FROM {table_name}"
        df = pd.read_sql_query(query, conn)
        conn.close()
        print(f"Loaded {len(df):,} rows from {table_name}")
        return df
    except Exception as e:
        print(f"Error reading database: {e}")
        return pd.DataFrame()


def prepare_data(df: pd.DataFrame) -> pd.DataFrame:
    """Light cleaning + type conversion + derived columns useful for correlations."""
    df = df.copy()

    # Convert grade counts to numeric
    grade_cols = ['A', 'B', 'C', 'D', 'F', 'I', 'S', 'U', 'Q', 'X', 'Total', 'Total A-F']
    for col in grade_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

    # GPA & percentages
    df['GPA'] = pd.to_numeric(df['GPA'], errors='coerce')
    df['Pct_A'] = (df['A'] / df['Total A-F'].replace(0, np.nan) * 100).round(1)
    df['Pct_graded'] = (df['Total A-F'] / df['Total'].replace(0, np.nan) * 100).round(1)
    df['Class_Size'] = df['Total'].astype('Int64')

    # Year → numeric
    if 'Year' in df.columns:
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').astype('Int64')

    # Drop rows that are probably totals/headers
    df = df[~df['Section'].astype(str).str.contains('total|course total|page|instructor',
                                                    case=False, na=False)]

    return df


def numeric_correlations(df: pd.DataFrame):
    """Pearson, Spearman, Kendall on numeric columns."""
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if len(num_cols) < 2:
        print("Not enough numeric columns for correlation.")
        return

    print("\n=== Spearman correlations (robust to non-normal data) ===")
    spearman = df[num_cols].corr(method='spearman').round(3)
    print(spearman.style.background_gradient(cmap='RdBu', vmin=-1, vmax=1))

    print("\n=== Top interesting Spearman pairs (abs(r) > 0.4) ===")
    corr_unstack = spearman.abs().unstack().sort_values(ascending=False)
    high_corr = corr_unstack[(corr_unstack < 1) & (corr_unstack > 0.4)].drop_duplicates()
    print(high_corr.head(15))


def mixed_type_associations(df: pd.DataFrame):
    """Use phik or dython for categorical + numerical associations."""
    print("\n=== Phik correlation matrix (handles mixed types) ===")
    phik_corr = df.phik_matrix().round(3)
    print(phik_corr.style.background_gradient(cmap='viridis', vmin=0, vmax=1))

    print("\n=== Dython associations heatmap (visual) ===")
    associations(
        df,
        nominal_columns='auto',
        mark_columns=True,
        nom_nom_assoc='theil',
        plot=True,
        filename='associations_heatmap.png',
        figsize=(12, 10)
    )
    print("Heatmap saved to: associations_heatmap.png")


def instructor_analysis(df: pd.DataFrame):
    """Quick instructor-level aggregates — often reveal strange patterns."""
    print("\n=== Instructor aggregates (sorted by mean GPA) ===")
    agg = df.groupby('Instructor').agg({
        'GPA': ['mean', 'count'],
        'Total': 'sum',
        'Pct_A': 'mean',
        'Class_Size': 'mean'
    }).round(2)
    agg.columns = ['_'.join(col).strip() for col in agg.columns.values]
    agg = agg.sort_values('GPA_mean', ascending=False)
    print(agg.head(20))


def main():
    parser = argparse.ArgumentParser(description="Find correlations in TAMU grade data")
    parser.add_argument('--db', default='tamu_grades.db', help='SQLite database path')
    parser.add_argument('--table', default='all_grade_distributions', help='Table name')
    args = parser.parse_args()

    df = load_grades(args.db, args.table)
    if df.empty:
        print("No data loaded — exiting.")
        return

    df = prepare_data(df)

    print("\nData shape:", df.shape)
    print("Columns:", list(df.columns))

    numeric_correlations(df)
    mixed_type_associations(df)
    instructor_analysis(df)


if __name__ == '__main__':
    main()