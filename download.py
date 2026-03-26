"""
download.py - Parallel PDF downloader for TAMU grade reports

Improved version with:
- Proper file skipping
- Graceful Ctrl+C handling
- Clear 404 handling
- Better logging
"""

import time
import random
import logging
from pathlib import Path
from typing import Tuple, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from config import (
    URL_TEMPLATE,
    SEMESTER_URL_CODE,
    REPORT_TYPE_PREFIX,
    COLLEGE_CODES,
    PDF_DIR,
    CONCURRENCY,
    RETRY_ATTEMPTS,
    BACKOFF_FACTOR,
)


def build_url(year: int, semester: int, report_type: str, college: str) -> str:
    """Construct the full URL for a TAMU grade report."""
    semester_code = SEMESTER_URL_CODE.get(semester)
    if not semester_code:
        raise ValueError(f"Invalid semester: {semester}")

    rtype_prefix = REPORT_TYPE_PREFIX.get(report_type)
    if not rtype_prefix:
        raise ValueError(f"Unknown report type: {report_type}")

    return URL_TEMPLATE.format(
        year=year,
        semester_code=semester_code,
        rtype_prefix=rtype_prefix,
        college_code=college
    )


def get_local_path(year: int, semester: int, report_type: str, college: str) -> Path:
    """Generate consistent local filename."""
    semester_str = f"{semester:01d}"
    filename = f"{report_type}_{year}_{semester_str}_{college}.pdf"
    return PDF_DIR / filename


def generate_all_urls_and_paths(
    years: List[int],
    semesters: List[int],
    report_types: List[str],
    colleges: List[str] = None
) -> List[Tuple[str, Path]]:
    """Generate list of (url, local_path) for all combinations."""
    if colleges is None:
        colleges = COLLEGE_CODES

    tasks = []
    for year in years:
        for sem in semesters:
            for rtype in report_types:
                for college in colleges:
                    url = build_url(year, sem, rtype, college)
                    path = get_local_path(year, sem, rtype, college)
                    tasks.append((url, path))
    return tasks


def is_file_valid(path: Path, min_size_bytes: int = 4096) -> bool:
    """Check if file exists and looks like a valid PDF."""
    if not path.exists():
        return False
    if path.stat().st_size < min_size_bytes:
        return False

    # Quick PDF header check
    try:
        with path.open("rb") as f:
            header = f.read(8)
            return header.startswith(b"%PDF-")
    except Exception:
        return False


def download_pdf(
    url: str,
    path: Path,
    retries: int = RETRY_ATTEMPTS,
    backoff_factor: float = BACKOFF_FACTOR,
    timeout: int = 30
) -> Tuple[bool, str]:
    """
    Download a single PDF.
    Returns (success, message)
    """
    if is_file_valid(path):
        return True, "already exists"

    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],   # Do NOT retry 404
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "User-Agent": "TAMU-Grade-Consolidator/1.0 (research/education purpose)"
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
                return False, "downloaded but invalid"

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return True, "404 - file does not exist on server"
            if attempt == retries:
                return False, f"HTTP {e.response.status_code} after {retries} attempts"
            time.sleep(backoff_factor ** attempt + random.uniform(0, 0.5))

        except requests.exceptions.RequestException as e:
            if attempt == retries:
                return False, f"Request failed after {retries} attempts: {str(e)}"
            time.sleep(backoff_factor ** attempt + random.uniform(0, 0.5))

    return False, "max retries exceeded"


def download_all(
    tasks: List[Tuple[str, Path]],
    max_workers: int = CONCURRENCY
) -> None:
    """Download all missing PDFs in parallel with graceful shutdown."""
    if not tasks:
        logging.info("No PDFs to download.")
        return

    # Filter only files that need downloading
    tasks_to_download = [(url, path) for url, path in tasks if not is_file_valid(path)]

    logging.info(f"Total potential files: {len(tasks)}")
    logging.info(f"Already valid: {len(tasks) - len(tasks_to_download)}")
    logging.info(f"Need to download: {len(tasks_to_download)}")

    if not tasks_to_download:
        logging.info("All files already downloaded.")
        return

    success_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(download_pdf, url, path, retries=RETRY_ATTEMPTS, backoff_factor=BACKOFF_FACTOR): 
            (url, path) for url, path in tasks_to_download
        }

        try:
            for future in tqdm(as_completed(future_to_task), total=len(tasks_to_download), desc="Downloading"):
                url, path = future_to_task[future]
                try:
                    success, msg = future.result()
                    if success:
                        if "404" in msg:
                            logging.info(f"Skipped (does not exist): {path.name}")
                        elif "already exists" in msg:
                            logging.debug(f"Skipped (already exists): {path.name}")
                        else:
                            logging.info(f"Downloaded: {path.name}")
                            success_count += 1
                    else:
                        logging.warning(f"Failed: {path.name} → {msg}")
                except Exception as e:
                    logging.error(f"Unexpected error downloading {url}: {e}")
        except KeyboardInterrupt:
            logging.warning("Download interrupted by user (Ctrl+C)")
            executor.shutdown(wait=False, cancel_futures=True)
            raise

    logging.info(f"Download finished: {success_count}/{len(tasks_to_download)} successful")