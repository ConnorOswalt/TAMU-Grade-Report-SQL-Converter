# sql_handler.py
import sqlite3
import pandas as pd
from typing import Optional


def connect_to_db(db_path: str, check_same_thread: bool = False) -> sqlite3.Connection:
    """Connect to SQLite database (creates file if it doesn't exist)."""
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    print(f"Connected to SQLite: {db_path}")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if the specified table exists."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None

def append_dataframe_to_db(
    df: pd.DataFrame,
    conn: sqlite3.Connection,
    table_name: str = "grade_distributions",
    if_exists: str = "append"
) -> bool:
    """
    Append DataFrame to the SQLite table.
    If the table already exists and some columns in df are missing from the table,
    automatically drop those extra columns from df before appending.
    """
    if df.empty:
        print("Warning: Empty DataFrame — nothing appended.")
        return False

    try:
        # If table doesn't exist yet, just append (it will create table with all columns)
        if not table_exists(conn, table_name):
            df.to_sql(table_name, conn, if_exists=if_exists, index=False, method="multi")
            conn.commit()
            print(f"Created table '{table_name}' and appended {len(df)} rows")
            return True

        # Table exists → check existing columns
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_cols = {row[1] for row in cursor.fetchall()}

        # Find columns in df that are NOT in the table
        extra_cols = set(df.columns) - existing_cols

        if extra_cols:
            print(f"Warning: Found {len(extra_cols)} extra column(s) in DataFrame "
                  f"that do not exist in table '{table_name}' → removing them")
            print(f"  Removed columns: {', '.join(extra_cols)}")
            # Drop the extra columns from the DataFrame
            df = df.drop(columns=extra_cols)

        # Now safe to append
        df.to_sql(
            table_name,
            conn,
            if_exists=if_exists,
            index=False,
            method="multi"
        )
        conn.commit()
        print(f"Appended {len(df)} rows to table '{table_name}'")
        return True

    except sqlite3.OperationalError as e:
        err_msg = str(e).lower()
        if "has no column named" in err_msg:
            print(f"Still failed after column cleanup — possible deeper schema mismatch")
            print(f"  Error: {e}")
            return False
        else:
            raise

    except Exception as e:
        print(f"Unexpected error appending to '{table_name}': {e}")
        return False

def get_row_count(conn: sqlite3.Connection, table_name: str) -> int:
    """Return total rows in the table."""
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
    except Exception as e:
        print(f"Error counting rows in '{table_name}': {e}")
        return -1


def close_connection(conn: Optional[sqlite3.Connection]):
    """Safely close the connection."""
    if conn:
        conn.close()
        print("SQLite connection closed.")


# sql_handler.py (add/replace this function)

def append_df_to_db(
    df: pd.DataFrame,
    db_path: str = "tamu_grades.db",
    table_name: str = "all_grade_distributions",
    if_exists: str = "append"
) -> bool:
    """
    Append a single DataFrame to the specified SQLite table.
    
    Features:
    - Creates table if it doesn't exist (using df's columns)
    - If table exists and df has extra columns → drops those extra columns from df
    - Safe commit, error handling, and feedback
    - Returns True if successful, False otherwise
    
    Usage example:
        success = append_df_to_db(my_dataframe, "grades.db", "grade_data")
    """
    import sqlite3

    if df.empty:
        print("Warning: Empty DataFrame — nothing appended.")
        return False

    conn = None
    try:
        # Connect
        conn = sqlite3.connect(db_path)
        print(f"Connected to database: {db_path}")

        # If table doesn't exist → create it
        if not table_exists(conn, table_name):
            df.to_sql(table_name, conn, if_exists="replace", index=False, method="multi")
            conn.commit()
            print(f"Created table '{table_name}' and appended {len(df)} rows")
            return True

        # Table exists → align columns
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_cols = {row[1] for row in cursor.fetchall()}

        # Drop extra columns from df
        extra_cols = set(df.columns) - existing_cols
        if extra_cols:
            print(f"Warning: Dropping {len(extra_cols)} extra column(s) not in table: {', '.join(extra_cols)}")
            df = df.drop(columns=extra_cols)

        # Append
        df.to_sql(
            table_name,
            conn,
            if_exists=if_exists,
            index=False,
            method="multi"
        )
        conn.commit()
        print(f"Appended {len(df)} rows to '{table_name}'")
        return True

    except sqlite3.OperationalError as e:
        err = str(e).lower()
        if "has no column named" in err:
            print(f"Column mismatch after cleanup: {e}")
            return False
        raise

    except Exception as e:
        print(f"Error appending DataFrame to '{table_name}': {e}")
        return False

    finally:
        if conn:
            conn.close()
            print("Database connection closed.")
