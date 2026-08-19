"""
degree_plan_normalizer.py - Parses TAMU CourseLeaf "Plan of Study Grid" HTML
into a tidy pandas DataFrame.

TAMU's undergraduate catalog (catalog.tamu.edu) is built on the CourseLeaf CMS.
Degree plan pages render a <table class="sc_plangrid"> per curriculum path,
grouped into year headers (First Year, Second Year, ...) and term headers
(Fall, Spring, Summer). Within each term, rows are one of:

  - a required course                          (row_type="course")
  - a requirement placeholder, e.g. "Science    (row_type="requirement_block")
    elective" or "University Core Curriculum"
  - a "Select one of the following:" header     (row_type="choice_header")
  - an indented option beneath a choice header  (row_type="choice_option")
  - a term subtotal ("Semester Credit Hours")   (row_type="term_subtotal")
  - a plan grand total ("Total Semester         (row_type="plan_total")
    Credit Hours")

This module does not guess at missing structure: if a page doesn't match the
expected CourseLeaf markup, parse_plan_html() simply returns whatever it could
find (which may be an empty DataFrame) rather than fabricating data.
"""

import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

import pandas as pd
from bs4 import BeautifulSoup, Tag

# Row schema, in column order
COLUMNS = [
    "major",
    "year_label",
    "term",
    "row_order",
    "row_type",
    "choice_group_id",
    "course_subject",
    "course_number",
    "course_code_raw",
    "title",
    "footnote_refs",
    "credit_hours_raw",
    "credit_hours_min",
    "credit_hours_max",
    "credit_hours",
]

_CODE_RE = re.compile(r"^([A-Za-z]+)\s*(\d[\dA-Za-z]*)$")
_HOURS_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)")
_HOURS_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _clean_whitespace(text: str) -> str:
    """Collapse runs of whitespace (including \\xa0 non-breaking spaces) to single spaces."""
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _text_without_sup(tag: Tag) -> Tuple[str, List[str]]:
    """Return (visible text with <sup> footnote markers removed, list of footnote numbers)."""
    tag_copy = BeautifulSoup(str(tag), "html.parser")
    footnote_nums = [sup.get_text(strip=True) for sup in tag_copy.find_all("sup")]
    for sup in tag_copy.find_all("sup"):
        sup.decompose()
    return _clean_whitespace(tag_copy.get_text(" ", strip=True)), footnote_nums


def _split_course_code(code: str) -> Tuple[Optional[str], Optional[str]]:
    match = _CODE_RE.match(code.strip())
    if not match:
        return None, None
    return match.group(1).upper(), match.group(2).upper()


def _primary_code_from_href(href: Optional[str]) -> Optional[str]:
    """CourseLeaf course links look like /search/?P=CSCE%20222 -- decode the P param."""
    if not href:
        return None
    query = parse_qs(urlparse(href).query)
    values = query.get("P")
    return values[0].strip() if values else None


def _parse_hours(text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (min, max, avg) credit hours parsed from strings like '3', '15-16', or ''."""
    text = text.strip()
    if not text:
        return None, None, None

    range_match = _HOURS_RANGE_RE.search(text)
    if range_match:
        lo, hi = float(range_match.group(1)), float(range_match.group(2))
        return lo, hi, (lo + hi) / 2

    single_match = _HOURS_SINGLE_RE.search(text)
    if single_match:
        val = float(single_match.group(1))
        return val, val, val

    return None, None, None


def _parse_footnotes(soup: BeautifulSoup) -> Dict[str, str]:
    """Parse the <dl class="sc_footnotes"> block into {number: footnote text}."""
    footnotes: Dict[str, str] = {}
    dl = soup.find("dl", class_="sc_footnotes")
    if not dl:
        return footnotes

    terms = dl.find_all("dt")
    defs = dl.find_all("dd")
    for dt, dd in zip(terms, defs):
        num = dt.get_text(strip=True)
        text = dd.get_text(" ", strip=True)
        if num:
            footnotes[num] = text
    return footnotes


def _new_row(major: str, year_label: str, term: str, row_order: int, row_type: str) -> dict:
    row = {col: None for col in COLUMNS}
    row.update(
        major=major,
        year_label=year_label,
        term=term,
        row_order=row_order,
        row_type=row_type,
    )
    return row


def parse_plan_html(html: str, major: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    Parse one major's degree plan HTML page into (rows_df, footnotes).

    rows_df has one row per table row (course, requirement block, choice
    header/option, term subtotal, or plan total) -- see COLUMNS for schema.
    """
    soup = BeautifulSoup(html, "html.parser")
    footnotes = _parse_footnotes(soup)

    rows: List[dict] = []
    row_order = 0
    year_label = None
    term = None
    current_choice_group_id: Optional[int] = None
    next_choice_group_id = 0

    for table in soup.find_all("table", class_="sc_plangrid"):
        for tr in table.find_all("tr", recursive=False) or table.find_all("tr"):
            classes = tr.get("class", []) or []

            if "plangridyear" in classes:
                th = tr.find("th")
                year_label = th.get_text(strip=True) if th else year_label
                continue

            if "plangridterm" in classes:
                th = tr.find("th")
                term = th.get_text(strip=True) if th else term
                current_choice_group_id = None
                continue

            if "plangridsum" in classes:
                tds = tr.find_all("td")
                hours_raw = tds[-1].get_text(strip=True) if tds else ""
                lo, hi, avg = _parse_hours(hours_raw)
                row = _new_row(major, year_label, term, row_order, "term_subtotal")
                row.update(
                    title="Semester Credit Hours",
                    credit_hours_raw=hours_raw,
                    credit_hours_min=lo,
                    credit_hours_max=hi,
                    credit_hours=avg,
                )
                rows.append(row)
                row_order += 1
                continue

            if "plangridtotal" in classes:
                tds = tr.find_all("td")
                title = tds[1].get_text(strip=True) if len(tds) > 1 else "Total"
                hours_raw = tds[-1].get_text(strip=True) if tds else ""
                lo, hi, avg = _parse_hours(hours_raw)
                row = _new_row(major, year_label, term, row_order, "plan_total")
                row.update(
                    title=title,
                    credit_hours_raw=hours_raw,
                    credit_hours_min=lo,
                    credit_hours_max=hi,
                    credit_hours=avg,
                )
                rows.append(row)
                row_order += 1
                continue

            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue

            code_td = tds[0]
            hours_td = tds[-1]
            hours_raw = hours_td.get_text(strip=True)
            lo, hi, avg = _parse_hours(hours_raw)

            is_block_row = code_td.get("colspan") == "2" or len(tds) == 2
            if is_block_row:
                text_raw, footnote_nums = _text_without_sup(code_td)
                is_choice_header = text_raw.lower().startswith("select")
                row_type = "choice_header" if is_choice_header else "requirement_block"

                next_choice_group_id += 1
                current_choice_group_id = next_choice_group_id

                row = _new_row(major, year_label, term, row_order, row_type)
                row.update(
                    choice_group_id=current_choice_group_id,
                    title=text_raw,
                    footnote_refs=",".join(footnote_nums) or None,
                    credit_hours_raw=hours_raw,
                    credit_hours_min=lo,
                    credit_hours_max=hi,
                    credit_hours=avg,
                )
                rows.append(row)
                row_order += 1
                continue

            title_td = tds[1] if len(tds) > 1 else None
            blockindent = code_td.find("div", class_="blockindent")
            is_option = blockindent is not None

            link = (blockindent or code_td).find("a")
            course_code_raw = _clean_whitespace(link.get_text(strip=True)) if link else _clean_whitespace(code_td.get_text(strip=True))
            href = link.get("href") if link else None
            primary_code = _primary_code_from_href(href) or course_code_raw
            subject, number = _split_course_code(primary_code)

            title_text, footnote_nums = _text_without_sup(title_td) if title_td is not None else ("", [])

            row_type = "choice_option" if is_option else "course"
            row = _new_row(major, year_label, term, row_order, row_type)
            row.update(
                choice_group_id=current_choice_group_id if is_option else None,
                course_subject=subject,
                course_number=number,
                course_code_raw=course_code_raw,
                title=title_text,
                footnote_refs=",".join(footnote_nums) or None,
                credit_hours_raw=hours_raw,
                credit_hours_min=lo,
                credit_hours_max=hi,
                credit_hours=avg,
            )
            rows.append(row)
            row_order += 1

    df = pd.DataFrame(rows, columns=COLUMNS)
    return df, footnotes


def parse_multiple(pages: Dict[str, str]) -> Tuple[pd.DataFrame, Dict[str, Dict[str, str]]]:
    """
    Parse several majors at once.
    `pages` is {major: html}. Returns (combined_df, {major: footnotes}).
    """
    frames = []
    all_footnotes: Dict[str, Dict[str, str]] = {}

    for major, html in pages.items():
        df, footnotes = parse_plan_html(html, major)
        if df.empty:
            print(f"Warning: no plan rows parsed for '{major}' -- check page structure")
        frames.append(df)
        all_footnotes[major] = footnotes

    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    return combined, all_footnotes


def footnotes_to_df(footnotes_by_major: Dict[str, Dict[str, str]]) -> pd.DataFrame:
    """Flatten {major: {footnote_num: text}} into a tidy DataFrame."""
    rows = [
        {"major": major, "footnote_num": num, "footnote_text": text}
        for major, footnotes in footnotes_by_major.items()
        for num, text in footnotes.items()
    ]
    return pd.DataFrame(rows, columns=["major", "footnote_num", "footnote_text"])


if __name__ == "__main__":
    from config import SQLITE_DB_PATH
    from degree_plan_scraper import fetch_all
    from sql_handler import append_df_to_db

    pages = fetch_all()
    combined_df, footnotes_by_major = parse_multiple(pages)
    footnotes_df = footnotes_to_df(footnotes_by_major)

    print(combined_df.head(30).to_string())
    print(f"\nParsed {len(combined_df)} rows across {combined_df['major'].nunique()} major(s)")

    append_df_to_db(combined_df, str(SQLITE_DB_PATH), "degree_plan_courses", if_exists="replace")
    append_df_to_db(footnotes_df, str(SQLITE_DB_PATH), "degree_plan_footnotes", if_exists="replace")
