"""
export_for_databricks.py - Exports the SQLite tables + derived analysis
(major difficulty ranking, Gurobi optimizer results) to partitioned Parquet
under data/parquet/, ready to upload to a Databricks Volume/DBFS path and
load as Delta tables (see databricks/major_difficulty_dashboard.sql).

This does NOT push anything to a Databricks workspace directly -- no
workspace credentials are configured in this environment. Upload the
contents of data/parquet/ via the Databricks UI (Catalog > Add Data) or the
`databricks fs cp` / `databricks-cli` once you've configured your own
DATABRICKS_HOST/DATABRICKS_TOKEN.
"""

import sqlite3

import pandas as pd

from config import PARQUET_DIR, SQLITE_DB_PATH
from course_optimizer import optimize_all_majors
from degree_plan_normalizer import parse_multiple
from degree_plan_scraper import fetch_all
from difficulty_index import compute_major_difficulty_index
from major_difficulty_ranker import rank_majors


def export_grade_distributions(db_path: str = str(SQLITE_DB_PATH)) -> None:
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql("SELECT * FROM all_grade_distributions", conn)
    finally:
        conn.close()

    if df.empty:
        print("Warning: 'all_grade_distributions' is empty -- skipping export")
        return

    # tabula occasionally leaves stray text (e.g. "-------") in numeric-looking
    # columns; coerce to numeric so pyarrow can write a consistent schema.
    numeric_cols = ["A", "B", "C", "D", "F", "Total A-F", "GPA", "I", "S", "U", "Q", "X", "Total"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    out_dir = PARQUET_DIR / "grade_distributions"
    df.to_parquet(out_dir, partition_cols=["College", "Year", "Semester"], index=False)
    print(f"Exported {len(df)} grade distribution rows to {out_dir}")


def export_degree_plans(plan_df: pd.DataFrame) -> None:
    if plan_df.empty:
        print("Warning: degree plan DataFrame is empty -- skipping export")
        return

    out_dir = PARQUET_DIR / "degree_plan_courses"
    plan_df.to_parquet(out_dir, partition_cols=["major"], index=False)
    print(f"Exported {len(plan_df)} degree plan rows to {out_dir}")


def export_analysis(plan_df: pd.DataFrame) -> None:
    ranking = rank_majors(plan_df)
    ranking_path = PARQUET_DIR / "major_expected_gpa.parquet"
    ranking.to_parquet(ranking_path, index=False)
    print(f"Exported major difficulty ranking to {ranking_path}")

    optimal_summary, selections_df = optimize_all_majors(plan_df)
    comparison = optimal_summary.merge(
        ranking[["major", "expected_gpa"]].rename(columns={"expected_gpa": "baseline_expected_gpa"}),
        on="major",
        how="left",
    )
    comparison["gpa_uplift"] = comparison["optimal_expected_gpa"] - comparison["baseline_expected_gpa"]

    comparison_path = PARQUET_DIR / "major_optimizer_comparison.parquet"
    comparison.to_parquet(comparison_path, index=False)
    print(f"Exported baseline vs. optimal comparison to {comparison_path}")

    selections_path = PARQUET_DIR / "optimizer_selected_electives.parquet"
    selections_df.to_parquet(selections_path, index=False)
    print(f"Exported optimizer elective selections to {selections_path}")

    difficulty_index = compute_major_difficulty_index(plan_df)
    difficulty_index_path = PARQUET_DIR / "major_difficulty_index.parquet"
    difficulty_index.to_parquet(difficulty_index_path, index=False)
    print(f"Exported major difficulty index (GPA + fail/drop rate) to {difficulty_index_path}")


if __name__ == "__main__":
    pages = fetch_all()
    plan_df, _ = parse_multiple(pages)

    export_grade_distributions()
    export_degree_plans(plan_df)
    export_analysis(plan_df)

    print(f"\nAll exports written under {PARQUET_DIR}")
    print("Upload this folder to a Databricks Volume/DBFS path, then run "
          "databricks/major_difficulty_dashboard.sql to build the dashboard.")
