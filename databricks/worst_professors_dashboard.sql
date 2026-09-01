-- Databricks notebook source
-- MAGIC %md
-- MAGIC # TAMU Worst Professors Dashboard
-- MAGIC
-- MAGIC Analyzes instructor performance across all grade distribution data to identify
-- MAGIC professors who give the lowest grades and have the highest fail rates.
-- MAGIC
-- MAGIC Metrics:
-- MAGIC - **Weighted GPA**: Average GPA weighted by number of students in each class
-- MAGIC - **Fail Rate**: Percentage of F grades out of total graded (A-F)
-- MAGIC - **Drop/Incomplete Rate**: Percentage of Q (drop), X (missing), and I (incomplete) codes
-- MAGIC - **Classes Taught**: Number of distinct sections/sections taught
-- MAGIC - **Total Students**: Total students graded across all sections

-- COMMAND ----------

CREATE SCHEMA IF NOT EXISTS workspace.tamu_grades;

-- COMMAND ----------

-- MAGIC %md ## Create unified grade distributions table (if not using existing)

-- COMMAND ----------

-- If using existing dashboard's table, comment this out and use workspace.tamu_grades.grade_distributions
-- Otherwise, create it from Parquet:

CREATE OR REPLACE TABLE workspace.tamu_grades.grade_distributions AS
SELECT
    College, Year, Semester, `Class Code` AS Class_Code, Section,
    A, B, C, D, F, `Total A-F` AS Total_A_F, GPA, I, S, U, Q, X, Total, Instructor
FROM read_files('/Volumes/workspace/default/tamu_grades/grade_distributions', format => 'parquet');

-- COMMAND ----------

-- MAGIC %md ## Worst Professors by Weighted GPA (Bottom 20)
-- MAGIC
-- MAGIC Professors who consistently give the lowest grades.
-- MAGIC Minimum filter: at least 500 students graded to ensure statistical significance.

-- COMMAND ----------

SELECT
    Instructor,
    COUNT(DISTINCT Class_Code) AS num_classes,
    COUNT(DISTINCT CONCAT(Class_Code, '-', Section)) AS num_sections,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS weighted_gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS fail_rate_pct,
    ROUND((SUM(Q) + SUM(X) + SUM(I)) * 100.0 / SUM(Total), 2) AS drop_incomplete_rate_pct,
    MIN(TRY_CAST(Year AS INT)) AS earliest_year,
    MAX(TRY_CAST(Year AS INT)) AS latest_year
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND TRIM(Instructor) <> ''
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY Instructor
HAVING SUM(Total) >= 500
ORDER BY weighted_gpa ASC
LIMIT 20;

-- COMMAND ----------

-- MAGIC %md ## Highest Fail Rate Professors (Bottom 20)
-- MAGIC
-- MAGIC Professors with the highest percentage of F grades.
-- MAGIC Minimum filter: at least 500 students graded.

-- COMMAND ----------

SELECT
    Instructor,
    COUNT(DISTINCT Class_Code) AS num_classes,
    COUNT(DISTINCT CONCAT(Class_Code, '-', Section)) AS num_sections,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS weighted_gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS fail_rate_pct,
    ROUND((SUM(Q) + SUM(X) + SUM(I)) * 100.0 / SUM(Total), 2) AS drop_incomplete_rate_pct,
    MIN(TRY_CAST(Year AS INT)) AS earliest_year,
    MAX(TRY_CAST(Year AS INT)) AS latest_year
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND TRIM(Instructor) <> ''
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY Instructor
HAVING SUM(Total) >= 500
ORDER BY fail_rate_pct DESC
LIMIT 20;

-- COMMAND ----------

-- MAGIC %md ## Worst Professors Composite Ranking
-- MAGIC
-- MAGIC Combined ranking based on both low GPA and high fail rates.
-- MAGIC Score = (100 - weighted_gpa * 25) + (fail_rate_pct * 2)
-- MAGIC This emphasizes low GPA while also accounting for fail rate.

-- COMMAND ----------

SELECT
    Instructor,
    COUNT(DISTINCT Class_Code) AS num_classes,
    COUNT(DISTINCT CONCAT(Class_Code, '-', Section)) AS num_sections,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS weighted_gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS fail_rate_pct,
    ROUND((SUM(Q) + SUM(X) + SUM(I)) * 100.0 / SUM(Total), 2) AS drop_incomplete_rate_pct,
    ROUND((100 - SUM(GPA * Total) / SUM(Total) * 25) + (SUM(F) * 100.0 / SUM(Total_A_F) * 2), 2) AS difficulty_score,
    MIN(TRY_CAST(Year AS INT)) AS earliest_year,
    MAX(TRY_CAST(Year AS INT)) AS latest_year
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND TRIM(Instructor) <> ''
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY Instructor
HAVING SUM(Total) >= 500
ORDER BY difficulty_score DESC
LIMIT 20;

-- COMMAND ----------

-- MAGIC %md ## Worst Professors by College
-- MAGIC
-- MAGIC Analyze the most challenging professors within each college.

-- COMMAND ----------

SELECT
    College,
    Instructor,
    COUNT(DISTINCT Class_Code) AS num_classes,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS weighted_gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS fail_rate_pct
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND TRIM(Instructor) <> ''
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY College, Instructor
HAVING SUM(Total) >= 100
ORDER BY College, weighted_gpa ASC;

-- COMMAND ----------

-- MAGIC %md ## Courses with Worst Grade Distributions (min. 200 students)
-- MAGIC
-- MAGIC Individual courses/sections that are particularly difficult.

-- COMMAND ----------

SELECT
    Class_Code,
    College,
    TRY_CAST(Year AS INT) AS Year,
    Semester,
    Instructor,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(SUM(GPA * Total) / SUM(Total), 3) AS weighted_gpa,
    ROUND(SUM(F) * 100.0 / SUM(Total_A_F), 2) AS fail_rate_pct,
    ROUND((SUM(A) + SUM(B)) * 100.0 / SUM(Total_A_F), 2) AS ab_rate_pct
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY Class_Code, College, TRY_CAST(Year AS INT), Semester, Instructor
HAVING SUM(Total) >= 200
ORDER BY weighted_gpa ASC
LIMIT 30;

-- COMMAND ----------

-- MAGIC %md ## GPA Distribution by Instructor (Variability Analysis)
-- MAGIC
-- MAGIC Shows professors with inconsistent grading (high variance in GPA across sections).

-- COMMAND ----------

SELECT
    Instructor,
    COUNT(DISTINCT Class_Code) AS num_classes,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(AVG(GPA), 3) AS avg_gpa,
    ROUND(STDDEV(GPA), 3) AS stddev_gpa,
    ROUND(MIN(GPA), 3) AS min_gpa,
    ROUND(MAX(GPA), 3) AS max_gpa,
    ROUND(MAX(GPA) - MIN(GPA), 3) AS gpa_range
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND TRIM(Instructor) <> ''
  AND GPA IS NOT NULL
  AND Total IS NOT NULL
GROUP BY Instructor
HAVING SUM(Total) >= 300
ORDER BY stddev_gpa DESC
LIMIT 20;

-- COMMAND ----------

-- MAGIC %md ## Dataset Summary for Worst Professors Analysis

-- COMMAND ----------

SELECT
    COUNT(DISTINCT Instructor) AS total_instructors,
    COUNT(DISTINCT Class_Code) AS total_courses,
    CAST(SUM(Total) AS BIGINT) AS total_students,
    ROUND(AVG(GPA), 3) AS avg_gpa_across_all,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY GPA), 3) AS median_gpa,
    ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY GPA), 3) AS q1_gpa,
    ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY GPA), 3) AS q3_gpa,
    MIN(TRY_CAST(Year AS INT)) AS earliest_year,
    MAX(TRY_CAST(Year AS INT)) AS latest_year
FROM workspace.tamu_grades.grade_distributions
WHERE Instructor IS NOT NULL
  AND GPA IS NOT NULL
  AND Total IS NOT NULL;
