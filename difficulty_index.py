"""
difficulty_index.py - Extends major_difficulty_ranker with failure- and
drop-rate signals, not just raw GPA -- capturing the original idea that
"harder classes have higher rates of failure and dropping" in addition to
lower grades.

fail_rate = F / (Total A-F)   -- share of *graded* students who failed
drop_rate = (Q + X) / Total   -- share of *all enrolled* students who dropped

Rolls up to a per-major, credit-hour-weighted difficulty_score: a 0-100
composite of (low GPA, high fail rate, high drop rate), each z-scored across
majors then averaged and min-max rescaled. 100 = hardest major in the set,
0 = easiest -- it's a relative ranking within this major list, not an
absolute scale.
"""

from typing import Optional

import pandas as pd

from config import SQLITE_DB_PATH
from major_difficulty_ranker import SUBJECT_ALIASES
from sql_handler import connect_to_db, table_exists

STATS_COLUMNS = ["course_subject", "course_number", "mean_gpa", "fail_rate", "drop_rate", "n_students"]
_REQUIRED_RAW_COLUMNS = {"Class Code", "GPA", "F", "Total A-F", "Q", "X", "Total"}


def load_course_stats(
    db_path: str = str(SQLITE_DB_PATH),
    table_name: str = "all_grade_distributions",
) -> pd.DataFrame:
    """Weighted per-course mean GPA, fail rate, and drop rate."""
    conn = connect_to_db(db_path)
    try:
        if not table_exists(conn, table_name):
            print(f"Warning: table '{table_name}' not found in {db_path} -- no grade data loaded")
            return pd.DataFrame(columns=STATS_COLUMNS)
        raw = pd.read_sql(f"SELECT * FROM {table_name}", conn)
    finally:
        conn.close()

    if raw.empty or not _REQUIRED_RAW_COLUMNS.issubset(raw.columns):
        print("Warning: grade table missing columns needed for fail/drop rates")
        return pd.DataFrame(columns=STATS_COLUMNS)

    split = raw["Class Code"].astype(str).str.split("-", n=1, expand=True)
    raw["course_subject"] = split[0].str.strip().str.upper()
    raw["course_number"] = split[1].str.strip().str.upper() if split.shape[1] > 1 else None

    for col in ["GPA", "F", "Total A-F", "Q", "X", "Total"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")

    raw = raw.dropna(subset=["course_subject", "course_number", "Total"])
    raw = raw[raw["Total"] > 0]
    if raw.empty:
        return pd.DataFrame(columns=STATS_COLUMNS)

    raw["_gpa_weight"] = raw["Total"].where(raw["GPA"].notna(), 0)
    raw["_weighted_gpa"] = raw["GPA"].fillna(0) * raw["_gpa_weight"]

    agg = raw.groupby(["course_subject", "course_number"]).agg(
        _weighted_gpa_sum=("_weighted_gpa", "sum"),
        _gpa_weight_sum=("_gpa_weight", "sum"),
        F_sum=("F", "sum"),
        total_af_sum=("Total A-F", "sum"),
        Q_sum=("Q", "sum"),
        X_sum=("X", "sum"),
        n_students=("Total", "sum"),
    )
    agg["mean_gpa"] = agg["_weighted_gpa_sum"] / agg["_gpa_weight_sum"].replace(0, pd.NA)
    agg["fail_rate"] = agg["F_sum"] / agg["total_af_sum"].replace(0, pd.NA)
    agg["drop_rate"] = (agg["Q_sum"] + agg["X_sum"]) / agg["n_students"].replace(0, pd.NA)
    return agg.reset_index()[STATS_COLUMNS]


def attach_course_stats(plan_df: pd.DataFrame, stats_df: pd.DataFrame) -> pd.DataFrame:
    """Same subject-alias fallback as major_difficulty_ranker.attach_course_gpa."""
    merged = plan_df.merge(stats_df, on=["course_subject", "course_number"], how="left")

    unmatched = merged["mean_gpa"].isna() & merged["course_subject"].notna()
    metric_cols = ["mean_gpa", "fail_rate", "drop_rate", "n_students"]
    for plan_subject, historical_subjects in SUBJECT_ALIASES.items():
        mask = unmatched & (merged["course_subject"] == plan_subject)
        if not mask.any():
            continue
        alias_stats = stats_df[stats_df["course_subject"].isin(historical_subjects)]
        alias_lookup = alias_stats.set_index("course_number")[metric_cols]
        for col in metric_cols:
            merged.loc[mask, col] = merged.loc[mask, "course_number"].map(alias_lookup[col])

    return merged


def _rollup_major(major_df: pd.DataFrame) -> dict:
    weight_total = 0.0
    gpa_sum = 0.0
    fail_sum = 0.0
    drop_sum = 0.0

    courses = major_df[major_df["row_type"] == "course"]
    for _, row in courses.iterrows():
        hours = row.get("credit_hours") or 0
        if pd.notna(row.get("mean_gpa")):
            weight_total += hours
            gpa_sum += row["mean_gpa"] * hours
            fail_sum += (row.get("fail_rate") or 0) * hours
            drop_sum += (row.get("drop_rate") or 0) * hours

    headers = major_df[major_df["row_type"] == "choice_header"]
    for _, header in headers.iterrows():
        gid = header["choice_group_id"]
        hours = header.get("credit_hours") or 0
        options = major_df[(major_df["choice_group_id"] == gid) & (major_df["row_type"] == "choice_option")]
        matched = options.dropna(subset=["mean_gpa"])
        if matched.empty:
            continue
        weight_total += hours
        gpa_sum += matched["mean_gpa"].mean() * hours
        fail_sum += matched["fail_rate"].mean() * hours
        drop_sum += matched["drop_rate"].mean() * hours

    if weight_total == 0:
        return {"expected_gpa": None, "avg_fail_rate": None, "avg_drop_rate": None, "matched_credit_hours": 0.0}

    return {
        "expected_gpa": gpa_sum / weight_total,
        "avg_fail_rate": fail_sum / weight_total,
        "avg_drop_rate": drop_sum / weight_total,
        "matched_credit_hours": weight_total,
    }


def compute_major_difficulty_index(plan_df: pd.DataFrame) -> pd.DataFrame:
    """Per-major GPA/fail-rate/drop-rate rollup plus a 0-100 relative difficulty_score."""
    stats_df = load_course_stats()
    merged = attach_course_stats(plan_df, stats_df)

    rows = []
    for major, major_df in merged.groupby("major"):
        row = {"major": major}
        row.update(_rollup_major(major_df))
        rows.append(row)

    df = pd.DataFrame(rows)
    valid = df.dropna(subset=["expected_gpa", "avg_fail_rate", "avg_drop_rate"])

    def _zscore(series: pd.Series) -> pd.Series:
        std = series.std(ddof=0)
        return (series - series.mean()) / std if std > 0 else series * 0

    if len(valid) > 1:
        raw_score = _zscore(-valid["expected_gpa"]) + _zscore(valid["avg_fail_rate"]) + _zscore(valid["avg_drop_rate"])
        span = raw_score.max() - raw_score.min()
        rescaled = (raw_score - raw_score.min()) / span * 100 if span > 0 else raw_score * 0 + 50
        df.loc[valid.index, "difficulty_score"] = rescaled
    else:
        df["difficulty_score"] = None

    return df.sort_values("difficulty_score", ascending=False, na_position="last").reset_index(drop=True)


if __name__ == "__main__":
    from degree_plan_normalizer import parse_multiple
    from degree_plan_scraper import fetch_all

    pages = fetch_all()
    plan_df, _ = parse_multiple(pages)
    print(compute_major_difficulty_index(plan_df).to_string(index=False))
