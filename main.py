# main.py
import os
import sqlite3
from converter import grd_to_df
from sql_handler import append_df_to_db
import pandas as pd

pdf_folder='./data/pdfs/grd'  # ← change to your folder path
pdf_files = [f for f in os.listdir(pdf_folder) if f.lower().endswith('.pdf')]

def parse_grd_filename(filename: str) -> list[str]:
    """
    Parse a TAMU grade distribution PDF filename and return:
    [year, semester_name, college_name]

    Expected format: grd_YYYY_S_COLLEGE.pdf
    - YYYY: 4-digit year
    - S: semester code (1=Spring, 2=Summer, 3=Fall)
    - COLLEGE: 2-letter college code

    Returns: list of 3 strings, or ["Unknown"]*3 if parsing fails
    """
    # Remove path and extension if present
    base = os.path.basename(filename).removesuffix('.pdf').removesuffix('.PDF')

    # Split on underscore
    parts = base.split('_')

    # We expect exactly 4 parts: ['grd', 'YYYY', 'S', 'COLLEGE']

    if len(parts) != 4 or parts[0].lower() != 'grd':
        print(f"Warning: Unexpected filename format: {filename}")
        return ["Unknown", "Unknown", "Unknown"]

    year = parts[1]
    semester_code = parts[2]
    college_code = parts[3].upper()

    # Semester mapping
    semester_map = {
        '1': 'Spring',
        '2': 'Summer',
        '3': 'Fall'
    }
    semester = semester_map.get(semester_code, semester_code)  # fallback to code if unknown

    # College mapping (expand as needed)
    college_map = {
        'MD': 'Medicine',
        'NU': 'Nursing',
        'EN': 'Engineering',
        'BA': 'Business',
        'ED': 'Education',
        'LA': 'Liberal Arts',
        'SC': 'Science',
        'AG': 'Agriculture',
        'AR': 'Architecture',
        'GB': 'Bush School of Government and Public Service',
        'GE' : 'Geosciences',
        'GV': 'Galveston',
        'QT': 'Qatar',
        'VM': 'Veterinary Medicine',


        # Add more college codes here
    }
    college = college_map.get(college_code, college_code)  # fallback to code

    return [college, year, semester]

def prepend_columns_with_values(
    df: pd.DataFrame,
    new_headers: list,
    new_values: list
) -> pd.DataFrame:
    """
    Adds new columns at the beginning (left) of the DataFrame.
    Populates every data row (not the header) with the given value.

    Parameters:
        df          : Existing DataFrame (can be empty)
        new_headers : List of new column names (e.g. ["College", "Year", "Semester"])
        new_values  : List of values (same length as new_headers)
                       Each value will be repeated down the entire column

    Returns:
        Updated DataFrame with new columns prepended

    Example:
        df = pd.DataFrame({
            "Course": ["CS101", "MATH202"],
            "Grade": ["A", "B"]
        })
        df = prepend_columns_with_values(df, ["College", "Year"], ["Engineering", 2023])
        # Result:
        #   College  Year  Course Grade
        # 0 Engineering  2023   CS101     A
        # 1 Engineering  2023  MATH202    B
    """
    if len(new_headers) != len(new_values):
        raise ValueError("new_headers and new_values must have the same length")

    # Convert to Series so we can easily align
    new_data = pd.Series(new_values, index=new_headers)

    if df.empty:
        # If DataFrame is empty, create it with just the new columns + one row
        return pd.DataFrame([new_values], columns=new_headers)

    # Add missing columns at the LEFT (beginning)
    missing = [h for h in new_headers if h not in df.columns]
    if missing:
        # Create new columns with the repeated value
        new_cols = pd.DataFrame(
            {h: [new_data[h]] * len(df) for h in missing},
            index=df.index
        )
        # Prepend: new columns LEFT + original df RIGHT
        df = pd.concat([new_cols, df], axis=1)

    # For columns that already existed → fill them with the new value
    for h in new_headers:
        if h in df.columns:
            df[h] = new_data[h]  # broadcast single value to whole column

    return df

def replace_section_with_split(df: pd.DataFrame, section_col: str = 'Section') -> pd.DataFrame:
    """
    Replaces the 'Section' column with two new columns in the same position:
      - 'Class Code' → everything before the last '-'
      - 'Section'    → the part after the last '-'
    
    The new 'Section' column contains just the section number (e.g. "501").
    The original 'Section' column is removed.
    
    If 'Section' column doesn't exist → returns df unchanged.
    Handles missing/invalid values → NaN in both new columns.
    
    Example:
        df['Section'] = ["MATH-151-501", "ENGR-101-200", "PHYS-202", None]
        → becomes:
          Class Code  Section  ...other columns...
        0   MATH-151      501
        1   ENGR-101      200
        2   PHYS-202      NaN
        3        NaN      NaN
    """
    df = df.copy()  # avoid modifying original

    if section_col not in df.columns:
        print(f"Warning: Column '{section_col}' not found — returning unchanged DataFrame")
        return df

    # Find position of the original column
    col_position = df.columns.get_loc(section_col)

    # Split on the last '-'
    split = df[section_col].astype(str).str.rsplit('-', n=1, expand=True)

    # Class Code = everything before last '-', Section = after
    class_code = split[0].str.strip()
    new_section = split[1].str.strip().replace('', pd.NA)

    # Create new DataFrame with the two columns
    new_cols = pd.DataFrame({
        'Class Code': class_code,
        'Section': new_section
    }, index=df.index)

    # Remove the old Section column
    df = df.drop(columns=[section_col])

    # Insert the two new columns at the original position
    df.insert(col_position, 'Class Code', new_cols['Class Code'])
    df.insert(col_position + 1, 'Section', new_cols['Section'])

    return df   

if not pdf_files:
    print(f"No PDF files found in: {pdf_folder}")
else:
    print(f"Found {len(pdf_files)} PDF file(s) in {pdf_folder}")
    pdf_files.sort()  # optional: process in alphabetical order

    # Main for loop
    for idx, pdf_filename in enumerate(pdf_files, 1):
        pdf_path = os.path.join(pdf_folder, pdf_filename)
        
        print(f"[{idx}/{len(pdf_files)}] Processing: {pdf_filename}")
        
        try:
            # Your conversion / processing code goes here
            df = grd_to_df(pdf_path)  # assuming you have this function
            
            if df.empty:
                print("  → Empty DataFrame — skipping")
                continue
            
            df = prepend_columns_with_values(df, ["College", "Year", "Semester"], parse_grd_filename(pdf_filename))
            df = replace_section_with_split(df, section_col='Section')
            # Append to database
            success = append_df_to_db(df, table_name="all_grade_distributions")
            
            if success:
                print(f"  → Success: {len(df)} rows appended")
            else:
                print("  → Append failed")
                
        except Exception as e:
            print(f"  → Error processing {pdf_filename}: {e}")
    
    print("\nAll PDFs processed.")