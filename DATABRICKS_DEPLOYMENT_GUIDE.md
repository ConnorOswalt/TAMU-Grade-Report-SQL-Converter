# TAMU Worst Professors Dashboard - Databricks Deployment Guide

## Overview

The Worst Professors Dashboard automatically runs after PDFs are ingested by the main TAMU Grade Report Pipeline, ensuring you always have analysis based on the latest grade data.

**Workflow:**
1. TAMU Grade Report Pipeline ingests PDFs (1st, 3rd, 5th, 7th, 9th, 11th of odd months at 12 PM CT)
2. PDFs parsed → Grades stored in Delta tables
3. ✅ Worst Professors Analysis automatically starts
4. Lakeview dashboard refreshed with latest instructor performance metrics
5. Email notification sent on any failures

### Prerequisites
- Databricks workspace access
- SQL warehouse created (or will use existing)
- Databricks personal access token (PAT)

### Step 1: Set Up Databricks Authentication

```powershell
# Create .databricks config file
$configDir = "$env:USERPROFILE\.databricks"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null

# Create config file
@"
[DEFAULT]
host = https://dbc-0b583d12-fb33.cloud.databricks.com
token = <your-personal-access-token-here>
"@ | Out-File -FilePath "$configDir\config" -Encoding UTF8
```

To generate your PAT:
1. Log in to: https://dbc-0b583d12-fb33.cloud.databricks.com
2. Click profile icon (top-right) → Settings
3. Developer → Personal access tokens
4. Click "Generate new token"
5. Name it (e.g., "tamu-deploy")
6. Copy the token value to the config file above

### Step 2: Upload Notebooks to Databricks

```powershell
cd "C:\Users\Connor\Documents\VSCode Projects\TAMU Grade Report Consolidator\TAMU-Grade-Report-SQL-Converter"

# Activate virtual environment (if not already)
.venv\Scripts\Activate.ps1

# Run deployment script
python upload_to_databricks.py
```

This will:
- ✅ Upload `worst_professors_dashboard.sql` 
- ✅ Upload `worst_professors_lakeview.sql`
- ℹ️  Display setup instructions for dashboard and job scheduling

### Step 3: Create Lakeview Dashboard

1. Navigate to: https://dbc-0b583d12-fb33.cloud.databricks.com/sql/editor/worst_professors_lakeview
2. Attach to your SQL warehouse (top-right dropdown)
3. Run the notebook to generate data
4. Go to: https://dbc-0b583d12-fb33.cloud.databricks.com/sql/dashboards
5. Click "+ Create" → "Lakeview dashboard"
6. Add visualizations from the queries:

**Recommended Dashboard Layout:**

| Widget | Query | Visualization | Purpose |
|--------|-------|----------------|---------| 
| Top KPIs | Summary Metrics | Scalar widgets | Show total instructors, avg GPA, overall fail rate |
| Worst 20 Professors | Worst Professors (Main) | Table (sortable) | Ranked list of most challenging professors |
| Hardest Courses | Hardest Courses | Table | Individual difficult courses |
| By College | Worst by College | Table with filter | Compare across colleges |
| GPA Trend | GPA Trend Over Years | Line chart | Track grade inflation/deflation |
| Grade Distribution | Grade Distribution | Stacked bar chart | Show A/B/C/D/F distribution by instructor |
| College Comparison | College Comparison | Bar chart | Compare colleges by average GPA |

### Step 4: Schedule Job Based on Pipeline Completion

**Automatic (Recommended):** Job now runs immediately after PDFs are ingested
- Triggers when `TAMU Grade Report Pipeline` completes successfully
- No fixed schedule needed
- Always has fresh data for analysis

**Option A: Deploy with Databricks Bundles**

1. Update `databricks.yml` with your warehouse ID (see Step 3 above)
2. Deploy:
   ```powershell
   databricks bundle deploy --target prod
   ```
3. This automatically sets up the job dependency in Databricks

**Option B: Manual Job Creation (if not using Bundles)**

1. Go to: https://dbc-0b583d12-fb33.cloud.databricks.com/jobs
2. Click "+ Create job"
3. Configure:
   - **Name:** Worst Professors Analysis
   - **Task Type:** SQL
   - **Notebook Path:** `/Shared/tamu-grade-report/worst_professors_lakeview`
   - **Warehouse:** Select your SQL warehouse
   - **Dependencies:**
     - Click "Add dependency"
     - Select job: "TAMU Grade Report Pipeline"
     - Select task: "ingest_and_refresh"
     - Wait for: Job completion
   - **Email Notifications:** 
     - On failure: connor.l.oswalt@gmail.com
4. Click "Create Job"

**Job Trigger Schedule:**
- Runs: After `TAMU Grade Report Pipeline` completes
- Pipeline runs: 1st, 3rd, 5th, 7th, 9th, 11th of odd months at 12 PM CT
- So Worst Professors analysis runs: Shortly after those times (when pipeline finishes)
- If pipeline fails: Worst Professors job doesn't run (avoids analyzing stale data)

## File Structure

```
databricks/
├── worst_professors_dashboard.sql      # Raw SQL queries for analysis
├── worst_professors_lakeview.sql       # Queries formatted for Lakeview dashboard
└── tamu_grade_pipeline.py              # Main pipeline (existing)

resources/
├── worst_professors_job.yml            # Job definition (new)
└── tamu_grade_pipeline.job.yml         # Existing pipeline job

databricks.yml                           # Bundle configuration (updated)
upload_to_databricks.py                 # Deployment script (updated)
WORST_PROFESSORS_README.md              # Detailed analysis documentation
DATABRICKS_DEPLOYMENT_GUIDE.md          # This file
```

## Queries Included in Lakeview Dashboard

### 1. Worst Professors (Top 20)
```sql
SELECT Instructor, num_classes, total_students, gpa, fail_rate, 
       drop_rate, difficulty_score, year_range
ORDER BY difficulty_score DESC
```
**Composite score** = (100 - GPA×25) + (fail_rate×2)

### 2. Hardest Courses
```sql
SELECT Class_Code, Instructor, total_students, gpa, fail_rate
ORDER BY gpa ASC
```
Minimum 200 students per course.

### 3. Worst Professors by College
```sql
SELECT College, Instructor, num_classes, total_students, gpa, fail_rate
ORDER BY gpa ASC
```
Allows college-level comparison.

### 4. Grade Distribution
```sql
SELECT Instructor, A_count, B_count, C_count, D_count, F_count, gpa
```
Stacked bar chart showing grade composition.

### 5. Summary Metrics (KPIs)
- Total instructors analyzed: 2,877+
- Total courses: 1,000+
- Average GPA: 3.343
- Overall fail rate: 1.52%
- Data range: 2017-2025

### 6. GPA Trend Over Time
```sql
SELECT Year, avg_gpa, num_instructors, total_students
ORDER BY Year DESC
```
Line chart to track trends.

### 7. College Comparison
```sql
SELECT College, avg_gpa, num_instructors, num_courses, total_students
ORDER BY avg_gpa DESC
```
Compare colleges by average GPA.

## Dashboard Features

✅ **Interactive Filters**
- Filter by college
- Filter by year/semester
- Sort by any column

✅ **Drill-Down Capability**
- Click instructor → see all their courses
- Click course → see distribution details

✅ **Auto-Refresh**
- Weekly refresh (Monday 2 AM)
- Manual refresh available
- Cache enabled for performance

✅ **Accessibility**
- Share with specific users/groups
- Export data to CSV
- Scheduled email reports

## Troubleshooting

### "Warehouse not found" Error
- Ensure SQL warehouse is running
- Check warehouse ID in job configuration
- Contact Databricks admin if needed

### "Notebook path not found" Error
- Verify notebooks were uploaded successfully
- Check path: `/Shared/tamu-grade-report/worst_professors_lakeview`
- Re-run `upload_to_databricks.py`

### Job Fails to Schedule
- Verify SQL warehouse ID is correct in resources/worst_professors_job.yml
- Check warehouse has sufficient permissions
- Ensure user has access to run jobs

### Dashboard Shows No Data
- Run the worst_professors_lakeview notebook manually first
- Verify grade_distributions table exists
- Check Parquet files are accessible in /Volumes/workspace/default/tamu_grades

## Monitoring & Maintenance

### Automatic Dashboard Updates (After PDF Ingestion)
1. Monitor job runs: https://dbc-0b583d12-fb33.cloud.databricks.com/jobs
2. Look for job pair: "TAMU Grade Report Pipeline" → "Worst Professors Analysis"
3. Both jobs show in job history with dependency chain
4. Email alerts sent on failures to: connor.l.oswalt@gmail.com

### Performance Tips
- Use dashboard filters to reduce query scope
- Cache results for common queries
- Schedule dashboard during off-peak hours (2 AM CT)

### Data Updates
- Grade distributions updated when new PDFs are ingested
- Manual refresh: Re-run worst_professors_lakeview notebook
- Incremental updates: Configure pipeline in tamu_grade_pipeline.py

## Support & Documentation

- **Analysis Details:** See [WORST_PROFESSORS_README.md](WORST_PROFESSORS_README.md)
- **Local Analysis:** Run `python worst_professors.py` for local reports
- **SQL Queries:** See [databricks/worst_professors_dashboard.sql](databricks/worst_professors_dashboard.sql)
- **Databricks Docs:** https://docs.databricks.com/en/dashboards/index.html

## Next Steps

1. ✅ Deploy notebooks (upload_to_databricks.py)
2. ✅ Create Lakeview dashboard (manual or bundle)
3. ✅ Schedule weekly job (manual or bundle)
4. ✅ Share dashboard with stakeholders
5. ⏭️ Create additional reports/alerts based on findings
6. ⏭️ Integrate with other TAMU analytics tools
