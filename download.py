"""
download.py - Parallel PDF downloader for TAMU grade reports

Handles URL generation, file existence checks, retries, and concurrent downloads.
"""

import time
import logging
import random
from pathlib import Path
from typing import Tuple, List, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from config import (
    REPORT_URL_TEMPLATES,
    SEMESTER_URL_CODE,
    COLLEGE_CODES,
    PDF_DIR,
    CONCURRENCY,
    RETRY_ATTEMPTS,
    BACKOFF_FACTOR,
    INTER_BATCH_SLEEP,
)


def build_url(year: int, semester: int, report_type: str, college: str) -> str:
    """
    Construct the full URL for a given year/semester/type/college combination.
    """
    semester_code = SEMESTER_URL_CODE.get(semester)
    if not semester_code:
        raise ValueError(f"Invalid semester code: {semester}")

    template = REPORT_URL_TEMPLATES.get(report_type)
    if not template:
        raise ValueError(f"Unknown report type: {report_type}")

    return template.format(
        year=year,
        term=semester_code,
        college_code=college
    )


def get_local_path(
    year: int,
    semester: int,
    report_type: str,
    college: str,
    pdf_dir: Path = PDF_DIR
) -> Path:
    """
    Generate consistent local filename and path.
    grd reports are nested under a 'grd' subfolder (matching main.py's expected
    layout); gpad/gpac reports stay flat in pdf_dir.
    Example: data/pdfs/grd/grd_2023_3_EN.pdf, data/pdfs/gpac_2023_3_EN.pdf
    """
    semester_str = f"{semester:01d}"
    filename = f"{report_type}_{year}_{semester_str}_{college}.pdf"
    if report_type == "grd":
        return pdf_dir / "grd" / filename
    return pdf_dir / filename


def generate_all_urls_and_paths(
    years: int,
    semesters: int,
    report_types: str,
    colleges: str,
    pdf_dir: Path = PDF_DIR
) -> Tuple[str, Path]:
    """
    Generate list of (url, local_path) tuples for all combinations.
    """
    tasks = []
    for year in years:
        for sem in semesters:
            for rtype in report_types:
                for college in colleges:
                    url = build_url(year, sem, rtype, college)
                    path = get_local_path(year, sem, rtype, college, pdf_dir)
                    tasks.append((url, path))
    return tasks


def is_file_valid(path: Path, min_size_bytes: int = 2048) -> bool:
    """
    Check if file exists, is not empty, and has reasonable size.
    (TAMU grade PDFs are usually >10 KB even for small reports)
    """
    if not path.exists():
        return False
    if path.stat().st_size < min_size_bytes:
        logging.warning(f"File too small, probably corrupt: {path}")
        return False
    return True


def download_pdf(
    url: str,
    path: Path,
    retries: int = RETRY_ATTEMPTS,
    backoff_factor: float = BACKOFF_FACTOR,
    timeout: int = 30
) -> Tuple[bool, str]:
    """
    Returns:
        (success: bool, message: str)
        - True + "downloaded" / "already exists" → good
        - True + "404 - does not exist" → intentional skip (not an error)
        - False + reason → real failure
    """
    if is_file_valid(path):
        return True, "already exists"

    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],          # ← IMPORTANT: do NOT retry 404
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "User-Agent": "TAMU-Grade-Consolidator/1.0 (research/education; contact: your.email@example.com)"
    }

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=timeout, stream=True)

            if resp.status_code == 404:
                return True, "404 - file does not exist on server"

            resp.raise_for_status()

            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            if is_file_valid(path):
                return True, f"downloaded ({path.stat().st_size:,} bytes)"
            else:
                path.unlink(missing_ok=True)
                return False, "downloaded but invalid size"

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return True, "404 - file does not exist on server"
            if attempt == retries:
                return False, f"HTTP error after {retries} attempts: {str(e)}"
            time.sleep(backoff_factor ** attempt + random.uniform(0, 0.5))

        except requests.exceptions.RequestException as e:
            if attempt == retries:
                return False, f"failed after {retries} attempts: {str(e)}"
            time.sleep(backoff_factor ** attempt + random.uniform(0, 0.5))

    return False, "max retries exceeded"


def download_all(
    tasks: List[Tuple[str, Path]],
    max_workers: int = CONCURRENCY,
    batch_size: int = None
) -> None:
    """
    Download all PDFs in parallel with progress bar.
    Optional batch_size to insert delays between groups of requests.
    """
    if not tasks:
        logging.info("No PDFs to download.")
        return

    logging.info(f"Starting download of {len(tasks)} files (max {max_workers} concurrent)")

    results = []
    completed = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(download_pdf, url, path): (url, path)
            for url, path in tasks
        }

        for future in tqdm(
            as_completed(future_to_task),
            total=len(tasks),
            desc="Downloading TAMU PDFs",
            unit="file"
        ):
            url, path = future_to_task[future]
            try:
                success, msg = future.result()
                results.append((url, success, msg))
                completed += 1
                if success:
                    logging.debug(f"OK: {path.name} → {msg}")
                else:
                    logging.warning(f"FAIL: {path.name} → {msg}")
            except Exception as exc:
                logging.error(f"Unexpected error for {url}: {exc}")

            # Optional polite delay between individual successful downloads
            if batch_size and completed % batch_size == 0 and completed < len(tasks):
                time.sleep(INTER_BATCH_SLEEP)

    success_count = sum(1 for _, s, _ in results if s)
    logging.info(f"Download finished: {success_count}/{len(tasks)} successful")


if __name__ == "__main__":
    from config import (
        DEFAULT_YEARS_TO_PROCESS_FIRST,
        REPORT_TYPES,
        COLLEGE_CODES,
    )

    logging.basicConfig(level=logging.INFO)

    # De-dupe COLLEGE_CODES (config.py has a couple of accidental repeats)
    colleges = list(dict.fromkeys(COLLEGE_CODES))
    semesters = list(SEMESTER_URL_CODE.keys())

    tasks = generate_all_urls_and_paths(
        years=DEFAULT_YEARS_TO_PROCESS_FIRST,
        semesters=semesters,
        report_types=REPORT_TYPES,
        colleges=colleges,
    )
    logging.info(f"Checking {len(tasks)} possible report files (existing valid files are skipped)")
    download_all(tasks)