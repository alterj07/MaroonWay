"""Conservative candidate report; never rewrite names, merge grades or assert identity."""
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'Data/output/howdy_matching'
ROOT.mkdir(parents=True, exist_ok=True)
ROSTER = REPO / 'Data/MaroonWay_Fall2026_Professor_Roster.csv'
GRADES = REPO / 'Data/output/schedule_dataset.csv'
csv.field_size_limit(100_000_000)

def tokens(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', s).upper() if not unicodedata.combining(c))
    return re.findall(r'[A-Z0-9]+', s)

def code(s):
    return re.sub(r'[^A-Z0-9]', '', s.upper())

def aliases(name):
    ts = tokens(name)
    if ts and ts[-1] in {'JR', 'SR', 'II', 'III', 'IV'}:
        ts = ts[:-1]
    if len(ts) < 2:
        return set()
    # Include compound surnames, without assuming which interior token is a surname.
    return {(''.join(ts[i:]), ts[0][0]) for i in range(1, len(ts))}

def grade_alias(name):
    ts = tokens(name)
    # Source convention: surname(s), followed by one or more initials.
    pos = len(ts)
    while pos > 0 and len(ts[pos - 1]) == 1:
        pos -= 1
    if 0 < pos < len(ts):
        return (''.join(ts[:pos]), ts[pos][0])
    return None

with ROSTER.open(newline='', encoding='utf-8-sig') as f:
    roster = list(csv.DictReader(f))
with GRADES.open(newline='', encoding='utf-8-sig') as f:
    grades = list(csv.DictReader(f))

by_alias = defaultdict(set)
by_full = defaultdict(set)
groups = defaultdict(list)
for r in grades:
    key = (r['instructor_name'], r['campus'])
    groups[key].append(r)
    alias = grade_alias(r['instructor_name'])
    if alias:
        by_alias[alias].add(key)
    by_full[tuple(tokens(r['instructor_name']))].add(key)

candidates = []
claimants = defaultdict(set)
for idx, person in enumerate(roster):
    keys = set(by_full[tuple(tokens(person['instructor_name']))])
    for alias in aliases(person['instructor_name']):
        keys.update(by_alias[alias])
    courses = {code(c) for c in person['courses'].split('|') if c.strip()}
    sites = {s.strip() for s in person['sites'].split('|') if s.strip()}
    found = []
    for key in sorted(keys):
        rows = groups[key]
        overlap = sorted(courses & {code(r['subject'] + r['course_number']) for r in rows})
        campus = key[1]
        campus_evidence = 'compatible' if campus in sites else 'unknown' if not sites or campus == 'Unknown' else 'conflict'
        supported = bool(overlap) and campus_evidence == 'compatible'
        found.append((key, overlap, campus_evidence, supported))
        if supported:
            claimants[key].add(idx)
    candidates.append(found)

out = []
statuses = Counter()
for idx, (person, found) in enumerate(zip(roster, candidates)):
    supported = [x for x in found if x[3]]
    if len(supported) == 1 and len(claimants[supported[0][0]]) == 1:
        status = 'unique_supported_candidate_NOT_VERIFIED'
    elif supported:
        status = 'ambiguous_review_required'
    elif found:
        status = 'name_only_or_conflicting_review_required'
    else:
        status = 'no_name_candidate'
    statuses[status] += 1
    for entry in found or [None]:
        r = dict(person)
        r['match_status'] = status
        r['identity_verified'] = 'NO'
        r['grade_source'] = 'MaroonWay Data/output/schedule_dataset.csv; official grade PDF pipeline'
        r['grades_instructor_name'] = entry[0][0] if entry else ''
        r['grades_campus'] = entry[0][1] if entry else ''
        r['overlapping_courses'] = ' | '.join(entry[1]) if entry else ''
        r['campus_evidence'] = entry[2] if entry else ''
        r['candidate_supported'] = 'YES' if entry and entry[3] else 'NO'
        r['howdy_people_claiming_grade_identity'] = len(claimants[entry[0]]) if entry else 0
        r['candidate_count'] = len(found)
        r['supported_candidate_count'] = len(supported)
        out.append(r)

output = ROOT / 'Howdy_Fall2026_MaroonWay_Grade_Name_Candidates.csv'
with output.open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=list(out[0]))
    writer.writeheader()
    writer.writerows(out)
summary = {'howdy_rows': len(roster), 'source_grade_rows': len(grades), 'output_candidate_rows': len(out), 'howdy_status_counts': dict(statuses), 'verified_identities': 0}
(ROOT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
assert sum(statuses.values()) == len(roster)
assert all(r['identity_verified'] == 'NO' for r in out)
assert all(r['supported_candidate_count'] == 1 and r['howdy_people_claiming_grade_identity'] == 1 for r in out if r['match_status'].startswith('unique_') and r['candidate_supported'] == 'YES')
print(json.dumps(summary, indent=2))
print('Examples:')
for r in [r for r in out if r['match_status'].startswith('unique_') and r['candidate_supported'] == 'YES'][:8]:
    print(r['instructor_name'], '->', r['grades_instructor_name'], r['overlapping_courses'])
