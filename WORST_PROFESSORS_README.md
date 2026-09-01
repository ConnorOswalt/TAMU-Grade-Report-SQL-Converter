# Worst Professors Dashboard

A comprehensive analysis system for identifying TAMU professors who give the lowest grades and have the highest fail rates.

## Overview

This dashboard analyzes instructor performance metrics across all TAMU courses to identify the most challenging professors. It uses a multi-dimensional approach combining grade distributions and fail rates.

## Files

### 1. `worst_professors_dashboard.sql` (Databricks)
A Databricks SQL notebook with multiple analytical queries:

- **Worst Professors by Weighted GPA** - Bottom 20 professors by average GPA (min. 500 students)
- **Highest Fail Rate** - Professors with highest F grade percentages (min. 500 students)
- **Composite Ranking** - Combined difficulty score based on both GPA and fail rate
- **By College** - Worst professors within each college/department
- **Hardest Courses** - Individual courses/sections with toughest grade distributions (min. 200 students)
- **GPA Variability** - Professors with inconsistent grading patterns (high variance in GPA)

### 2. `worst_professors.py` (Local Analysis)
Python script for analyzing worst professors from parquet data locally.

**Usage:**
```bash
python worst_professors.py
```

**Output:**
- Top 20 worst professors (difficulty score)
- Top 20 worst by weighted GPA
- Top 20 worst by fail rate %
- Worst professors by college
- Top 30 hardest courses
- Summary statistics

## Metrics Explained

### Weighted GPA
Average GPA weighted by class size. A professor teaching a 300-student course has more impact than a 30-student course.

```
Weighted GPA = Σ(GPA × Total Students) / Σ(Total Students)
```

### Fail Rate %
Percentage of F grades out of students with grades A-F (excluding I, S, U, Q, X).

```
Fail Rate % = (F / Total A-F) × 100
```

### Difficulty Score
Composite metric emphasizing low GPA while accounting for fail rate:

```
Difficulty Score = (100 - weighted_gpa × 25) + (fail_rate_pct × 2)
```

### Drop/Incomplete Rate %
Percentage of students receiving Q (drop), X (missing), or I (incomplete) codes.

```
Drop/Incomplete Rate % = (Q + X + I) / Total × 100
```

## Sample Results

**Top 5 Worst Professors (Difficulty Score):**

| Instructor | Weighted GPA | Fail Rate | Classes | Total Students |
|------------|-------------|-----------|---------|-----------------|
| ERDELYI T | 2.070 | 14.04% | 1 | 1,814 |
| ARISTIDOU M | 2.078 | 13.90% | 4 | 946 |
| MIR N | 2.232 | 13.79% | 5 | 1,186 |
| KANCHUPATI P | 2.146 | 9.71% | 2 | 1,322 |
| CROMPTON J | 2.114 | 8.72% | 6 | 1,248 |

**Context Benchmarks:**
- Average GPA across all instructors: **3.343**
- Median GPA: **3.371**
- Average Fail Rate: **1.52%**
- Median Fail Rate: **1.04%**

## Data Coverage

- **Total Records Analyzed:** 211,794 grade entries
- **Instructors Analyzed:** 2,877 (minimum 500 students taught)
- **Courses:** All TAMU colleges and departments
- **Years:** 2017-2025
- **Semesters:** Spring, Summer, Fall

## Minimum Sample Sizes

Different analyses use different minimum thresholds to ensure statistical significance:

- **Individual instructor analysis:** 500+ students taught
- **By-college analysis:** 100+ students taught
- **Course difficulty:** 200+ students in course
- **Variability analysis:** 300+ students taught (for STDDEV)

## Usage

### For Databricks Dashboard
1. Open Databricks workspace
2. Import `databricks/worst_professors_dashboard.sql`
3. Create queries as dashboard cells
4. Connect to Lakeview dashboard for interactive visualization

### For Local Analysis
```bash
# Activate virtual environment
.venv\Scripts\Activate.ps1

# Run analysis
python worst_professors.py

# Output includes rankings and statistics
```

## Integration with Existing Data

The analysis integrates with existing TAMU data pipeline:
- Uses parquet files from `data/parquet/grade_distributions/`
- Partitioned by College, Year, and Semester
- Consistent with `major_difficulty_dashboard.sql` format

## Notes

- Professors with fewer than 500 students taught are not included in overall analysis (still available in by-college analysis with 100+ threshold)
- Data represents TAMU institutional data from official grade distribution records
- Results should be interpreted in context of course difficulty, student population, and standards
- Some variation in GPA can reflect course rigor expectations (e.g., advanced courses typically have lower GPAs)
