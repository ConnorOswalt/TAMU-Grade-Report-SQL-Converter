#!/usr/bin/env python
"""
Utility script to find your Databricks SQL Warehouse ID for job scheduling.
"""

import sys
from databricks.sdk import WorkspaceClient

def get_sql_warehouses():
    """List all available SQL warehouses."""
    
    try:
        client = WorkspaceClient()
        print("🔍 Finding SQL Warehouses in your Databricks workspace...\n")
        
        warehouses = client.warehouses.list()
        warehouse_list = list(warehouses)
        
        if not warehouse_list:
            print("❌ No SQL warehouses found.")
            print("\nYou can create one:")
            print("  1. Go to: https://dbc-0b583d12-fb33.cloud.databricks.com/sql/warehouses")
            print("  2. Click '+ Create warehouse'")
            print("  3. Select cluster size (e.g., 'Small')")
            print("  4. Click 'Create'")
            return False
        
        print(f"Found {len(warehouse_list)} warehouse(s):\n")
        print("Copy the ID of your warehouse and paste it in databricks.yml:\n")
        print("-" * 80)
        
        for i, wh in enumerate(warehouse_list, 1):
            status = "🟢 Running" if wh.state and "RUNNING" in str(wh.state) else "⏸️  Stopped"
            name = wh.name or "Unnamed"
            print(f"\n{i}. {name}")
            print(f"   Status: {status}")
            print(f"   ID: {wh.id}")
            print(f"   Type: {wh.cluster_size}")
        
        print("\n" + "-" * 80)
        print("\n✅ To use a warehouse for the worst professors job:")
        print("   1. Edit: resources/worst_professors_job.yml")
        print("   2. Update sql_warehouse_id in databricks.yml")
        print("   3. Run: databricks bundle deploy --target prod")
        print("\nOR deploy manually using the ID in the Databricks UI")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n⚠️  Make sure you've set up Databricks authentication:")
        print("   Set environment variables or ~/.databricks/config")
        print("   See DATABRICKS_DEPLOYMENT_GUIDE.md for details")
        return False

if __name__ == "__main__":
    success = get_sql_warehouses()
    sys.exit(0 if success else 1)
