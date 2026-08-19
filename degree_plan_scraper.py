"""
degree_plan_scraper.py - Downloads TAMU degree plan pages (catalog.tamu.edu)

Fetches the raw HTML for each major's "Plan of Study Grid" page and caches it
to disk, mirroring the retry/caching style used in download.py.
"""

import time
import random
import logging
from pathlib import Path
from typing import Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    DEGREE_PLAN_SOURCES,
    DEGREE_PLAN_HTML_DIR,
    DEGREE_PLAN_USER_AGENT,
    DEGREE_PLAN_REQUEST_TIMEOUT,
    DEGREE_PLAN_RETRY_ATTEMPTS,
    DEGREE_PLAN_BACKOFF_FACTOR,
    DEGREE_PLAN_INTER_REQUEST_SLEEP,
)


def _slugify(name: str) -> str:
    """Turn a major name into a safe filename stem."""
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


def get_local_html_path(major: str, html_dir: Path = DEGREE_PLAN_HTML_DIR) -> Path:
    return html_dir / f"{_slugify(major)}.html"


def _build_session(retries: int, backoff_factor: float) -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_degree_plan_html(
    url: str,
    retries: int = DEGREE_PLAN_RETRY_ATTEMPTS,
    backoff_factor: float = DEGREE_PLAN_BACKOFF_FACTOR,
    timeout: int = DEGREE_PLAN_REQUEST_TIMEOUT,
) -> Optional[str]:
    """
    Download the raw HTML for a single degree plan page.
    Returns the HTML text, or None on failure.
    """
    session = _build_session(retries, backoff_factor)
    headers = {"User-Agent": DEGREE_PLAN_USER_AGENT}

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            if attempt == retries:
                logging.warning(f"Failed to fetch {url} after {retries} attempts: {e}")
                return None
            time.sleep(backoff_factor ** attempt + random.uniform(0, 0.5))

    return None


def get_or_fetch_html(
    major: str,
    url: str,
    html_dir: Path = DEGREE_PLAN_HTML_DIR,
    force_refresh: bool = False,
) -> Optional[str]:
    """
    Return cached HTML for a major if present, otherwise download and cache it.
    """
    path = get_local_html_path(major, html_dir)

    if not force_refresh and path.exists() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8")

    html = fetch_degree_plan_html(url)
    if html is None:
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


def fetch_all(
    sources: Dict[str, str] = DEGREE_PLAN_SOURCES,
    force_refresh: bool = False,
    sleep_between: float = DEGREE_PLAN_INTER_REQUEST_SLEEP,
) -> Dict[str, str]:
    """
    Fetch (or load cached) HTML for every major in `sources`.
    Returns {major: html}. Majors that fail to download are omitted.
    """
    results: Dict[str, str] = {}

    for major, url in sources.items():
        html = get_or_fetch_html(major, url, force_refresh=force_refresh)
        if html is None:
            logging.warning(f"Skipping '{major}' -- could not retrieve {url}")
            continue
        results[major] = html
        time.sleep(sleep_between)

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pages = fetch_all()
    print(f"Fetched/cached {len(pages)} of {len(DEGREE_PLAN_SOURCES)} degree plan pages")
