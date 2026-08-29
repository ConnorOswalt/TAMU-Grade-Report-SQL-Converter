-- Databricks notebook source
-- MAGIC %md
-- MAGIC # TAMU Major Difficulty Dashboard (SQL warehouse only)
-- MAGIC
-- MAGIC Loads the Parquet exports produced by `export_for_databricks.py` (already
-- MAGIC uploaded to `/Volumes/workspace/default/tamu_grades`) into Delta tables
-- MAGIC using `read_files()`, runnable entirely on a serverless SQL warehouse --
-- MAGIC no all-purpose cluster required. This mirrors the tables backing the
-- MAGIC published "TAMU Major Difficulty & Course Optimizer" Lakeview dashboard.
-- MAGIC
-- MAGIC `grade_distributions` renames tabula's raw column names (spaces/hyphens
-- MAGIC aren't valid Delta column names) and drops the unnamed trailing column.

-- COMMAND ----------

CREATE SCHEMA IF NOT EXISTS workspace.tamu_grades;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.tamu_grades.grade_distributions AS
SELECT
    College, Year, Semester, `Class Code` AS Class_Code, Section,
    A, B, C, D, F, `Total A-F` AS Total_A_F, GPA, I, S, U, Q, X, Total, Instructor
FROM read_files('/Volumes/workspace/default/tamu_grades/grade_distributions', format => 'parquet');

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.tamu_grades.degree_plan_courses AS
SELECT * FROM read_files('/Volumes/workspace/default/tamu_grades/degree_plan_courses', format => 'parquet');

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.tamu_grades.major_expected_gpa AS
SELECT * FROM read_files('/Volumes/workspace/default/tamu_grades/major_expected_gpa.parquet', format => 'parquet');

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.tamu_grades.optimizer_comparison AS
SELECT * FROM read_files('/Volumes/workspace/default/tamu_grades/major_optimizer_comparison.parquet', format => 'parquet');

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.tamu_grades.optimizer_selections AS
SELECT * FROM read_files('/Volumes/workspace/default/tamu_grades/optimizer_selected_electives.parquet', format => 'parquet');

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.tamu_grades.major_difficulty_index AS
SELECT * FROM read_files('/Volumes/workspace/default/tamu_grades/major_difficulty_index.parquet', format => 'parquet');

-- COMMAND ----------

-- MAGIC %md ## Expected GPA per major (baseline default-plan estimate)

-- COMMAND ----------

SELECT major, expected_gpa, coverage_pct, matched_credit_hours,
  matched_course_count, total_course_count, effective_sample_size, reliability_pct
FROM workspace.tamu_grades.major_expected_gpa
ORDER BY expected_gpa DESC;

-- COMMAND ----------

-- MAGIC %md ## Optimal (Gurobi) vs. baseline expected GPA

-- COMMAND ----------

SELECT major, baseline_expected_gpa, optimal_expected_gpa, gpa_uplift, num_choice_groups
FROM workspace.tamu_grades.optimizer_comparison
ORDER BY optimal_expected_gpa DESC;

-- COMMAND ----------

-- MAGIC %md ## Optimizer's selected electives per major

-- COMMAND ----------

SELECT major, course_subject, course_number, title, mean_gpa
FROM workspace.tamu_grades.optimizer_selections
ORDER BY major, choice_group_id;

-- COMMAND ----------

-- MAGIC %md ## Difficulty index: GPA + fail rate + drop rate (composite 0-100 score)

-- COMMAND ----------

SELECT major, expected_gpa, avg_fail_rate, avg_drop_rate, difficulty_score,
  coverage_pct, effective_sample_size, reliability_pct
FROM workspace.tamu_grades.major_difficulty_index
ORDER BY difficulty_score DESC;

-- COMMAND ----------

-- MAGIC %md ## Dataset summary KPIs

-- COMMAND ----------

SELECT
  COUNT(*) AS total_grade_rows,
  CAST(SUM(Total) AS BIGINT) AS total_students_graded,
  COUNT(DISTINCT Class_Code) AS distinct_courses,
  MIN(TRY_CAST(Year AS INT)) AS earliest_year,
  MAX(TRY_CAST(Year AS INT)) AS latest_year
FROM workspace.tamu_grades.grade_distributions
WHERE TRY_CAST(Year AS INT) IS NOT NULL;

-- COMMAND ----------

-- MAGIC %md ## Hardest / easiest individual courses (min. 200 students graded)
-- MAGIC
-- MAGIC The published dashboard renders the hardest courses as a ranked list.

-- COMMAND ----------

SELECT Class_Code AS class_code,
  ROUND(SUM(GPA * Total) / SUM(Total), 2) AS weighted_gpa,
  ROUND((SUM(F) + SUM(Q) + SUM(X)) * 100.0 / SUM(Total), 2) AS fail_drop_pct,
  CAST(SUM(Total) AS BIGINT) AS n_students
FROM workspace.tamu_grades.grade_distributions
WHERE GPA > 0 AND Total IS NOT NULL
GROUP BY Class_Code
HAVING SUM(Total) >= 200
ORDER BY weighted_gpa ASC
LIMIT 10;

-- COMMAND ----------

SELECT Class_Code AS class_code,
  ROUND(SUM(GPA * Total) / SUM(Total), 2) AS weighted_gpa,
  ROUND((SUM(F) + SUM(Q) + SUM(X)) * 100.0 / SUM(Total), 2) AS fail_drop_pct,
  CAST(SUM(Total) AS BIGINT) AS n_students
FROM workspace.tamu_grades.grade_distributions
WHERE GPA > 0 AND Total IS NOT NULL
GROUP BY Class_Code
HAVING SUM(Total) >= 200
ORDER BY weighted_gpa DESC, fail_drop_pct ASC, class_code ASC
LIMIT 10;

-- COMMAND ----------

-- MAGIC %md ## GPA trend by college and year (grade inflation check)

-- COMMAND ----------

SELECT
  College,
  TRY_CAST(Year AS INT) AS Year,
  ROUND(SUM(GPA * Total) / SUM(Total), 3) AS weighted_gpa
FROM workspace.tamu_grades.grade_distributions
WHERE GPA IS NOT NULL
  AND Total IS NOT NULL
  AND TRY_CAST(Year AS INT) IS NOT NULL
  AND College IS NOT NULL
  AND TRIM(College) <> ''
GROUP BY College, TRY_CAST(Year AS INT)
ORDER BY College, Year;
