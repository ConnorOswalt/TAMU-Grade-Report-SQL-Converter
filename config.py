"""
config.py - Central configuration for TAMU Grade Consolidator

All paths, constants, codes, and tunable parameters live here.
"""

from pathlib import Path
import os
from datetime import datetime

# ────────────────────────────────────────────────────────────────
#  Directories & Files
# ────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"
PARQUET_DIR = DATA_DIR / "parquet"
SQLITE_DB_PATH = DATA_DIR / "grades.db"

# Ensure directories exist (you can call this from main.py if desired)
for d in [DATA_DIR, PDF_DIR, PARQUET_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ────────────────────────────────────────────────────────────────
#  Download / Concurrency Settings
# ────────────────────────────────────────────────────────────────

# How many PDFs to download at the same time
# 8–16 is usually a sweet spot; too high → TAMU may throttle or block
CONCURRENCY = 10

# Retry settings for failed downloads
RETRY_ATTEMPTS = 5
BACKOFF_FACTOR = 1.5          # exponential backoff: 1.5, 2.25, 3.375, ...

# Sleep between batches to be extra polite to the server (seconds)
INTER_BATCH_SLEEP = 1.0

# ────────────────────────────────────────────────────────────────
#  Academic Time Period
# ────────────────────────────────────────────────────────────────

START_YEAR = 2017
END_YEAR   = datetime.now().year   # auto-update to current year

# Semester codes used in TAMU URLs
SEMESTER_CODES = {
    1: "Spring",
    2: "Summer",
    3: "Fall"
}

# Most recent terms usually appear first — helpful for testing
DEFAULT_YEARS_TO_PROCESS_FIRST = list(range(END_YEAR, START_YEAR - 1, -1))

# ────────────────────────────────────────────────────────────────
#  Report Types & File Prefixes
# ────────────────────────────────────────────────────────────────

REPORT_TYPES = ["grd", "gpad", "gpac"]

REPORT_TYPE_PREFIX = {
    "grd":  "grd",     # per-section grade distribution
    "gpad": "gpad",    # term GPA by classification & gender
    "gpac": "gpac",    # cumulative GPA by classification & gender
}

# ────────────────────────────────────────────────────────────────
#  College / School Codes
# ────────────────────────────────────────────────────────────────
# These are the codes used in the TAMU grade report URLs
# (may change slightly over time — check registrar site occasionally)

COLLEGE_CODES = [
    "AG",        # Agriculture & Life Sciences
    "AR",        # Architecture
    "BA",        # Mays Business School
    "ED",        # Education & Human Development
    "EN",        # Engineering
    "GB",        # General Studies / University Studies
    "GE",        # Geosciences
    "LA",        # Liberal Arts
    "MD",        # Medicine (usually MD_PROF or similar)
    "NU",        # Nursing
    "PH",        # Pharmacy
    "SC",        # Science
    "VM",        # Veterinary Medicine
    "GV",        # Galveston
    "QT",        # Qatar
    # Professional / special programs
    "MD_PROF",   # College of Medicine – Professional
    "DN",        # Dentistry
    "LW",        # Law
    "PU",        # Public Health
    # Add others as discovered / needed
    "UN",        # Unassigned / Other
    "PH",        # Public Health
]

# Optional: group some colleges for reporting / aggregation
COLLEGE_GROUPS = {
    "STEM": ["EN", "SC", "GE", "AG"],
    "HEALTH": ["MD", "MD_PROF", "NU", "PH", "DN", "PU", "VM"],
    "BUSINESS": ["BA"],
    "LIBERAL_ARTS": ["LA"],
}

# ────────────────────────────────────────────────────────────────
#  Spark / Parquet Settings
# ────────────────────────────────────────────────────────────────

SPARK_PARTITION_COLS = ["year", "semester", "report_type", "college"]
# Order matters — most frequently filtered columns first

PARQUET_COMPRESSION = "snappy"      # snappy, gzip, zstd, none
PARQUET_ROW_GROUP_SIZE = 128 * 1024 * 1024   # 128 MB target

# Whether to try using Delta Lake format (requires delta-spark package)
USE_DELTA_LAKE = False

# ────────────────────────────────────────────────────────────────
#  SQLite Table Names
# ────────────────────────────────────────────────────────────────

SQLITE_TABLES = {
    "grade_distribution": "grade_distribution",   # per-section grades (grd)
    "gpa_distribution":   "gpa_distribution",     # term & cumulative GPA (gpad + gpac)
    # You can add more later (e.g. "course_catalog", "instructors", etc.)
}

# ────────────────────────────────────────────────────────────────
#  Logging & Debugging
# ────────────────────────────────────────────────────────────────

LOG_LEVEL = "INFO"          # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = PROJECT_ROOT / "tamu_grades.log"

# Show extra progress / debug info during parsing?
VERBOSE_PARSING = False

# ────────────────────────────────────────────────────────────────
#  URL Construction Template
# ────────────────────────────────────────────────────────────────

# Base pattern observed on TAMU registrar site (as of 2024–2025)
# May need adjustment if the URL structure changes
URL_TEMPLATE = (
    "https://web-as.tamu.edu/GradeReports/PDFReports/"
    "{year}{semester_code}/{rtype_prefix}{year}{semester_code}{college_code}.pdf"
)

# Semester code mapping for URL (sometimes just the number, sometimes letter)
SEMESTER_URL_CODE = {1: "1", 2: "2", 3: "3"}  # currently numeric

# ────────────────────────────────────────────────────────────────
#  Export / make available
# ────────────────────────────────────────────────────────────────

__all__ = [
    "PROJECT_ROOT", "DATA_DIR", "PDF_DIR", "PARQUET_DIR", "SQLITE_DB_PATH",
    "CONCURRENCY", "RETRY_ATTEMPTS", "BACKOFF_FACTOR",
    "START_YEAR", "END_YEAR", "SEMESTER_CODES",
    "REPORT_TYPES", "REPORT_TYPE_PREFIX",
    "COLLEGE_CODES", "COLLEGE_GROUPS",
    "SPARK_PARTITION_COLS", "PARQUET_COMPRESSION", "USE_DELTA_LAKE",
    "SQLITE_TABLES", "LOG_LEVEL", "LOG_FILE", "VERBOSE_PARSING",
    "URL_TEMPLATE", "SEMESTER_URL_CODE",
]