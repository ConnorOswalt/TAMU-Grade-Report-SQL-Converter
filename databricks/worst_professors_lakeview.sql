-- Databricks notebook source
-- MAGIC %md
-- MAGIC # TAMU Worst Professors Dashboard (Lakeview)
-- MAGIC
-- MAGIC Interactive dashboard showing instructor performance metrics.
-- MAGIC Queries the grade distributions data to identify professors giving
-- MAGIC the lowest grades and highest fail rates.
-- MAGIC
-- MAGIC **Updated:** Weekly (Mondays 2 AM CT)

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Configuration

-- COMMAND ----------

-- Ensure tables are created
CREATE SCHEMA IF NOT EXISTS workspace.tamu_grades;

CREATE OR REPLACE TABLE workspace.tamu_grades.grade_distributions AS
SELECT
    College, Year, Semester, `Class Code` AS Class_Code, Section,
    A, B, C, D, F, `Total A-F` AS Total_A_F, GPA, I, S, U, Q, X, Total, Instructor
FROM read_files('/Volumes/workspace/default/tamu_grades/grade_distributions', format => 'parquet');

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Worst Professors (Dashboard Data) - Top 20

-- COMMAND ----------

SELECT
    RANK() OVER (ORDER BY difficulty_score DESC) AS rank,
    Instructor,
    num_classes,
    total_students,
    ROUND(weighted_gpa, 3) AS gpa,
    ROUND(fail_rate_pct, 2) AS fail_rate,
    ROUND(drop_incomplete_rate_pct, 2) AS drop_rate,
    ROUND(difficulty_score, 2) AS difficulty_score,
    MIN(year) AS earliest_year,
    MAX(year) AS latest_year
FROM (
    SELECT
        Instructor,
        COUNT(DISTINCT Class_Code) AS num_classes,
        SUM(Total) AS total_students,
        SUM(GPA * Total) / SUM(Total) AS weighted_gpa,
        SUM(F) * 100.0 / SUM(Total_A_F) AS fail_rate_pct,
        (SUM(Q) + SUM(X) + SUM(I)) * 100.0 / SUM(Total) AS drop_incomplete_rate_pct,
        (100 - SUM(GPA * Total) / SUM(Total) * 25) + (SUM(F) * 100.0 / SUM(Total_A_F) * 2) AS difficulty_score,
        TRY_CAST(Year AS INT) AS year
    FROM workspace.tamu_grades.grade_distributions
    WHERE Instructor IS NOT NULL
      AND TRIM(Instructor) <> ''
      AND GPA IS NOT NULL
      AND Total IS NOT NULL
    GROUP BY Instructor, TRY_CAST(Year AS INT)
)
GROUP BY Instructor, num_classes, total_students, weighted_gpa, fail_rate_pct, drop_incomplete_rate_pct, difficulty_score
HAVING SUM(total_students) >= 500
ORDER BY difficulty_score DESC
LIMIT 20;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Hardest Courses (min 200 students)

-- COMMAND ----------

SELECT
    RANK() OVER (ORDER BY weighted_gpa ASC) AS rank,
    Class_Code,
    Instructor,
    total_students,
    ROUND(weighted_gpa, 3) AS gpa,
    ROUND(fail_rate_pct, 2) AS fail_rate,
    latest_semester
FROM (
    SELECT
        Class_Code,
        Instructor,
        SUM(Total) AS total_students,
        SUM(GPA * Total) / SUM(Total) AS weighted_gpa,
        SUM(F) * 100.0 / SUM(Total_A_F) AS fail_rate_pct,
        MAX(Semester) AS latest_semester
    FROM workspace.tamu_grades.grade_distributions
    WHERE GPA IS NOT NULL AND Total IS NOT NULL
    GROUP BY Class_Code, Instructor
    HAVING SUM(Total) >= 200
)
ORDER BY weighted_gpa ASC
LIMIT 20;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Worst Professors by College

-- COMMAND ----------

SELECT
    College,
    Instructor,
    COUNT(DISTINCT Class_Code) AS num_classes,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS fail_rate
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND TRIM(Instructor) <> ''
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY College, Instructor
HAVING SUM(Total) >= 100
ORDER BY College, gpa ASC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Grade Distribution by Instructor (Top 30 by Student Count)

-- COMMAND ----------

SELECT
    Instructor,
    SUM(A) AS A_count,
    SUM(B) AS B_count,
    SUM(C) AS C_count,
    SUM(D) AS D_count,
    SUM(F) AS F_count,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS gpa,
    CAST(SUM(Total) AS BIGINT) AS total_students
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY Instructor
HAVING SUM(Total) >= 500
ORDER BY total_students DESC
LIMIT 30;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## Summary Metrics (Dashboard KPIs)

-- COMMAND ----------

SELECT
    COUNT(DISTINCT Instructor) AS total_instructors,
    COUNT(DISTINCT Class_Code) AS total_courses,
    CAST(SUM(Total) AS BIGINT) AS total_students_graded,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS overall_avg_gpa,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY GPA), 3) AS median_gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS overall_fail_rate,
    MIN(TRY_CAST(Year AS INT)) AS earliest_year,
    MAX(TRY_CAST(Year AS INT)) AS latest_year
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND GPA IS NOT NULL
  AND Total IS NOT NULL;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## GPA Trend Over Years (All Instructors)

-- COMMAND ----------

SELECT
    TRY_CAST(Year AS INT) AS Year,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS avg_gpa,
    COUNT(DISTINCT Instructor) AS num_instructors,
    CAST(SUM(Total) AS BIGINT) AS total_students
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
  AND TRY_CAST(Year AS INT) IS NOT NULL
GROUP BY TRY_CAST(Year AS INT)
ORDER BY Year DESC;

-- COMMAND ----------

-- MAGIC %md
-- MAGIC ## College Comparison (Average GPA)

-- COMMAND ----------

SELECT
    College,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS avg_gpa,
    COUNT(DISTINCT Instructor) AS num_instructors,
    COUNT(DISTINCT Class_Code) AS num_courses,
    CAST(SUM(Total) AS BIGINT) AS total_students
FROM workspace.tamu_grades.grade_distributions
WHERE College IS NOT NULL
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY College
ORDER BY avg_gpa DESC;
