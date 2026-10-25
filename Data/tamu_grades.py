"""
Download TAMU Registrar grade-distribution PDFs (Fall 2021 -> Spring 2026),
parse every section row, and write combined CSVs.

The Registrar serves each report directly at:
  https://web-as.tamu.edu/gradereports/Report?year=2026&term=SPRING&college=EN

Outputs (in ./output):
  sections_all.csv      one row per section
  prof_course_all.csv   one row per course + instructor (weighted over all terms)
  download_log.csv      every download attempt (ok / missing / error)
  parse_problems.txt    lines that looked like sections but could not be parsed

Requires: pip install requests pandas   and   poppler (pdftotext)
"""
import re, shutil, subprocess, sys, time
from pathlib import Path
import pandas as pd
import requests

# ---------------- settings ----------------
FIRST_TERM = (2021, "FALL")
LAST_TERM = (2026, "SPRING")
INCLUDE_SUMMER = False
DELAY = 0.5                   # seconds between requests
INDEX_URL = "https://web-as.tamu.edu/gradereports"
REPORT_URL = "https://web-as.tamu.edu/gradereports/Report?year={year}&term={term}&college={code}"
# Fallback list = codes seen in the dropdowns on the Registrar's page.
FALLBACK_CODES = ["AC", "AD", "AE", "AG", "AP", "AR", "AT", "BA", "DN", "DT", "ED", "EH",
                  "EN", "EX", "GB", "GE", "GS", "GV", "LA", "MD", "MN", "MS", "NU", "PH",
                  "PV", "QT", "SC", "SL", "VM", "VT"]
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/pdf,*/*",
    "Referer": INDEX_URL,
}
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"; PDFS = ROOT / "pdfs"
# ------------------------------------------

ORDER = {"SPRING": 1, "SUMMER": 2, "FALL": 3}


def terms():
    """Yield (year, TERM) from FIRST_TERM to LAST_TERM."""
    y, t = FIRST_TERM
    while (y, ORDER[t]) <= (LAST_TERM[0], ORDER[LAST_TERM[1]]):
        if t != "SUMMER" or INCLUDE_SUMMER:
            yield y, t
        n = ORDER[t] + 1
        if n > 3:
            y, n = y + 1, 1
        t = {1: "SPRING", 2: "SUMMER", 3: "FALL"}[n]


def discover_codes():
    """Read college codes from the dropdowns on the index page; fall back to a built-in list."""
    try:
        html = requests.get(INDEX_URL, headers=HEADERS, timeout=30).text
        vals = {v.upper() for v in re.findall(r'<option[^>]*value="([A-Za-z]{2,3})"', html)}
        vals -= {"SPR", "SUM", "FAL"}
    except Exception as e:
        print("Could not read index page:", e); vals = set()
    if not vals:
        print("Using built-in college code list.")
        return sorted(FALLBACK_CODES)
    print("College codes found on the index page:", sorted(vals))
    return sorted(vals)


def download_all(codes):
    PDFS.mkdir(exist_ok=True)
    log, shown = [], [0]
    for year, term in terms():
        for code in codes:
            dest = PDFS / f"{year}{term}_{code}.pdf"
            if dest.exists():
                log.append((f"{year} {term}", code, "cached")); continue
            url = REPORT_URL.format(year=year, term=term, code=code)
            try:
                r = requests.get(url, headers=HEADERS, timeout=90)
                if r.status_code == 200 and r.content[:4] == b"%PDF":
                    dest.write_bytes(r.content); status = "ok"
                    print(f"  got {dest.name} ({len(r.content)//1024} KB)")
                else:
                    status = f"missing ({r.status_code})"
                    if shown[0] < 3:
                        shown[0] += 1
                        print(f"  FAILED {url} -> HTTP {r.status_code}, "
                              f"type={r.headers.get('Content-Type')}, first bytes={r.content[:60]!r}")
            except Exception as e:
                status = f"error ({e})"
            log.append((f"{year} {term}", code, status))
            time.sleep(DELAY)
    OUT.mkdir(exist_ok=True)
    df = pd.DataFrame(log, columns=["term", "code", "status"])
    df.to_csv(OUT / "download_log.csv", index=False)
    return df


# ---------------- parsing ----------------
TERM_RE = re.compile(r"GRADE DISTRIBUTION REPORT FOR (.+?)\s*$")
COLLEGE_RE = re.compile(r"^\s*COLLEGE:\s+(.*?)\s*$")
DEPT_RE = re.compile(r"^\s*DEPARTMENT:\s+(.*?)(?:\s{2,}TOTAL.*)?\s*$")
ID_RE = re.compile(r"^([A-Z]{2,4})-(\d{3,4})-(\w+)\s+(.*)$")
LEVELS = {"Undergraduate", "Graduate", "Professional"}


def parse_pdf(path, problems):
    text = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                          capture_output=True, text=True, check=True).stdout
    rows, term, level, college, dept, cols = [], None, None, None, None, None
    for line in text.splitlines():
        s = line.strip()
        if (m := TERM_RE.search(line)): term = m.group(1); continue
        if s in LEVELS: level = s; continue
        if (m := COLLEGE_RE.match(line)): college = m.group(1); continue
        if (m := DEPT_RE.match(line)): dept = m.group(1); continue
        if s.startswith("SECTION") and "INSTRUCTOR" in s:
            names = s.replace("A - F", "AF").replace("TOTAL", "TOTAL").split()
            cols = [n for n in names if n not in ("SECTION", "INSTRUCTOR")]
            continue
        if (m := ID_RE.match(s)):
            if not cols:
                problems.append(f"{path.name}: no header before: {s}"); continue
            toks = m.group(4).split()
            nums = []
            while toks and len(nums) < len(cols) and re.fullmatch(r"\d+(\.\d+)?", toks[0]):
                nums.append(toks.pop(0))
            if len(nums) != len(cols):
                problems.append(f"{path.name}: {s}"); continue
            rec = dict(zip(cols, nums))
            rows.append({"term": term, "level": level, "college": college,
                         "department": dept, "subject": m.group(1), "number": m.group(2),
                         "section": m.group(3), "instructor": " ".join(toks), "file": path.name, **rec})
    return rows


def parse_all():
    problems, rows = [], []
    for pdf in sorted(PDFS.glob("*.pdf")):
        got = parse_pdf(pdf, problems)
        print(f"  parsed {pdf.name}: {len(got)} sections")
        rows += got
    df = pd.DataFrame(rows)
    if df.empty:
        sys.exit("No sections parsed (no PDFs downloaded?). Look at the FAILED lines above "
                 "and output/download_log.csv.")
    for c in df.columns:
        if c in ("term level college department subject number section instructor file".split()):
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns={"AF": "af_total", "GPA": "gpa", "TOTAL": "total"})
    # The Registrar lists some units twice (e.g. a "College" and a "School" report), so the
    # same section can appear in more than one PDF. Keep one copy of each real section.
    from build_dataset import campus_for
    df["campus"] = [campus_for(r) for r in df.to_dict("records")]
    key = ["campus", "level", "term", "subject", "number", "section", "instructor", "A", "B", "C", "D", "F", "total"]
    before = len(df)
    df = df.drop_duplicates(subset=key).reset_index(drop=True)
    print(f"removed {before - len(df)} duplicate section rows")
    OUT.mkdir(exist_ok=True)
    df.to_csv(OUT / "sections_all.csv", index=False)
    (OUT / "parse_problems.txt").write_text("\n".join(problems))
    print(f"{len(df)} sections total; {len(problems)} problem lines (see output/parse_problems.txt)")
    return df


def aggregate(df):
    d = df.dropna(subset=["af_total"]).copy()
    d["pts"] = d["A"] * 4 + d["B"] * 3 + d["C"] * 2 + d["D"]
    g = d.groupby(["campus", "level", "subject", "number", "instructor"]).agg(
        sections=("section", "count"), terms=("term", "nunique"),
        students=("af_total", "sum"), A=("A", "sum"), B=("B", "sum"), C=("C", "sum"),
        D=("D", "sum"), F=("F", "sum"), pts=("pts", "sum")).reset_index()
    g["pct_A"] = (g.A / g.students).round(3)
    g["gpa"] = (g.pts / g.students).round(3)
    g = g.drop(columns="pts").sort_values(["subject", "number", "gpa"], ascending=[True, True, False])
    g.to_csv(OUT / "prof_course_all.csv", index=False)
    print(f"{len(g)} course/instructor rows -> output/prof_course_all.csv")


if __name__ == "__main__":
    if not shutil.which("pdftotext"):
        sys.exit("pdftotext not found. Run: brew install poppler")
    if "--parse-only" not in sys.argv:
        codes = discover_codes()
        print(f"Trying {len(codes)} college codes x {len(list(terms()))} terms")
        log = download_all(codes)
        print("\nDownload summary:\n", log.status.str.split(" ").str[0].value_counts().to_string())
        hit = set(log[log.status.isin(["ok", "cached"])].code)
        print("Codes that returned files:", sorted(hit))
        print("Codes with no files at all:", sorted(set(codes) - hit))
    df = parse_all()
    aggregate(df)
