"""
Worst Professors Analysis
Analyzes instructor performance to identify professors giving lowest grades and highest fail rates.
"""

import pandas as pd
import glob
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_grade_distributions(grade_dist_dir: str = "data/parquet/grade_distributions") -> pd.DataFrame:
    """Load all grade distribution parquet files into a single DataFrame."""
    logger.info(f"Loading grade distributions from {grade_dist_dir}...")
    
    parquet_files = glob.glob(f"{grade_dist_dir}/**/*.parquet", recursive=True)
    logger.info(f"Found {len(parquet_files)} parquet files")
    
    dfs = []
    for file in parquet_files:
        try:
            df = pd.read_parquet(file)
            # Extract partitioning info from path
            parts = Path(file).parts
            for part in parts:
                if part.startswith("College="):
                    df['College'] = part.replace("College=", "").replace("%20", " ")
                elif part.startswith("Year="):
                    df['Year'] = part.replace("Year=", "")
                elif part.startswith("Semester="):
                    df['Semester'] = part.replace("Semester=", "")
            dfs.append(df)
        except Exception as e:
            logger.warning(f"Failed to read {file}: {e}")
    
    df_combined = pd.concat(dfs, ignore_index=True)
    
    # Rename columns to remove spaces
    df_combined.columns = df_combined.columns.str.replace(' ', '_').str.replace('-', '_')
    
    logger.info(f"Loaded {len(df_combined)} total grade records")
    return df_combined


def analyze_worst_professors(df: pd.DataFrame, min_students: int = 500) -> pd.DataFrame:
    """
    Analyze instructor performance and rank by difficulty.
    
    Args:
        df: Grade distributions DataFrame
        min_students: Minimum number of students to include instructor
        
    Returns:
        DataFrame ranked by difficulty score
    """
    logger.info(f"Analyzing worst professors (min {min_students} students)...")
    
    # Clean data
    df = df[df['Instructor'].notna() & (df['Instructor'].str.strip() != '')]
    df = df[df['GPA'].notna() & df['Total'].notna()]
    
    # Group by instructor
    instructor_stats = df.groupby('Instructor').agg({
        'Class_Code': 'nunique',
        'Total': 'sum',
        'GPA': lambda x: (df.loc[x.index, 'GPA'] * df.loc[x.index, 'Total']).sum() / df.loc[x.index, 'Total'].sum(),
        'F': 'sum',
        'Total_A_F': 'sum',
        'Q': 'sum',
        'X': 'sum',
        'I': 'sum',
    }).rename(columns={
        'Class_Code': 'num_classes',
        'Total': 'total_students',
        'GPA': 'weighted_gpa',
        'F': 'total_f_grades',
        'Total_A_F': 'total_af_grades',
        'Q': 'total_drops',
        'X': 'total_missing',
        'I': 'total_incomplete',
    })
    
    # Calculate rates
    instructor_stats['fail_rate_pct'] = (instructor_stats['total_f_grades'] / instructor_stats['total_af_grades'] * 100).round(2)
    instructor_stats['drop_incomplete_rate_pct'] = (
        (instructor_stats['total_drops'] + instructor_stats['total_missing'] + instructor_stats['total_incomplete']) 
        / instructor_stats['total_students'] * 100
    ).round(2)
    
    # Composite difficulty score: (100 - weighted_gpa * 25) + (fail_rate_pct * 2)
    instructor_stats['difficulty_score'] = (
        (100 - instructor_stats['weighted_gpa'] * 25) + (instructor_stats['fail_rate_pct'] * 2)
    ).round(2)
    
    # Filter by minimum students
    instructor_stats = instructor_stats[instructor_stats['total_students'] >= min_students]
    
    # Round GPA
    instructor_stats['weighted_gpa'] = instructor_stats['weighted_gpa'].round(3)
    
    logger.info(f"Found {len(instructor_stats)} instructors with >= {min_students} students")
    
    return instructor_stats.sort_values('difficulty_score', ascending=False)


def analyze_worst_professors_by_college(df: pd.DataFrame, min_students: int = 100) -> pd.DataFrame:
    """Analyze worst professors within each college."""
    logger.info(f"Analyzing worst professors by college (min {min_students} students)...")
    
    # Clean data
    df = df[df['Instructor'].notna() & (df['Instructor'].str.strip() != '')]
    df = df[df['GPA'].notna() & df['Total'].notna() & df['College'].notna()]
    
    # Group by college and instructor
    college_stats = df.groupby(['College', 'Instructor']).agg({
        'Class_Code': 'nunique',
        'Total': 'sum',
        'GPA': lambda x: (df.loc[x.index, 'GPA'] * df.loc[x.index, 'Total']).sum() / df.loc[x.index, 'Total'].sum(),
        'F': 'sum',
        'Total_A_F': 'sum',
    }).rename(columns={
        'Class_Code': 'num_classes',
        'Total': 'total_students',
        'GPA': 'weighted_gpa',
        'F': 'total_f_grades',
        'Total_A_F': 'total_af_grades',
    })
    
    college_stats['fail_rate_pct'] = (college_stats['total_f_grades'] / college_stats['total_af_grades'] * 100).round(2)
    college_stats['weighted_gpa'] = college_stats['weighted_gpa'].round(3)
    
    # Filter by minimum students
    college_stats = college_stats[college_stats['total_students'] >= min_students]
    
    return college_stats.sort_values(['College', 'weighted_gpa'], ascending=[True, True])


def analyze_hardest_courses(df: pd.DataFrame, min_students: int = 200) -> pd.DataFrame:
    """Find the hardest individual courses."""
    logger.info(f"Analyzing hardest courses (min {min_students} students)...")
    
    # Clean data
    df = df[df['GPA'].notna() & df['Total'].notna()]
    
    # Group by course
    course_stats = df.groupby('Class_Code').agg({
        'College': 'first',
        'Total': 'sum',
        'GPA': lambda x: (df.loc[x.index, 'GPA'] * df.loc[x.index, 'Total']).sum() / df.loc[x.index, 'Total'].sum(),
        'F': 'sum',
        'Total_A_F': 'sum',
        'A': 'sum',
        'B': 'sum',
    }).rename(columns={
        'Total': 'total_students',
        'GPA': 'weighted_gpa',
        'F': 'total_f_grades',
        'Total_A_F': 'total_af_grades',
        'A': 'total_a_grades',
        'B': 'total_b_grades',
    })
    
    course_stats['fail_rate_pct'] = (course_stats['total_f_grades'] / course_stats['total_af_grades'] * 100).round(2)
    course_stats['ab_rate_pct'] = ((course_stats['total_a_grades'] + course_stats['total_b_grades']) / course_stats['total_af_grades'] * 100).round(2)
    course_stats['weighted_gpa'] = course_stats['weighted_gpa'].round(3)
    
    # Filter by minimum students
    course_stats = course_stats[course_stats['total_students'] >= min_students]
    
    return course_stats.sort_values('weighted_gpa', ascending=True)


def print_report(df: pd.DataFrame, title: str, top_n: int = 20):
    """Print a formatted report."""
    print("\n" + "="*120)
    print(f"{title}")
    print("="*120)
    print(df.head(top_n).to_string())
    print()


def main():
    # Load data
    df = load_grade_distributions()
    
    # Analyze worst professors overall
    worst_professors = analyze_worst_professors(df, min_students=500)
    print_report(worst_professors, "Top 20 Worst Professors (Difficulty Score - Based on GPA & Fail Rate)", top_n=20)
    
    # Analyze by GPA only
    worst_by_gpa = worst_professors.sort_values('weighted_gpa', ascending=True)
    print_report(worst_by_gpa, "Top 20 Worst Professors by Weighted GPA", top_n=20)
    
    # Analyze by fail rate only
    worst_by_fail = worst_professors.sort_values('fail_rate_pct', ascending=False)
    print_report(worst_by_fail, "Top 20 Worst Professors by Fail Rate %", top_n=20)
    
    # Analyze by college
    college_worst = analyze_worst_professors_by_college(df, min_students=100)
    print("\n" + "="*120)
    print("Worst Professors by College (Sample - 5 per college)")
    print("="*120)
    for college in college_worst.index.get_level_values(0).unique()[:5]:
        college_data = college_worst.loc[college].head(5)
        print(f"\n{college}:")
        print(college_data.to_string())
    print()
    
    # Analyze hardest courses
    hardest_courses = analyze_hardest_courses(df, min_students=200)
    print_report(hardest_courses, "Top 30 Hardest Individual Courses (min 200 students)", top_n=30)
    
    # Summary statistics
    logger.info("\n" + "="*120)
    logger.info("SUMMARY STATISTICS")
    logger.info("="*120)
    logger.info(f"Total instructors analyzed: {len(worst_professors)}")
    logger.info(f"Average GPA across all instructors: {worst_professors['weighted_gpa'].mean():.3f}")
    logger.info(f"Median GPA: {worst_professors['weighted_gpa'].median():.3f}")
    logger.info(f"25th percentile GPA: {worst_professors['weighted_gpa'].quantile(0.25):.3f}")
    logger.info(f"75th percentile GPA: {worst_professors['weighted_gpa'].quantile(0.75):.3f}")
    logger.info(f"Average fail rate: {worst_professors['fail_rate_pct'].mean():.2f}%")
    logger.info(f"Median fail rate: {worst_professors['fail_rate_pct'].median():.2f}%")
    logger.info("="*120 + "\n")


if __name__ == "__main__":
    main()
