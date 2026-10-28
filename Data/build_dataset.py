"""Campus-aware grades + RMP pipeline. See DATA_README.md for commands and caveats."""
import argparse
import base64
import csv
import json
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
CACHE = OUT / "rmp_cache_v2"
CAMPUS_IDS = {"College Station": 1003, "Galveston": 1006}
# These reports span other locations or professional programs; do not assume CStat.
UNCERTAIN_CODES = {"DN", "DT", "MD", "MN", "NU", "SL", "PH"}


def campus_for(row):
    code = Path(row['file']).stem.rsplit('_', 1)[-1]
    if code == 'QT':
        return 'Qatar'
    if code == 'GV':
        return 'Galveston'
    if code in UNCERTAIN_CODES:
        return 'Unknown'
    return 'College Station'


def read_csv(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with path.with_suffix('.tmp').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    path.with_suffix('.tmp').replace(path)


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix('.tmp').write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    path.with_suffix('.tmp').replace(path)


def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().upper()
    return ' '.join(re.sub(r"[^A-Z0-9 ]", ' ', s).split())


#: Name forms we have to read, and which half of each is the surname:
#:
#:   "CANTU J"            grade reports -- surname first, then an initial
#:   "Cantu, Justin Colt" Schedule Builder -- surname, comma, given names
#:   "Justin Colt Cantu"  the same, already rearranged
#:
#: Only the first of these existed when this was written, which is why the old
#: version required the final token to be a single letter and returned None for
#: everything else.
def name_key(name):
    """(surname, given name or initial), or None if the form is unreadable."""
    raw = str(name or '')
    if ',' in raw:
        last, _, rest = raw.partition(',')
        given = [x for x in norm(rest).split() if x not in NAME_SUFFIXES]
        surname = ' '.join(x for x in norm(last).split() if x not in NAME_SUFFIXES)
        return (surname, given[0]) if surname and given else None

    t = [x for x in norm(raw).split() if x not in NAME_SUFFIXES]
    if len(t) < 2:
        return None
    # "CANTU J": everything but the trailing initial is the surname.
    if len(t[-1]) == 1:
        return ' '.join(t[:-1]), t[-1]
    # "Justin Colt Cantu": the trailing token is the surname. Middle names are
    # dropped rather than guessed at -- RMP carries one first name.
    return t[-1], t[0]


NAME_SUFFIXES = {'JR', 'SR', 'II', 'III', 'IV'}


def names_agree(ours, theirs):
    """Whether two given names can be the same person.

    One being a prefix of the other covers the only two cases we actually see:
    an initial against a full name ("J" vs "JUSTIN"), and two spellings of the
    same name. It is deliberately not fuzzy -- "JUSTIN" and "JUSTINE" are
    different people and a looser rule would merge them.
    """
    if not ours or not theirs:
        return False
    return theirs.startswith(ours) if len(ours) <= len(theirs) else ours.startswith(theirs)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def aggregate_sections(sections):
    groups = {}
    seen = set()
    conflicts = defaultdict(set)
    for r in sections:
        r = dict(r)
        for raw, clean in [('AF', 'af_total'), ('TOTAL', 'total'), ('GPA', 'gpa')]:
            if raw in r:
                r[clean] = r[raw]
        r['campus'] = campus_for(r)
        identity = tuple(r.get(k, '') for k in ['campus', 'level', 'term', 'subject', 'number', 'section', 'instructor'])
        counts = tuple(r.get(k, '') for k in ['A', 'B', 'C', 'D', 'F', 'af_total', 'total'])
        conflicts[identity].add(counts)
        if identity + counts in seen:
            continue
        seen.add(identity + counts)
        key = (r['campus'], r['level'], r['subject'], r['number'], r['instructor'])
        g = groups.setdefault(key, {'campus': key[0], 'level': key[1], 'subject': key[2],
            'course_number': key[3], 'instructor_name': key[4], 'section_count': 0,
            'graded_students': 0, **{x.lower() + '_count': 0 for x in 'ABCDF'},
            '_terms': set(), '_departments': set(), '_files': set(), 'grade_issue_count': 0})
        g['section_count'] += 1
        g['_terms'].add(r['term'])
        g['_departments'].add(r['department'])
        g['_files'].add(r['file'])
        values = [number(r.get(x)) for x in 'ABCDF']
        n = number(r.get('af_total'))
        if n is None or any(v is None or v < 0 for v in values) or n < 0 or abs(sum(values) - n) > .01:
            g['grade_issue_count'] += 1
            continue
        g['graded_students'] += int(n)
        for x, v in zip('ABCDF', values):
            g[x.lower() + '_count'] += int(v)
    result = []
    for g in groups.values():
        g['term_count'] = len(g['_terms'])
        g['grade_terms_json'] = json.dumps(sorted(g.pop('_terms')))
        g['departments'] = ' | '.join(sorted(g.pop('_departments')))
        g['grade_source_files_json'] = json.dumps(sorted(g.pop('_files')))
        n = g['graded_students']
        g['avg_gpa'] = round(sum(g[x + '_count'] * w for x, w in zip('abcd', [4, 3, 2, 1])) / n, 4) if n else None
        g['pct_a'] = round(g['a_count'] / n, 4) if n else None
        g['campus_basis'] = 'report_code' if g['campus'] in ('Galveston', 'Qatar') else 'unresolved' if g['campus'] == 'Unknown' else 'report_unit_inferred'
        result.append(g)
    bad = [dict(zip(['campus', 'level', 'term', 'subject', 'number', 'section', 'instructor'], k), variants_json=json.dumps(sorted(v)))
           for k, v in conflicts.items() if len(v) > 1]
    if bad:
        write_csv(OUT / 'grade_conflicts.csv', bad)
        raise ValueError('Conflicting section records: see output/grade_conflicts.csv; refusing to double count.')
    return sorted(result, key=lambda r: (r['campus'], r['subject'], r['course_number'], r['instructor_name'], r['level']))


class Client:
    def __init__(self, delay=1.0):
        import requests
        from rmp_api.client import API_LINK, HEADERS
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.url, self.delay, self.last = API_LINK, delay, 0

    def query(self, query, variables):
        for attempt in range(3):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            response = self.session.post(self.url, json={'query': query, 'variables': variables}, timeout=45)
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            response.raise_for_status()
            data = response.json()
            if data.get('errors'):
                raise RuntimeError(str(data['errors']))
            return data['data']
        raise RuntimeError('RMP unavailable after three attempts; rerun later to resume.')


SEARCH = '''query($query: TeacherSearchQuery!, $cursor: String) {
  newSearch { teachers(query: $query, first: 100, after: $cursor) {
    edges { node { id legacyId firstName lastName department avgRating avgDifficulty
      numRatings wouldTakeAgainPercent school { id legacyId name } } }
    pageInfo { hasNextPage endCursor }
  } }
}'''


def node_id(kind, legacy):
    return base64.b64encode(f'{kind}-{legacy}'.encode()).decode()


def collect_rosters(client, refresh=False):
    from rmp_api.client import SCHOOL_QUERY
    schools = {}
    for campus, sid in CAMPUS_IDS.items():
        schools[campus] = {'legacyId': sid, 'id': node_id('School', sid)}
    # Qatar's ID is deliberately discovered rather than guessed.
    qpath = CACHE / 'qatar_school.json'
    if qpath.exists() and not refresh:
        schools['Qatar'] = json.loads(qpath.read_text())
    else:
        data = client.query(SCHOOL_QUERY, {'query': {'text': 'Texas A&M Qatar'}})
        candidates = [e['node'] for e in data['newSearch']['schools']['edges']
                      if 'QATAR' in norm(e['node']['name']) and 'TEXAS' in norm(e['node']['name'])]
        if len(candidates) == 1:
            schools['Qatar'] = candidates[0]
            save_json(qpath, candidates[0])
        else:
            print('Qatar RMP school not uniquely identified; Qatar grades will remain unmatched.', flush=True)
    all_profs = []
    for campus, school in schools.items():
        path = CACHE / f'roster_{school["legacyId"]}.json'
        state = json.loads(path.read_text()) if path.exists() and not refresh else {'professors': [], 'cursor': None, 'complete': False}
        while not state['complete']:
            data = client.query(SEARCH, {'query': {'text': '', 'schoolID': school['id'], 'fallback': False}, 'cursor': state['cursor']})
            connection = data['newSearch']['teachers']
            profs = [e['node'] for e in connection['edges']]
            if any(str(p['school']['legacyId']) != str(school['legacyId']) for p in profs):
                raise ValueError(f'RMP returned professors from another campus for {campus}; nothing from that page saved.')
            for p in profs:
                p['campus'] = campus
            state['professors'].extend(profs)
            state['professors'] = list({str(p['legacyId']): p for p in state['professors']}.values())
            info = connection['pageInfo']
            if info['hasNextPage'] and (not info['endCursor'] or info['endCursor'] == state['cursor'] or not profs):
                raise ValueError('Roster pagination stopped advancing.')
            state.update(cursor=info['endCursor'], complete=not info['hasNextPage'], fetched_at=datetime.now(timezone.utc).isoformat())
            save_json(path, state)
            print(f'{campus}: {len(state["professors"])} professors cached', flush=True)
        for p in state['professors']:
            p['fetched_at'] = state['fetched_at']
        all_profs.extend(state['professors'])
    return all_profs


def load_rosters():
    profs = []
    for path in sorted(CACHE.glob('roster_*.json')):
        state = json.loads(path.read_text())
        if not state.get('complete'):
            continue
        for p in state['professors']:
            p['fetched_at'] = state.get('fetched_at')
            profs.append(p)
    return profs


def dept_tokens(s):
    aliases = {'SCIENCES': 'SCIENCE', 'SCI': 'SCIENCE', 'ENGR': 'ENGINEERING', 'MATH': 'MATHEMATICS', 'STAT': 'STATISTICS'}
    return {aliases.get(t, t) for t in norm(s).split() if t not in {'AND', 'OF', 'THE', 'DEPARTMENT', 'DEPT'}}


def match(g, profs):
    """Link one instructor to an RMP profile, or say why not.

    Department agreement used to be a precondition: a candidate matched
    uniquely by name was thrown away unless RMP's department string shared
    half its tokens with the grade report's. That rejected 5,485 rows whose
    *only* candidate was the right one -- "AEROSPACE ENGINEERING" against RMP's
    "Mechanical Engineering" scores 0.33 and fails -- and is the single largest
    reason 64% of instructors carry no rating.

    Department is now what it should always have been: a tiebreak. A name that
    matches exactly one professor on the right campus is that professor. Only
    when several answer to the same name does the department decide between
    them, and when it cannot, the row still goes to review rather than being
    guessed at.
    """
    key = name_key(g['instructor_name'])
    if not key:
        return None, 'unmatched_name_format', []
    surname, given = key
    candidates = [p for p in profs if p['campus'] == g['campus']
                  and norm(p['lastName']) == surname
                  and names_agree(given, norm(p['firstName']))]
    if not candidates:
        return None, 'no_match', []
    if len(candidates) == 1:
        return candidates[0], 'matched_name_unique', candidates

    def dept_ok(p):
        a = dept_tokens(p['department'])
        return any(a and a & dept_tokens(d) and len(a & dept_tokens(d)) / len(a | dept_tokens(d)) >= .5
                   for d in g['departments'].split(' | '))
    compatible = [p for p in candidates if dept_ok(p)]
    if len(compatible) == 1:
        return compatible[0], 'matched_name_department', candidates
    return None, 'needs_review', candidates


def review_day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def year_before(day):
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def collect_reviews(client, prof, refresh=False):
    from rmp_api.client import RATINGS_LIST_QUERY
    path = CACHE / f'reviews_{prof["legacyId"]}.json'
    state = json.loads(path.read_text()) if path.exists() and not refresh else {'reviews': [], 'cursor': None, 'complete': False}
    while not state['complete']:
        data = client.query(RATINGS_LIST_QUERY, {'id': prof['id'], 'count': 100, 'courseFilter': None, 'cursor': state['cursor']})
        teacher = data['node']
        if str(teacher['school']['legacyId']) != str(prof['school']['legacyId']):
            raise ValueError('Review school does not match professor school.')
        conn = teacher['ratings']
        reviews = [e['node'] for e in conn['edges']]
        state['reviews'].extend(reviews)
        state['reviews'] = list({r['id']: r for r in state['reviews']}.values())
        info = conn['pageInfo']
        if info['hasNextPage'] and (not info['endCursor'] or state['cursor'] == info['endCursor'] or not reviews):
            raise ValueError('Review pagination stopped advancing.')
        state.update(cursor=info['endCursor'], complete=not info['hasNextPage'], fetched_at=datetime.now(timezone.utc).isoformat())
        save_json(path, state)
    return state


def attach_rmp(grades, profs, as_of, client=None, limit=None, refresh=False):
    cutoff = year_before(as_of)
    targets = set()
    review_rows = []
    consecutive_errors = 0
    index = defaultdict(list)
    campus_totals = defaultdict(lambda: [0, 0])
    for p in profs:
        first = norm(p['firstName'])
        if first:
            index[(p['campus'], norm(p['lastName']), first[0])].append(p)
        if (p['numRatings'] or 0) > 0:
            campus_totals[p['campus']][0] += p['avgRating'] * p['numRatings']
            campus_totals[p['campus']][1] += p['numRatings']
    for g in grades:
        key = name_key(g['instructor_name'])
        p, status, candidates = match(g, index.get((g['campus'], *key), []) if key else [])
        g.update(match_status=status, match_confidence='heuristic' if p else '',
                 rmp_candidate_ids_json=json.dumps([x['legacyId'] for x in candidates]),
                 rmp_professor_id=None, rmp_name=None, rmp_rating=None, rmp_difficulty=None,
                 rmp_review_count=None, rmp_would_take_again_pct=None, rmp_rating_adjusted=None,
                 rmp_fetched_at=None, rmp_reviews_fetched_at=None, rmp_url=None,
                 reviews_status='not_matched', reviews_collected_count=None,
                 reviews_past_year_count=None, reviews_invalid_date_count=None,
                 reviews_window_start=cutoff.isoformat(), reviews_window_end=as_of.isoformat(),
                 rmp_reviews_past_year_json='[]', rmp_course_reviews_past_year_json='[]')
        if not p:
            review_rows.append({k: g[k] for k in ['campus', 'subject', 'course_number', 'instructor_name', 'match_status', 'rmp_candidate_ids_json']})
            continue
        n = p['numRatings'] or 0
        g.update(rmp_professor_id=p['legacyId'], rmp_name=f'{p["firstName"]} {p["lastName"]}',
                 rmp_rating=p['avgRating'] if n else None, rmp_difficulty=p['avgDifficulty'] if n else None,
                 rmp_review_count=n, rmp_would_take_again_pct=p['wouldTakeAgainPercent'] if p['wouldTakeAgainPercent'] is not None and p['wouldTakeAgainPercent'] >= 0 else None,
                 rmp_fetched_at=p.get('fetched_at'), rmp_url=f'https://www.ratemyprofessors.com/professor/{p["legacyId"]}')
        total, count = campus_totals[p['campus']]
        prior = total / count if count else 3.5
        g['rmp_rating_adjusted'] = round((n * p['avgRating'] + 10 * prior) / (n + 10), 4) if n else None
        path = CACHE / f'reviews_{p["legacyId"]}.json'
        if client and p['legacyId'] not in targets and (limit is None or len(targets) < limit):
            targets.add(p['legacyId'])
            print(f'Fetching reviews: {g["rmp_name"]} ({len(targets)})', flush=True)
            try:
                collect_reviews(client, p, refresh)
                consecutive_errors = 0
            except Exception as exc:
                print(f'Reviews incomplete for {p["legacyId"]}: {exc}', flush=True)
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    print('Three consecutive download errors; stopping requests and exporting available cached data.', flush=True)
                    client = None
        if not path.exists():
            g['reviews_status'] = 'not_fetched'
            continue
        state = json.loads(path.read_text())
        g['reviews_status'] = 'complete' if state['complete'] else 'partial'
        g['rmp_reviews_fetched_at'] = state.get('fetched_at')
        g['reviews_collected_count'] = len(state['reviews'])
        g['reviews_invalid_date_count'] = sum(review_day(r.get('date')) is None for r in state['reviews'])
        recent = [dict(r, course_match_status='unresolved') for r in state['reviews'] if review_day(r.get('date')) is not None and cutoff <= review_day(r['date']) <= as_of]
        course = re.sub(r'[^A-Z0-9]', '', g['subject'] + g['course_number'])
        for r in recent:
            label = re.sub(r'[^A-Z0-9]', '', str(r.get('class', '')).upper())
            # Number-only labels stay unresolved; never invent their subject.
            r['course_match_status'] = 'exact' if label == course else 'number_only' if label.isdigit() else 'other_or_unresolved'
        g['reviews_past_year_count'] = len(recent)
        g['rmp_reviews_past_year_json'] = json.dumps(recent, ensure_ascii=False)
        g['rmp_course_reviews_past_year_json'] = json.dumps([r for r in recent if r['course_match_status'] == 'exact'], ensure_ascii=False)
    write_csv(OUT / 'needs_review_v2.csv', review_rows, ['campus', 'subject', 'course_number', 'instructor_name', 'match_status', 'rmp_candidate_ids_json'])
    return grades


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true', help='Download RMP rosters/reviews; otherwise build from cache only.')
    parser.add_argument('--reparse', action='store_true', help='Reparse cached PDFs, retaining campus in section deduplication.')
    parser.add_argument('--refresh', action='store_true', help='Refresh downloaded RMP data (otherwise resume/use cache).')
    parser.add_argument('--as-of', type=date.fromisoformat, default=datetime.now(ZoneInfo('America/Chicago')).date())
    parser.add_argument('--subject', help='Optional comma-separated subjects for a faster demo run.')
    parser.add_argument('--max-professors', type=int, help='Limit review downloads; unmatched/unfetched rows remain in CSV.')
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.reparse:
        import tamu_grades
        problems, sections = [], []
        for path in sorted((ROOT / 'pdfs').glob('*.pdf')):
            sections.extend(tamu_grades.parse_pdf(path, problems))
        if not sections:
            raise RuntimeError('No sections found in cached PDFs.')
        (OUT / 'parse_problems_v2.txt').write_text('\n'.join(problems))
        write_csv(OUT / 'sections_campus_source.csv', sections)
        print(f'Reparsed {len(sections)} rows; {len(problems)} parse problems.', flush=True)
    else:
        source = OUT / 'sections_campus_source.csv'
        if not source.exists():
            raise RuntimeError('First run requires --reparse to recover campus information before deduplication.')
        sections = read_csv(source)
    grades = aggregate_sections(sections)
    if args.subject:
        subjects = set(args.subject.upper().split(','))
        grades = [g for g in grades if g['subject'] in subjects]
    if not grades:
        raise RuntimeError('No grade rows selected.')
    catalog = {(r['subject'], r['number']): r for r in read_csv(ROOT / 'courses.csv')}
    for g in grades:
        c = catalog.get((g['subject'], g['course_number']), {})
        for dest, src in [('course_title', 'title'), ('credits', 'credits'), ('description', 'description'), ('prereq_text', 'prereq_text'), ('coreq_text', 'coreq_text')]:
            g[dest] = c.get(src, '')
        g['catalog_match_status'] = 'subject_number_only' if c else 'not_in_undergraduate_catalog'
    client = Client() if args.fetch else None
    if client:
        try:
            profs = collect_rosters(client, args.refresh)
        except Exception as exc:
            print(f'Roster collection incomplete: {exc}. Building from completed cached rosters.', flush=True)
            profs = load_rosters()
    else:
        profs = load_rosters()
    grades = attach_rmp(grades, profs, args.as_of, client, args.max_professors, args.refresh)
    write_csv(OUT / 'schedule_dataset.csv', grades)
    report = {'rows': len(grades), 'matched_rows': sum(g['rmp_professor_id'] is not None for g in grades),
              'campuses': {c: sum(g['campus'] == c for g in grades) for c in sorted({g['campus'] for g in grades})},
              'complete_review_rows': sum(g['reviews_status'] == 'complete' for g in grades),
              'grade_issue_sections': sum(g['grade_issue_count'] for g in grades),
              'as_of': args.as_of.isoformat(), 'subject_filter': args.subject,
              'notes': ['College Station is inferred from report unit, not verified section location.',
                        'Unknown-campus rows are retained but never automatically matched to RMP.',
                        'Roster and review timestamps describe cache freshness; complete means pagination completed.',
                        'Honors, section availability and campus-specific prerequisites are not verified.']}
    save_json(OUT / 'dataset_report.json', report)
    print(json.dumps(report, indent=2))
    print(f'Saved {OUT / "schedule_dataset.csv"}', flush=True)


if __name__ == '__main__':
    main()
