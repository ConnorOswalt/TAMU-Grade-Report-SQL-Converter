import tabula
import pandas as pd
import sqlite3
from typing import List, Optional, Union

def pdf_to_dataframe(
    pdf_path: str,
    pages: str = "all",
    final_column_names: Optional[List[str]] = None,
    lattice: bool = False,
    stream: bool = True,
    multiple_tables: bool = True,
    guess: bool = True,
    pandas_options: Optional[dict] = None
) -> pd.DataFrame:
    """
    Extract tables from PDF.
    Drops leading all-NaN / empty columns per table to fix left-side misalignment.
    Aligns all tables to the maximum number of columns found.
    """
    try:
        if pandas_options is None:
            pandas_options = {'header': None}


        dfs = tabula.read_pdf(
            pdf_path,
            pages=pages,
            lattice=lattice,
            stream=stream,
            multiple_tables=multiple_tables,
            guess=guess,
            pandas_options=pandas_options
        )

        if not dfs:
            print("→ No tables detected")
            return pd.DataFrame()



        processed = []
        max_cols = 0

        for i, df in enumerate(dfs):
            # Replace empty strings with NaN
            df = df.replace(r'^\s*$', pd.NA, regex=True)

            # Drop leading columns that are completely NaN / empty
            while not df.empty and df.iloc[:, 0].isna().all():
                df = df.iloc[:, 1:].reset_index(drop=True)


            # Also drop trailing empty columns (optional but often helpful)
            while not df.empty and df.iloc[:, -1].isna().all():
                df = df.iloc[:, :-1]

            if df.empty:
                continue

            processed.append(df)
            max_cols = max(max_cols, df.shape[1])

        if not processed:
            print("→ No non-empty tables after cleanup")
            return pd.DataFrame()

        # Align all tables to the widest one (add NaN columns on the right if needed)
        aligned = []
        for df in processed:
            if df.shape[1] < max_cols:
                extra = max_cols - df.shape[1]
                for _ in range(extra):
                    df[f"extra_{df.shape[1]}"] = pd.NA
            aligned.append(df)

        # Concatenate
        combined = pd.concat(aligned, ignore_index=True, sort=False)

        # Optional: rename to user-provided names if count matches
        if final_column_names is not None:
            if len(final_column_names) == combined.shape[1]:
                combined.columns = final_column_names



        return combined

    except Exception as e:

        return pd.DataFrame()
    
def remove_rows_with_keywords(df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    """
    Remove rows where any cell contains one of the given keywords (case-insensitive).
    Safely handles NaN, numbers, None, etc.
    """
    if df.empty or not keywords:
        return df.copy()

    # Convert keywords to lowercase once
    keywords = [k.lower() for k in keywords]

    # Convert entire DataFrame to string, replace NaN/None with empty string
    df_str = df.astype(str).fillna('')

    # Work row-by-row
    def row_contains_keyword(row):
        # Join all cell values with space → lowercase → check if any keyword is substring
        text = ' '.join(row).lower()
        return any(kw in text for kw in keywords)

    # Create mask: True = KEEP the row (no keyword found)
    mask = ~df_str.apply(row_contains_keyword, axis=1)

    cleaned = df[mask].copy()

    removed = len(df) - len(cleaned)


    return cleaned



    """
    Renames all columns of the DataFrame to the exact list of names provided.
    
    Args:
        df: The pandas DataFrame to rename columns for
        new_column_names: List of strings to use as the new column names
        
    Returns:
        A new DataFrame with renamed columns (original is unchanged)
        
    Raises:
        ValueError: If the number of new names doesn't match the number of columns
    """
    if len(new_column_names) != len(df.columns):
        raise ValueError(
            f"Number of new column names ({len(new_column_names)}) "
            f"does not match number of columns in DataFrame ({len(df.columns)})"
        )
    
    # Create a copy to avoid modifying the original
    df_renamed = df.copy()
    
    # Do the renaming
    df_renamed.columns = new_column_names
    
    return df_renamed

def insert_column_names_as_first_row(df: pd.DataFrame) -> pd.DataFrame:
    """
    Inserts the current column names as the first row of the DataFrame (as data),
    shifting all existing rows down by one.
    
    Useful for debugging or when you want the header visible as a data row.
    """
    if df.empty:
        return df.copy()

    # Create a new row with the column names
    header_row = pd.DataFrame([df.columns.tolist()], columns=df.columns)

    # Concatenate: header row on top + original data below
    df_new = pd.concat([header_row, df], ignore_index=True)

    return df_new

def rename_columns_loose(df: pd.DataFrame, new_names: List[str]) -> pd.DataFrame:
    """
    Renames columns using the provided list.
    If the list is shorter → keeps original names for remaining columns.
    If the list is longer → ignores extra names.
    """
    rename_dict = {old: new for old, new in zip(df.columns, new_names)}
    return df.rename(columns=rename_dict)

def convert_columns_to_int(
    df: pd.DataFrame,
    columns: Union[str, List[str]],
    errors: str = 'coerce',
    fillna_value: int = 0,
    inplace: bool = False
) -> pd.DataFrame:
    """
    Converts one or more columns to integer type.
    
    Handles common problems:
    - non-numeric values → become NaN (then filled with fillna_value)
    - strings with commas ("1,234") → removed
    - floats → truncated to int
    
    Parameters:
        df           : pandas DataFrame
        columns      : column name or list of column names to convert
        errors       : 'coerce' → invalid values become NaN
                       'raise'  → raise error on invalid values
        fillna_value : value to replace NaN after conversion (default: 0)
        inplace      : modify the original DataFrame (default: False)
    
    Returns:
        DataFrame with converted columns (new copy unless inplace=True)
    """
    # Make copy if not inplace
    df_work = df if inplace else df.copy()

    # Normalize columns to list
    if isinstance(columns, str):
        columns = [columns]

    # Check columns exist
    missing = [col for col in columns if col not in df_work.columns]
    if missing:
        raise ValueError(f"Columns not found in DataFrame: {missing}")

    for col in columns:
        # Clean common string issues
        if df_work[col].dtype == 'object' or df_work[col].dtype == 'string':
            # Remove commas, spaces, etc.
            df_work[col] = df_work[col].astype(str).str.replace(r'[,\s]', '', regex=True)

        # Convert to numeric (float first, then int)
        df_work[col] = pd.to_numeric(df_work[col], errors=errors, downcast='integer')

        # Fill NaN with chosen value
        df_work[col] = df_work[col].fillna(fillna_value)

        # Final cast to int (after fillna)
        df_work[col] = df_work[col].astype('int64')  # or 'Int64' if you want nullable integer

    return df_work

standard_grade_columns = [
    'Section',
    'A',
    'B',
    'C',
    'D',
    'F',
    'Total A-F',    # or 'Total Graded'
    'GPA',
    'I',           # Incomplete (sometimes present)
    'S',           # Satisfactory
    'U',           # Unsatisfactory
    'Q',
    'X',           
    'Total',
    'Instructor',  # or just 'GPA'
    ' '
]

def grd_to_df(grd_path):
    df = pdf_to_dataframe(
        pdf_path=grd_path,
        pages="all",
    )
    df = rename_columns_loose(df, standard_grade_columns)
    df = remove_rows_with_keywords(df, ["%","TOTAL"])
    return df





