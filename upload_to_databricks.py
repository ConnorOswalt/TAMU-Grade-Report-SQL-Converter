#!/usr/bin/env python
"""
Deploy Worst Professors Dashboard to Databricks.
Uploads SQL notebooks and provides instructions for creating Lakeview dashboard and scheduling jobs.
"""

import os
import sys
from pathlib import Path
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import ImportPath, Language

def upload_notebook(client: WorkspaceClient, sql_file: Path, workspace_path: str) -> bool:
    """Upload a SQL notebook to Databricks workspace."""
    
    if not sql_file.exists():
        print(f"❌ Error: {sql_file} not found")
        return False
    
    with open(sql_file, "r") as f:
        content = f.read()
    
    print(f"📤 Uploading {sql_file}...")
    print(f"   → {workspace_path}")
    
    try:
        client.workspace.upload(
            path=workspace_path,
            format="SOURCE",
            language="SQL",
            overwrite=True,
            contents=content.encode('utf-8')
        )
        print(f"✅ Uploaded successfully")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def deploy_to_databricks():
    """Deploy all worst professors dashboards and provide setup instructions."""
    
    print("🚀 TAMU Worst Professors Dashboard - Databricks Deployment")
    print("=" * 70)
    
    try:
        # Initialize Databricks client
        client = WorkspaceClient()
        print(f"✅ Connected to Databricks workspace\n")
        
    except Exception as e:
        print(f"❌ Failed to connect to Databricks: {e}")
        print("\n⚠️  Setup Required:")
        print("   1. Create a Databricks personal access token (PAT):")
        print("      - Go to your Databricks workspace")
        print("      - Profile → Settings → Developer → Personal access tokens")
        print("      - Create new token, copy the value")
        print("   2. Set environment variables:")
        print("      $env:DATABRICKS_HOST='https://dbc-0b583d12-fb33.cloud.databricks.com'")
        print("      $env:DATABRICKS_TOKEN='<your-token-here>'")
        print("   3. Run this script again")
        return False
    
    success = True
    
    # Upload main dashboard notebook
    success &= upload_notebook(
        client,
        Path("databricks/worst_professors_dashboard.sql"),
        "/Workspace/Shared/tamu-grade-report/worst_professors_dashboard"
    )
    
    # Upload Lakeview dashboard notebook
    success &= upload_notebook(
        client,
        Path("databricks/worst_professors_lakeview.sql"),
        "/Workspace/Shared/tamu-grade-report/worst_professors_lakeview"
    )
    
    if not success:
        print("\n❌ Some uploads failed. Please check the errors above.")
        return False
    
    print("\n" + "=" * 70)
    print("✅ DEPLOYMENT COMPLETE\n")
    
    print("📊 Next Steps:\n")
    
    print("1️⃣  ATTACH TO SQL WAREHOUSE")
    print("   - Open: https://dbc-0b583d12-fb33.cloud.databricks.com/sql/editor/worst_professors_dashboard")
    print("   - Click 'Use Warehouse' dropdown (top right)")
    print("   - Select your SQL warehouse (or create one)")
    print("   - Run the notebook to generate dashboard data\n")
    
    print("2️⃣  CREATE LAKEVIEW DASHBOARD")
    print("   - Go to: https://dbc-0b583d12-fb33.cloud.databricks.com/sql/dashboards")
    print("   - Click '+ Create' → 'Lakeview dashboard'")
    print("   - Title: 'TAMU Worst Professors Dashboard'")
    print("   - Add visualizations from the queries in worst_professors_lakeview notebook:\n")
    print("     • Worst Professors (Top 20) - Table visualization")
    print("     • Hardest Courses - Table with sorting")
    print("     • Worst Professors by College - Table")
    print("     • Grade Distribution - Stacked bar chart")
    print("     • Summary Metrics - Scalar widgets (KPIs)")
    print("     • GPA Trend - Line chart over time")
    print("     • College Comparison - Bar chart\n")
    
    print("3️⃣  SCHEDULE WEEKLY JOB")
    print("   - Go to: https://dbc-0b583d12-fb33.cloud.databricks.com/jobs")
    print("   - Click '+ Create job'")
    print("   - Name: 'Worst Professors Analysis (Weekly)'")
    print("   - Task Type: SQL")
    print("   - Notebook path: /Shared/tamu-grade-report/worst_professors_lakeview")
    print("   - Warehouse: Select your SQL warehouse")
    print("   - Schedule: Mondays, 2:00 AM (America/Chicago)")
    print("   - Email on failure: connor.l.oswalt@gmail.com")
    print("   - Click 'Create Job'\n")
    
    print("   OR use Databricks Bundles to deploy automatically:")
    print("   - Update resources/worst_professors_job.yml with your warehouse ID")
    print("   - Run: databricks bundle deploy --target prod\n")
    
    print("4️⃣  SHARE & MONITOR")
    print("   - Open dashboard")
    print("   - Click 'Share' to give others view/edit access")
    print("   - Monitor job runs in Jobs section")
    print("   - Check alerts on failure\n")
    
    print("=" * 70)
    print("📚 Documentation:")
    print("   - WORST_PROFESSORS_README.md - Full analysis documentation")
    print("   - databricks/worst_professors_dashboard.sql - Query reference")
    print("   - databricks/worst_professors_lakeview.sql - Dashboard queries")
    print("=" * 70)
    
    return True

if __name__ == "__main__":
    success = deploy_to_databricks()
    sys.exit(0 if success else 1)
