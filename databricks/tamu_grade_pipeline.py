import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.dashboards import Dashboard
from pyspark.sql import SparkSession, types as T

PROJECT_ROOT = Path(sys.argv[sys.argv.index("--project-root") + 1])
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    COLLEGE_CODES,
    REPORT_URL_TEMPLATES,
    REPORT_TYPES,
    SEMESTER_CODES,
    SEMESTER_URL_CODE,
)
from converter import grd_to_df, pdf_to_dataframe
from course_optimizer import optimize_all_majors
from degree_plan_normalizer import parse_plan_html
from degree_plan_scraper import discover_bachelor_programs, fetch_degree_plan_html
from difficulty_index import compute_major_difficulty_index
from major_difficulty_ranker import rank_majors

CATALOG = "workspace"
SCHEMA = "tamu_grades"
VOLUME_ROOT = "/Volumes/workspace/default/tamu_grades"
DASHBOARD_ID = "01f19b6f9cce102b92c0bd9f3961f2a9"
DASHBOARD_WAREHOUSE_ID = "b83e95710a138a79"
LOOKBACK_YEARS = 1
MIN_PDF_BYTES = 2048
USER_AGENT = "TAMU-Grade-Consolidator/1.0 (research/education)"

COLLEGE_NAMES = {
    "AG": "Agriculture",
    "AR": "Architecture",
    "BA": "Business",
    "DN": "Dentistry",
    "ED": "Education",
    "EN": "Engineering",
    "GB": "Bush School of Government and Public Service",
    "GE": "Geosciences",
    "GV": "Galveston",
    "LA": "Liberal Arts",
    "LW": "Law",
    "MD": "Medicine",
    "MD_PROF": "Medicine - Professional",
    "NU": "Nursing",
    "PH": "Pharmacy",
    "PU": "Public Health",
    "QT": "Qatar",
    "SC": "Science",
    "UN": "Unassigned / Other",
    "VM": "Veterinary Medicine",
}

GRADE_COLUMNS = [
    "College", "Year", "Semester", "Class_Code", "Section", "A", "B", "C",
    "D", "F", "Total_A_F", "GPA", "I", "S", "U", "Q", "X", "Total",
    "Instructor", "source_report_sha256", "source_url", "ingested_at",
]
NUMERIC_GRADE_COLUMNS = [
    "A", "B", "C", "D", "F", "Total_A_F", "GPA", "I", "S", "U", "Q", "X", "Total"
]
CLASSIFICATIONS = ["Freshman", "Sophomore", "Junior", "Senior", "Overall"]

spark = SparkSession.builder.getOrCreate()


class UnsupportedReportSchemaError(ValueError):
    pass


def ensure_tables() -> None:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.report_ingestion_manifest (
          source_url STRING,
          report_sha256 STRING,
          report_type STRING,
          college_code STRING,
          report_year INT,
          semester_code INT,
          volume_path STRING,
          byte_count BIGINT,
          status STRING,
          row_count BIGINT,
          discovered_at TIMESTAMP,
          processed_at TIMESTAMP,
          error_message STRING
        ) USING DELTA
        """
    )
    spark.sql(
        f"""
        CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.gpa_distributions (
          report_type STRING,
          College STRING,
          Year STRING,
          Semester STRING,
          classification STRING,
          metric STRING,
          male_value DOUBLE,
          female_value DOUBLE,
          total_value DOUBLE,
          source_report_sha256 STRING,
          source_url STRING,
          ingested_at TIMESTAMP
        ) USING DELTA
        """
    )


def build_report_url(year: int, semester: int, report_type: str, college: str) -> str:
    return REPORT_URL_TEMPLATES[report_type].format(
        year=year,
        term=SEMESTER_URL_CODE[semester],
        college_code=college,
    )


def processed_hashes() -> set[str]:
    rows = spark.sql(
        f"""
        SELECT report_sha256
        FROM {CATALOG}.{SCHEMA}.report_ingestion_manifest
        WHERE status IN ('processed', 'quarantined')
        """
    ).collect()
    return {row.report_sha256 for row in rows}


def download_candidates() -> list[dict]:
    current_year = datetime.now(timezone.utc).year
    years = range(current_year - LOOKBACK_YEARS, current_year + 1)
    colleges = list(dict.fromkeys(COLLEGE_CODES))
    existing_hashes = processed_hashes()
    candidates = []

    for year in years:
        for semester_code in SEMESTER_CODES:
            for report_type in REPORT_TYPES:
                for college_code in colleges:
                    url = build_report_url(year, semester_code, report_type, college_code)
                    response = requests.get(
                        url,
                        headers={"User-Agent": USER_AGENT},
                        timeout=30,
                    )
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    content = response.content
                    if len(content) < MIN_PDF_BYTES or not content.startswith(b"%PDF"):
                        print(f"Skipping unavailable report: {url}")
                        continue

                    report_hash = hashlib.sha256(content).hexdigest()
                    if report_hash in existing_hashes:
                        continue

                    volume_path = (
                        f"{VOLUME_ROOT}/raw/{report_type}/{year}/{semester_code}/"
                        f"{report_type}_{year}_{semester_code}_{college_code}_{report_hash[:12]}.pdf"
                    )
                    Path(volume_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(volume_path).write_bytes(content)
                    candidates.append(
                        {
                            "source_url": url,
                            "report_sha256": report_hash,
                            "report_type": report_type,
                            "college_code": college_code,
                            "report_year": year,
                            "semester_code": semester_code,
                            "volume_path": volume_path,
                            "byte_count": len(content),
                        }
                    )
    return candidates


def split_values(value: object, expected: int) -> list[float | None]:
    parts = str(value).strip().split() if pd.notna(value) else []
    parsed = [pd.to_numeric(part, errors="coerce") for part in parts]
    values = [None if pd.isna(item) else float(item) for item in parsed]
    return (values + [None] * expected)[:expected]


def normalize_grd(candidate: dict) -> pd.DataFrame:
    frame = grd_to_df(candidate["volume_path"])
    if frame.empty or "Section" not in frame.columns:
        raise ValueError("Tabula returned no grade-distribution rows")
    if "Total" not in frame.columns or "Instructor" not in frame.columns:
        raise UnsupportedReportSchemaError(
            "Non-A-F professional grading schema; archived but excluded from letter-grade analytics"
        )

    split = frame["Section"].astype(str).str.rsplit("-", n=1, expand=True)
    if split.shape[1] != 2:
        raise ValueError("Could not split course and section identifiers")

    frame = frame.copy()
    frame.insert(0, "Class_Code", split[0].str.strip())
    frame["Section"] = split[1].str.strip()
    frame.insert(0, "Semester", SEMESTER_CODES[candidate["semester_code"]])
    frame.insert(0, "Year", str(candidate["report_year"]))
    frame.insert(0, "College", COLLEGE_NAMES.get(candidate["college_code"], candidate["college_code"]))
    frame = frame.rename(columns={"Total A-F": "Total_A_F"})

    for column in NUMERIC_GRADE_COLUMNS:
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")

    frame["source_report_sha256"] = candidate["report_sha256"]
    frame["source_url"] = candidate["source_url"]
    frame["ingested_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    frame = frame.reindex(columns=GRADE_COLUMNS)
    frame = frame.dropna(subset=["Class_Code", "Section", "Total"])

    if frame.empty:
        raise ValueError("No valid grade rows remained after normalization")
    if (frame[NUMERIC_GRADE_COLUMNS].drop(columns="GPA") < 0).any().any():
        raise ValueError("Negative grade counts detected")
    return frame


def normalize_gpa(candidate: dict) -> pd.DataFrame:
    raw = pdf_to_dataframe(candidate["volume_path"])
    if raw.empty:
        raise ValueError(f"Unexpected {candidate['report_type']} Tabula shape: {raw.shape}")

    rows = []
    for _, source_row in raw.iterrows():
        metric = str(source_row.iloc[0]).strip()
        if not metric or metric.lower() == "nan" or metric.upper() == "GRADE POINT AVG":
            continue

        values = []
        for cell in source_row.iloc[1:]:
            if pd.isna(cell):
                continue
            for token in str(cell).replace(",", "").split():
                value = pd.to_numeric(token, errors="coerce")
                if pd.notna(value):
                    values.append(float(value))

        if len(values) != 15:
            raise ValueError(
                f"Unexpected {candidate['report_type']} metric layout for {metric!r}: "
                f"expected 15 numeric values, found {len(values)}"
            )

        for group_index, classification in enumerate(CLASSIFICATIONS):
            male, female, total = values[group_index * 3:(group_index + 1) * 3]
            rows.append((classification, metric, male, female, total))

    ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return pd.DataFrame(
        [
            {
                "report_type": candidate["report_type"],
                "College": COLLEGE_NAMES.get(candidate["college_code"], candidate["college_code"]),
                "Year": str(candidate["report_year"]),
                "Semester": SEMESTER_CODES[candidate["semester_code"]],
                "classification": classification,
                "metric": metric,
                "male_value": male,
                "female_value": female,
                "total_value": total,
                "source_report_sha256": candidate["report_sha256"],
                "source_url": candidate["source_url"],
                "ingested_at": ingested_at,
            }
            for classification, metric, male, female, total in rows
        ]
    )


def replace_report_slice(candidate: dict, frame: pd.DataFrame) -> None:
    table = "grade_distributions" if candidate["report_type"] == "grd" else "gpa_distributions"
    college = COLLEGE_NAMES.get(candidate["college_code"], candidate["college_code"])
    semester = SEMESTER_CODES[candidate["semester_code"]]
    spark_frame = spark.createDataFrame(frame)
    spark.sql(
        f"""
        DELETE FROM {CATALOG}.{SCHEMA}.{table}
        WHERE College = {sql_literal(college)}
          AND Year = {sql_literal(str(candidate['report_year']))}
          AND Semester = {sql_literal(semester)}
          {f"AND report_type = {sql_literal(candidate['report_type'])}" if table == 'gpa_distributions' else ''}
        """
    )
    spark_frame.write.mode("append").option("mergeSchema", "true").saveAsTable(
        f"{CATALOG}.{SCHEMA}.{table}"
    )


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def record_manifest(candidate: dict, status: str, row_count: int = 0, error: str | None = None) -> None:
    schema = T.StructType(
        [
            T.StructField("source_url", T.StringType(), False),
            T.StructField("report_sha256", T.StringType(), False),
            T.StructField("report_type", T.StringType(), False),
            T.StructField("college_code", T.StringType(), False),
            T.StructField("report_year", T.IntegerType(), False),
            T.StructField("semester_code", T.IntegerType(), False),
            T.StructField("volume_path", T.StringType(), False),
            T.StructField("byte_count", T.LongType(), False),
            T.StructField("status", T.StringType(), False),
            T.StructField("row_count", T.LongType(), False),
            T.StructField("discovered_at", T.TimestampType(), False),
            T.StructField("processed_at", T.TimestampType(), True),
            T.StructField("error_message", T.StringType(), True),
        ]
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = (
        candidate["source_url"], candidate["report_sha256"], candidate["report_type"],
        candidate["college_code"], candidate["report_year"], candidate["semester_code"],
        candidate["volume_path"], candidate["byte_count"], status, row_count, now,
        now if status in {"processed", "quarantined", "failed"} else None, error,
    )
    spark.createDataFrame([row], schema).createOrReplaceTempView("manifest_update")
    spark.sql(
        f"""
        MERGE INTO {CATALOG}.{SCHEMA}.report_ingestion_manifest target
        USING manifest_update source
        ON target.report_sha256 = source.report_sha256
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )


def rebuild_gold_tables() -> None:
    refresh_degree_plan_catalog()
    plan_df = spark.table(f"{CATALOG}.{SCHEMA}.degree_plan_courses").drop("_rescued_data").toPandas()
    grade_df = spark.table(f"{CATALOG}.{SCHEMA}.grade_distributions").toPandas()
    split = grade_df["Class_Code"].astype(str).str.split("-", n=1, expand=True)
    grade_df["course_subject"] = split[0].str.strip().str.upper()
    grade_df["course_number"] = split[1].str.strip().str.upper()

    for column in ["GPA", "F", "Total_A_F", "Q", "X", "Total"]:
        grade_df[column] = pd.to_numeric(grade_df[column], errors="coerce")

    valid = grade_df.dropna(subset=["course_subject", "course_number", "Total"])
    valid = valid[valid["Total"] > 0].copy()
    valid["_gpa_weight"] = valid["Total"].where(valid["GPA"].notna(), 0)
    valid["_weighted_gpa"] = valid["GPA"].fillna(0) * valid["_gpa_weight"]
    stats = valid.groupby(["course_subject", "course_number"]).agg(
        _weighted_gpa_sum=("_weighted_gpa", "sum"),
        _gpa_weight_sum=("_gpa_weight", "sum"),
        F_sum=("F", "sum"),
        total_af_sum=("Total_A_F", "sum"),
        Q_sum=("Q", "sum"),
        X_sum=("X", "sum"),
        n_students=("Total", "sum"),
    ).reset_index()
    stats["mean_gpa"] = stats["_weighted_gpa_sum"] / stats["_gpa_weight_sum"].replace(0, pd.NA)
    stats["fail_rate"] = stats["F_sum"] / stats["total_af_sum"].replace(0, pd.NA)
    stats["drop_rate"] = (stats["Q_sum"] + stats["X_sum"]) / stats["n_students"].replace(0, pd.NA)
    stats_df = stats[["course_subject", "course_number", "mean_gpa", "fail_rate", "drop_rate", "n_students"]]
    course_gpa_df = stats_df[["course_subject", "course_number", "mean_gpa", "n_students"]]

    ranking = rank_majors(plan_df, course_gpa_df=course_gpa_df)
    difficulty = compute_major_difficulty_index(plan_df, stats_df=stats_df)
    optimal, selections = optimize_all_majors(plan_df, course_gpa_df=course_gpa_df)
    comparison = optimal.merge(
        ranking[["major", "expected_gpa"]].rename(columns={"expected_gpa": "baseline_expected_gpa"}),
        on="major",
        how="left",
    )
    comparison["gpa_uplift"] = comparison["optimal_expected_gpa"] - comparison["baseline_expected_gpa"]

    outputs = {
        "major_expected_gpa": ranking,
        "major_difficulty_index": difficulty,
        "optimizer_comparison": comparison,
        "optimizer_selections": selections,
    }
    for table_name, output in outputs.items():
        spark.createDataFrame(output).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
            f"{CATALOG}.{SCHEMA}.{table_name}"
        )
    refresh_dashboard_lists(difficulty, grade_df)


def refresh_degree_plan_catalog() -> None:
    programs = discover_bachelor_programs()
    if len(programs) < 220:
        raise RuntimeError(f"Catalog discovery returned only {len(programs)} bachelor programs")

    frames = []
    inventory = []
    for major, url in programs.items():
        html = fetch_degree_plan_html(url)
        if html is None:
            inventory.append({"major": major, "program_url": url, "status": "fetch_failed", "plan_rows": 0})
            continue
        frame, _ = parse_plan_html(html, major)
        if frame.empty:
            inventory.append({"major": major, "program_url": url, "status": "no_plan_grid", "plan_rows": 0})
            continue
        frame["program_url"] = url
        frames.append(frame)
        inventory.append({"major": major, "program_url": url, "status": "rankable", "plan_rows": len(frame)})

    if len(frames) < 200:
        raise RuntimeError(f"Only {len(frames)} bachelor programs produced parseable degree plans")

    plan_df = pd.concat(frames, ignore_index=True)
    spark.createDataFrame(plan_df).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        f"{CATALOG}.{SCHEMA}.degree_plan_courses"
    )
    spark.createDataFrame(pd.DataFrame(inventory)).write.mode("overwrite").option(
        "overwriteSchema", "true"
    ).saveAsTable(f"{CATALOG}.{SCHEMA}.degree_plan_program_inventory")


def refresh_dashboard_lists(difficulty: pd.DataFrame, grade_df: pd.DataFrame) -> None:
    scored_difficulty = difficulty.dropna(subset=["difficulty_score"]).copy()
    unscored_difficulty = difficulty[difficulty["difficulty_score"].isna()].copy()
    major_lines = ["## Hardest Majors, Ranked\n"]
    for rank, row in enumerate(scored_difficulty.head(10).itertuples(index=False), 1):
        reliability_label = (
            "High" if row.reliability_pct >= 80 else "Moderate" if row.reliability_pct >= 60 else "Limited"
        )
        major_lines.append(
            f"{rank}. **{row.major}** | Difficulty **{row.difficulty_score:.1f}** | "
            f"GPA **{row.expected_gpa:.2f}** | Fail **{row.avg_fail_rate * 100:.2f}%** | "
            f"Drop **{row.avg_drop_rate * 100:.2f}%** | Reliability **{row.reliability_pct:.1f}% "
            f"({reliability_label})** | Coverage **{row.coverage_pct:.1f}%** | "
            f"N_eff **{row.effective_sample_size:g}**\n"
        )

    courses = grade_df[(grade_df["GPA"] > 0) & grade_df["Total"].notna()].copy()
    courses["weighted_gpa"] = courses["GPA"] * courses["Total"]
    course_stats = courses.groupby("Class_Code").agg(
        weighted_gpa_sum=("weighted_gpa", "sum"),
        fail_count=("F", "sum"),
        drop_q_count=("Q", "sum"),
        drop_x_count=("X", "sum"),
        n_students=("Total", "sum"),
    )
    course_stats = course_stats[course_stats["n_students"] >= 200].copy()
    course_stats["weighted_gpa"] = course_stats["weighted_gpa_sum"] / course_stats["n_students"]
    course_stats["fail_drop_rate"] = (
        course_stats["fail_count"] + course_stats["drop_q_count"] + course_stats["drop_x_count"]
    ) / course_stats["n_students"]
    course_stats["reliability_pct"] = (1 - (-course_stats["n_students"] / 500).map(math.exp)) * 100
    course_stats = course_stats.reset_index()
    hardest = course_stats.sort_values(
        ["weighted_gpa", "fail_drop_rate", "Class_Code"],
        ascending=[True, False, True],
    ).head(10)
    easiest = course_stats.sort_values(
        ["weighted_gpa", "fail_drop_rate", "Class_Code"],
        ascending=[False, True, True],
    ).head(10)

    course_lines = ["## Hardest Courses, Ranked\n"]
    for rank, row in enumerate(hardest.itertuples(index=False), 1):
        course_lines.append(
            f"{rank}. **{row.Class_Code}** | Average GPA: **{row.weighted_gpa:.2f}** | "
            f"Fail+Drop: **{row.fail_drop_rate * 100:.2f}%** | Reliability: "
            f"**{row.reliability_pct:.1f}%** | {row.n_students:g} enrollments\n"
        )

    easiest_lines = ["## Easiest Courses, Ranked\n"]
    for rank, row in enumerate(easiest.itertuples(index=False), 1):
        easiest_lines.append(
            f"{rank}. **{row.Class_Code}** | Average GPA: **{row.weighted_gpa:.2f}** | "
            f"Fail+Drop: **{row.fail_drop_rate * 100:.2f}%** | Reliability: "
            f"**{row.reliability_pct:.1f}%** | {row.n_students:g} enrollments\n"
        )

    year_values = pd.to_numeric(grade_df["Year"], errors="coerce").dropna()
    earliest_year = int(year_values.min())
    latest_year = int(year_values.max())
    report_counts = spark.sql(
        f"""
        SELECT
          SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
          SUM(CASE WHEN status = 'quarantined' THEN 1 ELSE 0 END) AS quarantined
        FROM {CATALOG}.{SCHEMA}.report_ingestion_manifest
        """
    ).first()
    quality_lines = [
        "## Methodology & Data Quality\n",
        "**Reliability score.** Major reliability = plan coverage x "
        "`(1 - exp(-N_eff / 500))`, where `N_eff` is the credit-weighted harmonic "
        "enrollment support. Course reliability uses the same sample-support curve. "
        "This is a transparent evidence-support score, **not** a 95% confidence interval.\n",
        f"**Difficulty score.** Relative only among the {len(scored_difficulty)} ranked programs: "
        "equal-weight standardized "
        "signals for lower GPA, higher failure rate, and higher drop rate, rescaled from 0 to 100. "
        "A score of 100 does not mean an absolute or universal maximum.\n",
        "**Rates.** Major failure = `F / Total A-F`; major drop = `(Q + X) / Total`. "
        "Course Fail+Drop = `(F + Q + X) / Total`. Counts represent enrollments, not unique students.\n",
        f"**Scope.** {len(grade_df):,} section-level records from {earliest_year}-{latest_year}; "
        f"{int(report_counts.processed or 0)} source PDFs processed and "
        f"{int(report_counts.quarantined or 0)} incompatible professional-grade PDFs quarantined.\n",
        "**Limitations.** Default catalog plans are modeled rather than individual student pathways; "
        "tracks/options are treated as distinct catalog programs; ETAM and elective pathways may be incomplete; "
        "FERPA suppresses "
        "sections below five students; report availability varies by college/year; aggregate reports "
        "cannot control for prior student GPA, instructor selection, repeated enrollment, or causal effects.\n",
    ]

    client = WorkspaceClient()
    dashboard = client.lakeview.get(dashboard_id=DASHBOARD_ID)
    spec = json.loads(dashboard.serialized_dashboard)
    for dataset in spec["datasets"]:
        if dataset.get("name") == "major_gpa":
            dataset["queryLines"] = [
                "SELECT major, expected_gpa, coverage_pct, reliability_pct\n",
                f"FROM {CATALOG}.{SCHEMA}.major_expected_gpa\n",
                "ORDER BY expected_gpa ASC\n",
                "LIMIT 10",
            ]
        if dataset.get("name") == "optimizer_cmp":
            dataset["queryLines"] = [
                "SELECT major, baseline_expected_gpa, optimal_expected_gpa, gpa_uplift\n",
                f"FROM {CATALOG}.{SCHEMA}.optimizer_comparison\n",
                "ORDER BY gpa_uplift DESC\n",
                "LIMIT 10",
            ]
        if dataset.get("name") == "gpa_by_year":
            dataset.pop("queryLines", None)
            dataset["config"] = {
                "source": f"{CATALOG}.{SCHEMA}.grade_distributions",
                "measures": [
                    {
                        "name": "weighted_gpa",
                        "expr": "SUM(GPA * Total) / NULLIF(SUM(Total), 0)",
                        "displayName": "Weighted GPA",
                    }
                ],
                "dimensions": [
                    {"name": "College", "expr": "College"},
                    {"name": "Year", "expr": "TRY_CAST(Year AS BIGINT)"},
                ],
                "filter": "source.GPA > 0 AND source.Total IS NOT NULL",
                "version": "1.1",
            }

    for item in spec["pages"][0]["layout"]:
        widget = item.get("widget", {})
        if widget.get("name") == "dashboard_title":
            widget["multilineTextboxSpec"]["lines"] = [
                "# TAMU Major Difficulty & Course Optimizer\n",
                f"Evidence-weighted comparisons across {len(grade_df):,} TAMU section records "
                f"({earliest_year}-{latest_year}), mapped to official default degree plans. "
                "Difficulty combines GPA, failure, and drop outcomes; reliability shows how strongly "
                "each estimate is supported by plan coverage and enrollment volume.",
            ]
        if widget.get("name") == "difficulty_score_list":
            widget["multilineTextboxSpec"]["lines"] = major_lines
        if widget.get("name") == "hardest_courses_list":
            widget["multilineTextboxSpec"]["lines"] = course_lines
        if widget.get("name") in {"easiest_courses_bar", "easiest_courses_list"}:
            item["widget"] = {
                "name": "easiest_courses_list",
                "multilineTextboxSpec": {"lines": easiest_lines},
            }
        if widget.get("name") == "gpa_trend_line":
            widget["queries"] = [
                {
                    "name": "main_query",
                    "query": {
                        "datasetName": "gpa_by_year",
                        "fields": [
                            {"name": "College", "expression": "`College`"},
                            {"name": "Year", "expression": "`Year`"},
                            {
                                "name": "measure(weighted_gpa)",
                                "expression": "MEASURE(`weighted_gpa`)",
                            },
                        ],
                        "disaggregated": False,
                    },
                }
            ]
            widget["spec"] = {
                "version": 3,
                "frame": {"title": "GPA Trend by College, 2017-2026", "showTitle": True},
                "widgetType": "line",
                "encodings": {
                    "x": {
                        "fieldName": "Year",
                        "displayName": "Year",
                        "scale": {"type": "categorical"},
                    },
                    "y": {
                        "fieldName": "measure(weighted_gpa)",
                        "displayName": "Weighted GPA",
                        "scale": {"type": "quantitative"},
                    },
                    "color": {
                        "fieldName": "College",
                        "displayName": "College",
                        "scale": {"type": "categorical"},
                    },
                },
                "data": {"queryName": "main_query"},
            }

    inventory = spark.table(f"{CATALOG}.{SCHEMA}.degree_plan_program_inventory").toPandas()
    unranked_inventory = inventory[inventory["status"] != "rankable"].sort_values("major")
    all_major_lines = []
    for rank, row in enumerate(scored_difficulty.itertuples(index=False), 1):
        reliability_label = (
            "High" if row.reliability_pct >= 80 else "Moderate" if row.reliability_pct >= 60 else "Limited"
        )
        all_major_lines.append(
            f"{rank}. **{row.major}** | Difficulty **{row.difficulty_score:.1f}** | "
            f"GPA **{row.expected_gpa:.2f}** | Reliability **{row.reliability_pct:.1f}% "
            f"({reliability_label})** | Coverage **{row.coverage_pct:.1f}%**\n"
        )

    all_major_layout = [
        {
            "widget": {
                "name": "all_majors_title",
                "multilineTextboxSpec": {
                    "lines": [
                        "# All Ranked Bachelor Programs\n",
                        f"{len(scored_difficulty)} catalog programs and tracks ranked from hardest to easiest. "
                        "Use your browser's Find command to locate a program. The main dashboard remains a "
                        "compact top-10 view; reliability and coverage should be considered alongside rank.",
                    ]
                },
            },
            "position": {"x": 0, "y": 0, "width": 6, "height": 4},
        }
    ]
    chunk_size = 30
    y_position = 4
    for chunk_index in range(0, len(all_major_lines), chunk_size):
        chunk = all_major_lines[chunk_index:chunk_index + chunk_size]
        first_rank = chunk_index + 1
        last_rank = chunk_index + len(chunk)
        all_major_layout.append(
            {
                "widget": {
                    "name": f"all_majors_{first_rank}_{last_rank}",
                    "multilineTextboxSpec": {
                        "lines": [f"## Ranks {first_rank}-{last_rank}\n", *chunk]
                    },
                },
                "position": {"x": 0, "y": y_position, "width": 6, "height": 30},
            }
        )
        y_position += 30

    if not unranked_inventory.empty:
        excluded_lines = [
            f"- **{row.major}** | {row.status.replace('_', ' ')}\n"
            for row in unranked_inventory.itertuples(index=False)
        ]
        excluded_lines.extend(
            f"- **{row.major}** | insufficient named-course grade matches\n"
            for row in unscored_difficulty.sort_values("major").itertuples(index=False)
        )
        all_major_layout.append(
            {
                "widget": {
                    "name": "unranked_catalog_programs",
                    "multilineTextboxSpec": {
                        "lines": [
                            "## Catalog Programs Not Ranked\n",
                            "These programs remain visible but lack a parseable plan grid or sufficient matched grade data.\n",
                            *excluded_lines,
                        ]
                    },
                },
                "position": {"x": 0, "y": y_position, "width": 6, "height": 10},
            }
        )

    all_majors_page = {
        "name": "all_majors",
        "displayName": "All Majors",
        "layout": all_major_layout,
        "pageType": "PAGE_TYPE_CANVAS",
    }
    existing_page = next((page for page in spec["pages"] if page.get("name") == "all_majors"), None)
    if existing_page is None:
        spec["pages"].append(all_majors_page)
    else:
        existing_page.update(all_majors_page)

    quality_item = next(
        (
            item
            for item in spec["pages"][0]["layout"]
            if item.get("widget", {}).get("name") == "methodology_quality_notes"
        ),
        None,
    )
    if quality_item is None:
        spec["pages"][0]["layout"].append(
            {
                "widget": {
                    "name": "methodology_quality_notes",
                    "multilineTextboxSpec": {"lines": quality_lines},
                },
                "position": {"x": 0, "y": 37, "width": 6, "height": 9},
            }
        )
    else:
        quality_item["widget"]["multilineTextboxSpec"]["lines"] = quality_lines

    client.lakeview.update(
        dashboard_id=DASHBOARD_ID,
        dashboard=Dashboard(serialized_dashboard=json.dumps(spec)),
    )
    client.lakeview.publish(
        dashboard_id=DASHBOARD_ID,
        warehouse_id=DASHBOARD_WAREHOUSE_ID,
        embed_credentials=False,
    )


def main() -> None:
    ensure_tables()
    candidates = download_candidates()
    processed = 0
    failures = []

    for candidate in candidates:
        try:
            frame = normalize_grd(candidate) if candidate["report_type"] == "grd" else normalize_gpa(candidate)
            replace_report_slice(candidate, frame)
            record_manifest(candidate, "processed", len(frame))
            processed += 1
        except UnsupportedReportSchemaError as error:
            record_manifest(candidate, "quarantined", error=str(error))
        except Exception as error:
            record_manifest(candidate, "failed", error=str(error)[:4000])
            failures.append(f"{candidate['source_url']}: {error}")

    rebuild_gold_tables()
    print(f"Discovered {len(candidates)} new or changed reports; processed {processed}")
    if failures:
        raise RuntimeError(f"{len(failures)} reports failed:\n" + "\n".join(failures))


if __name__ == "__main__":
    main()