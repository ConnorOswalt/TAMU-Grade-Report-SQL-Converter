"""
major_difficulty_ranker.py - Joins the degree-plan course lists (from
degree_plan_normalizer.py) with historical course grade distributions (from
the main grd ETL pipeline) to estimate an "expected GPA" per major, assuming a
student follows the catalog's default semester-by-semester plan.

Grade data schema assumed (table 'all_grade_distributions', built by main.py):
    Class Code  -- e.g. "MATH-151" (Subject-Number, split from the PDF's
                   original "Section" column by replace_section_with_split)
    GPA         -- term GPA for that course/section
    Total       -- total students graded, used as a weight

Validated against real ingested grade data (105k+ rows, 2017-2025). One thing
to watch for: TAMU sometimes renames a department's course subject code over
time (e.g. Psychology's prefix changed from PSYC to PBSI), so a current
degree plan may reference a subject code that never appears in older grade
PDFs. SUBJECT_ALIASES below maps a plan's subject code to the code(s) it may
appear as historically -- add entries here as you discover more renames.
"""

from typing import Optional

import pandas as pd

from config import SQLITE_DB_PATH
from sql_handler import connect_to_db, table_exists

NON_COURSE_ROW_TYPES = {"term_subtotal", "plan_total", "choice_header"}

# Plan subject code -> historical subject code(s) it may appear as in grade data
SUBJECT_ALIASES = {
    "PBSI": ["PSYC"],
}


def load_course_gpa(
    db_path: str = str(SQLITE_DB_PATH),
    table_name: str = "all_grade_distributions",
) -> pd.DataFrame:
    """
    Load and aggregate historical GPA per course (Subject + Course Number),
    weighted by number of students graded.

    Returns columns: course_subject, course_number, mean_gpa, n_students
    """
    conn = connect_to_db(db_path)
    try:
        if not table_exists(conn, table_name):
            print(f"Warning: table '{table_name}' not found in {db_path} -- no grade data loaded")
            return pd.DataFrame(columns=["course_subject", "course_number", "mean_gpa", "n_students"])

        raw = pd.read_sql(f"SELECT * FROM {table_name}", conn)
    finally:
        conn.close()

    if raw.empty or "Class Code" not in raw.columns or "GPA" not in raw.columns:
        print("Warning: grade table missing expected 'Class Code'/'GPA' columns -- check main.py's schema")
        return pd.DataFrame(columns=["course_subject", "course_number", "mean_gpa", "n_students"])

    split = raw["Class Code"].astype(str).str.split("-", n=1, expand=True)
    raw["course_subject"] = split[0].str.strip().str.upper()
    raw["course_number"] = split[1].str.strip().str.upper() if split.shape[1] > 1 else None

    raw["GPA"] = pd.to_numeric(raw["GPA"], errors="coerce")
    weight_col = "Total" if "Total" in raw.columns else None
    raw["_weight"] = pd.to_numeric(raw[weight_col], errors="coerce") if weight_col else 1.0
    raw["_weight"] = raw["_weight"].fillna(0)

    raw = raw.dropna(subset=["GPA", "course_subject", "course_number"])
    raw = raw[raw["_weight"] > 0]

    if raw.empty:
        return pd.DataFrame(columns=["course_subject", "course_number", "mean_gpa", "n_students"])

    raw["_weighted_gpa"] = raw["GPA"] * raw["_weight"]
    agg = raw.groupby(["course_subject", "course_number"]).agg(
        _weighted_gpa_sum=("_weighted_gpa", "sum"),
        n_students=("_weight", "sum"),
    )
    agg["mean_gpa"] = agg["_weighted_gpa_sum"] / agg["n_students"]
    return agg.reset_index()[["course_subject", "course_number", "mean_gpa", "n_students"]]


def attach_course_gpa(
    plan_df: pd.DataFrame,
    course_gpa_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Left-join course-level mean GPA onto each plan row that names a specific
    course. Falls back to SUBJECT_ALIASES when a plan's subject code has no
    direct match (e.g. a renamed department prefix).
    """
    merged = plan_df.merge(
        course_gpa_df,
        on=["course_subject", "course_number"],
        how="left",
    )

    unmatched = merged["mean_gpa"].isna() & merged["course_subject"].notna()
    for plan_subject, historical_subjects in SUBJECT_ALIASES.items():
        mask = unmatched & (merged["course_subject"] == plan_subject)
        if not mask.any():
            continue

        alias_gpa = course_gpa_df[course_gpa_df["course_subject"].isin(historical_subjects)]
        alias_lookup = alias_gpa.set_index("course_number")[["mean_gpa", "n_students"]]

        matched_numbers = merged.loc[mask, "course_number"].map(alias_lookup["mean_gpa"])
        merged.loc[mask, "mean_gpa"] = matched_numbers
        merged.loc[mask, "n_students"] = merged.loc[mask, "course_number"].map(alias_lookup["n_students"])

    return merged


def _resolve_choice_group_gpa(group: pd.DataFrame) -> Optional[float]:
    """
    For a "Select one of the following" block, approximate the credit-weighted
    GPA contribution as the average GPA across the named options that have
    grade data (not the best/easiest option -- see README caveat).
    """
    options = group[group["row_type"] == "choice_option"]
    matched = options.dropna(subset=["mean_gpa"])
    if matched.empty:
        return None
    return matched["mean_gpa"].mean()


def compute_major_expected_gpa(merged_df: pd.DataFrame) -> pd.DataFrame:
    """
    Roll up a merged (plan + GPA) DataFrame into one row per major with a
    credit-hour-weighted expected GPA, plus coverage stats.
    """
    results = []

    for major, major_df in merged_df.groupby("major"):
        weighted_sum = 0.0
        weight_total = 0.0
        matched_hours = 0.0
        total_course_hours = 0.0

        # Plain required courses
        courses = major_df[major_df["row_type"] == "course"]
        for _, row in courses.iterrows():
            hours = row.get("credit_hours") or 0
            total_course_hours += hours
            if pd.notna(row.get("mean_gpa")):
                weighted_sum += row["mean_gpa"] * hours
                weight_total += hours
                matched_hours += hours

        # Choice blocks: use the choice_header's credit hours, average GPA of its options
        headers = major_df[major_df["row_type"] == "choice_header"]
        for _, header_row in headers.iterrows():
            group_id = header_row["choice_group_id"]
            group_rows = major_df[major_df["choice_group_id"] == group_id]
            hours = header_row.get("credit_hours") or 0
            total_course_hours += hours
            gpa = _resolve_choice_group_gpa(group_rows)
            if gpa is not None:
                weighted_sum += gpa * hours
                weight_total += hours
                matched_hours += hours

        expected_gpa = weighted_sum / weight_total if weight_total > 0 else None
        coverage = matched_hours / total_course_hours if total_course_hours > 0 else 0

        results.append(
            {
                "major": major,
                "expected_gpa": expected_gpa,
                "matched_credit_hours": matched_hours,
                "total_course_credit_hours": total_course_hours,
                "coverage_pct": round(coverage * 100, 1),
            }
        )

    out = pd.DataFrame(results).sort_values("expected_gpa", ascending=False, na_position="last")
    return out.reset_index(drop=True)


def rank_majors(
    plan_df: pd.DataFrame,
    db_path: str = str(SQLITE_DB_PATH),
    grade_table: str = "all_grade_distributions",
) -> pd.DataFrame:
    """End-to-end: attach historical GPA to a degree-plan DataFrame and rank majors."""
    course_gpa_df = load_course_gpa(db_path, grade_table)
    merged = attach_course_gpa(plan_df, course_gpa_df)
    return compute_major_expected_gpa(merged)


if __name__ == "__main__":
    from degree_plan_scraper import fetch_all
    from degree_plan_normalizer import parse_multiple

    pages = fetch_all()
    plan_df, _ = parse_multiple(pages)

    ranking = rank_majors(plan_df)
    print(ranking.to_string(index=False))

    if (ranking["coverage_pct"] < 50).any():
        low = ranking[ranking["coverage_pct"] < 50]["major"].tolist()
        print(
            f"\nWarning: low course-match coverage for {low} -- their plan "
            "courses may use subject codes not present in "
            "'all_grade_distributions', or that table may be empty/stale. "
            "Treat their rankings as unreliable until investigated."
        )
