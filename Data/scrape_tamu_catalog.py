"""
Scrape every department's course list from the TAMU undergraduate catalog
into one clean CSV.

Run locally:  pip install requests beautifulsoup4 pandas
              python scrape_tamu_catalog.py

NOTE: the selectors below (div.courseblock, p.courseblocktitle, p.courseblockdesc)
are the usual CourseLeaf catalog markup but I could not verify them against the
live page. Run on ONE department first (set ONLY_DEPTS = ["csce"]) and check
courses.csv before running everything.
"""
import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE = "https://catalog.tamu.edu"
INDEX = f"{BASE}/undergraduate/course-descriptions/"
HEADERS = {"User-Agent": "schedule-builder-student-project (personal use)"}
DELAY = 1.0          # seconds between requests; be polite
ONLY_DEPTS = []      # e.g. ["csce"] for a test run; empty = all


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def department_codes():
    soup = BeautifulSoup(get(INDEX), "html.parser")
    codes = set()
    for a in soup.select("a[href]"):
        m = re.fullmatch(r"/undergraduate/course-descriptions/([a-z]{3,4})/", a["href"])
        if m:
            codes.add(m.group(1))
    return sorted(codes)


def parse_department(code):
    soup = BeautifulSoup(get(f"{INDEX}{code}/"), "html.parser")
    rows = []
    for block in soup.select("div.courseblock"):
        title = clean(block.select_one(".courseblocktitle").get_text(" "))
        m = re.match(r"([A-Z]{2,4})\s+(\d{3,4})\s*(.*)", title)
        if not m:
            continue
        subject, number, name = m.groups()
        text = clean(block.get_text(" "))

        credits = re.search(r"Credits?\s+([\d.\-]+(?:\s+to\s+[\d.]+)?)", text)
        prereq = re.search(
            r"Prerequisites?:\s*(.*?)(?=\s*(?:Corequisites?:|Cross Listing|Cross-listed|$))", text)
        coreq = re.search(r"Corequisites?:\s*(.*?)(?=\s*(?:Prerequisites?:|Cross Listing|$))", text)
        desc_el = block.select_one(".courseblockdesc")

        rows.append({
            "subject": subject,
            "number": number,
            "course": f"{subject} {number}",
            "title": name,
            "credits": credits.group(1) if credits else None,
            "is_honors_dept": subject == "HONR",
            "description": clean(desc_el.get_text(" ")) if desc_el else None,
            "prereq_text": prereq.group(1) if prereq else None,
            "coreq_text": coreq.group(1) if coreq else None,
            "dept_code": code.upper(),
        })
    return rows


def main():
    depts = ONLY_DEPTS or department_codes()
    print(f"{len(depts)} departments")
    all_rows = []
    for code in depts:
        try:
            rows = parse_department(code)
            print(f"{code}: {len(rows)} courses")
            all_rows += rows
        except Exception as e:
            print(f"{code}: FAILED ({e})")
        time.sleep(DELAY)
    df = pd.DataFrame(all_rows).drop_duplicates(subset="course")
    df.to_csv("courses.csv", index=False)
    print(f"saved {len(df)} courses to courses.csv")


if __name__ == "__main__":
    main()
