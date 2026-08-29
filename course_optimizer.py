"""
course_optimizer.py - Uses Gurobi to pick the optimal elective/choice-group
selections within a major's degree plan to maximize expected GPA, given the
same historical course-GPA data used by major_difficulty_ranker.py.

Each "Select one of the following" block in a degree plan (choice_group_id)
becomes a set of binary decision variables with an "exactly one" constraint.
Required (non-choice) courses are fixed and contribute a constant to the
objective. A course that appears as an option in more than one choice group
(cross-listed / shared electives) can only be selected once across the whole
plan -- this is what keeps the model a genuine joint optimization rather than
independent per-group argmax.

"requirement_block" rows (e.g. "Science elective") aren't optimized since we
don't have the actual candidate course list -- they're excluded from both the
baseline and optimal GPA denominators so the before/after comparison is
apples-to-apples.
"""

from typing import Optional, Tuple

import gurobipy as gp
import pandas as pd
from gurobipy import GRB

from config import SQLITE_DB_PATH
from major_difficulty_ranker import attach_course_gpa, load_course_gpa


def _credit_hours(row: pd.Series) -> float:
    value = pd.to_numeric(row.get("credit_hours"), errors="coerce")
    return float(value) if pd.notna(value) and value > 0 else 0.0


def _fixed_course_contribution(major_df: pd.DataFrame) -> Tuple[float, float]:
    """Sum (gpa*hours, hours) across required courses that have grade data."""
    weighted_sum = 0.0
    matched_hours = 0.0
    for _, row in major_df[major_df["row_type"] == "course"].iterrows():
        hours = _credit_hours(row)
        gpa = row.get("mean_gpa")
        if pd.notna(gpa):
            weighted_sum += gpa * hours
            matched_hours += hours
    return weighted_sum, matched_hours


def optimize_major_plan(
    plan_df: pd.DataFrame,
    major: str,
    db_path: str = str(SQLITE_DB_PATH),
    course_gpa_df: Optional[pd.DataFrame] = None,
) -> Tuple[Optional[dict], pd.DataFrame]:
    """
    Solve the choice-group selection MILP for one major.

    Returns (summary_dict, selections_df). summary_dict is None if the major
    has no matchable data at all.
    """
    if course_gpa_df is None:
        course_gpa_df = load_course_gpa(db_path)
    major_df = attach_course_gpa(plan_df[plan_df["major"] == major].copy(), course_gpa_df)

    model = gp.Model(f"course_optimizer_{major}")
    model.Params.OutputFlag = 0

    objective = gp.LinExpr()
    fixed_weighted_sum, fixed_hours = _fixed_course_contribution(major_df)
    objective += fixed_weighted_sum
    weight_total = fixed_hours

    course_vars_by_key = {}  # (subject, number) -> list of gurobi Vars (for dedupe constraint)
    group_option_vars = {}   # choice_group_id -> [(var, option_row)]

    headers = major_df[major_df["row_type"] == "choice_header"]
    for _, header in headers.iterrows():
        gid = header["choice_group_id"]
        hours = _credit_hours(header)
        options = major_df[(major_df["choice_group_id"] == gid) & (major_df["row_type"] == "choice_option")]

        option_vars = []
        for i, (_, opt) in enumerate(options.iterrows()):
            var = model.addVar(vtype=GRB.BINARY, name=f"g{gid}_{i}")
            option_vars.append((var, opt))
            key = (opt.get("course_subject"), opt.get("course_number"))
            course_vars_by_key.setdefault(key, []).append(var)

            gpa = opt.get("mean_gpa")
            if pd.notna(gpa):
                objective += var * gpa * hours

        if option_vars:
            model.addConstr(gp.quicksum(v for v, _ in option_vars) == 1, name=f"choice_group_{gid}")
            group_option_vars[gid] = option_vars
            if options["mean_gpa"].notna().any():
                weight_total += hours

    # A course offered as an option in multiple choice groups can only be picked once
    for key, vars_list in course_vars_by_key.items():
        if key != (None, None) and len(vars_list) > 1:
            model.addConstr(gp.quicksum(vars_list) <= 1, name=f"dedupe_{key}")

    if weight_total == 0:
        print(f"Warning: no matchable grade data for '{major}' -- skipping optimization")
        return None, pd.DataFrame()

    model.setObjective(objective, GRB.MAXIMIZE)
    model.optimize()

    if model.Status != GRB.OPTIMAL:
        print(f"Warning: Gurobi did not find an optimal solution for '{major}' (status {model.Status})")
        return None, pd.DataFrame()

    selections = []
    for gid, option_vars in group_option_vars.items():
        for var, opt in option_vars:
            if var.X > 0.5:
                selections.append(
                    {
                        "major": major,
                        "choice_group_id": gid,
                        "course_subject": opt.get("course_subject"),
                        "course_number": opt.get("course_number"),
                        "title": opt.get("title"),
                        "mean_gpa": opt.get("mean_gpa"),
                    }
                )

    summary = {
        "major": major,
        "optimal_expected_gpa": objective.getValue() / weight_total,
        "matched_credit_hours": weight_total,
        "num_choice_groups": len(group_option_vars),
    }
    return summary, pd.DataFrame(selections)


def optimize_all_majors(
    plan_df: pd.DataFrame,
    db_path: str = str(SQLITE_DB_PATH),
    course_gpa_df: Optional[pd.DataFrame] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run the optimizer for every major in plan_df. Returns (summary_df, all_selections_df)."""
    summaries = []
    all_selections = []

    for major in plan_df["major"].unique():
        summary, selections = optimize_major_plan(plan_df, major, db_path, course_gpa_df)
        if summary is not None:
            summaries.append(summary)
            all_selections.append(selections)

    summary_df = pd.DataFrame(summaries).sort_values("optimal_expected_gpa", ascending=False)
    selections_df = pd.concat(all_selections, ignore_index=True) if all_selections else pd.DataFrame()
    return summary_df.reset_index(drop=True), selections_df


if __name__ == "__main__":
    from degree_plan_normalizer import parse_multiple
    from degree_plan_scraper import fetch_all
    from major_difficulty_ranker import rank_majors

    pages = fetch_all()
    plan_df, _ = parse_multiple(pages)

    baseline = rank_majors(plan_df)[["major", "expected_gpa"]].rename(columns={"expected_gpa": "baseline_expected_gpa"})
    optimal_summary, selections_df = optimize_all_majors(plan_df)

    comparison = optimal_summary.merge(baseline, on="major", how="left")
    comparison["gpa_uplift"] = comparison["optimal_expected_gpa"] - comparison["baseline_expected_gpa"]

    print(comparison.to_string(index=False))
    print("\nSelected electives (optimal plan):")
    print(selections_df.to_string(index=False))
