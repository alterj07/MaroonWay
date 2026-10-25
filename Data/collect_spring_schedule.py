"""Download public Spring 2027 sections and optionally enrich public office hours.

No login, student records, or registration actions. Run --help for options.
"""
import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from bs4 import BeautifulSoup
from prerequisites import ensure_catalogs, attach_prerequisites, fill_missing_prerequisites

ROOT = Path(__file__).resolve().parent
HOWDY = 'https://howdyportal.tamu.edu'
SIMPLE = 'https://tamu.simplesyllabus.com'
PUBLIC_SEARCH = HOWDY + '/uPortal/p/public-class-search-ui.ctf1/max/render.uP'
PREFIX = 'SWV_CLASS_SEARCH_'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def write_csv(path, rows):
    if not rows:
        raise ValueError(f'Refusing to write an empty export: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def norm(value):
    s = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().upper()
    return ' '.join(re.sub(r'[^A-Z0-9 ]', ' ', s).split())


def json_list(value):
    result = json.loads(value) if isinstance(value, str) and value else value or []
    if not isinstance(result, list):
        raise ValueError('Expected list of meetings or instructors')
    return result


def clock_time(value):
    if not value or str(value).upper() in ('TBA', 'ARR'):
        return None
    for fmt in ('%I:%M %p', '%I:%M%p', '%H:%M', '%H%M'):
        try:
            return datetime.strptime(str(value).strip(), fmt).strftime('%H:%M')
        except ValueError:
            pass
    raise ValueError(f'Unrecognized time: {value}')


def iso_date(value):
    return datetime.strptime(value, '%m/%d/%Y').date().isoformat() if value else None


def syllabus_url(term, crn, kind='html'):
    return SIMPLE + '/ui/syllabus-redirect?' + urlencode({'type': kind, 'attribute[4]': f'{crn}.{term}'})


def normalize_section(raw, term_label, fetched_at):
    v = lambda name: raw.get(PREFIX + name)
    term, crn = str(v('TERM')), str(v('CRN'))
    term_campus = term_label.split(' - ', 1)[1]
    site = v('SITE')
    meetings = []
    for m in json_list(v('JSON_CLOB')):
        meetings.append({'type': m.get('SSRMEET_MTYP_CODE'),
            'days': [label for code, label in [('MON','Mon'),('TUE','Tue'),('WED','Wed'),('THU','Thu'),('FRI','Fri'),('SAT','Sat'),('SUN','Sun')] if m.get('SSRMEET_' + code + '_DAY')],
            'start_time': clock_time(m.get('SSRMEET_BEGIN_TIME')),
            'end_time': clock_time(m.get('SSRMEET_END_TIME')),
            'start_date': iso_date(m.get('SSRMEET_START_DATE')),
            'end_date': iso_date(m.get('SSRMEET_END_DATE')),
            'building': m.get('SSRMEET_BLDG_CODE'), 'room': m.get('SSRMEET_ROOM_CODE')})
    instructors = []
    for p in json_list(v('INSTRCTR_JSON')):
        name = re.sub(r'\s*\(P\)\s*$', '', p['NAME']).strip()
        instructors.append({'name': name, 'primary': bool(re.search(r'\(P\)\s*$', p['NAME']))})
    attrs = [x.strip() for x in (v('ATTRIBUTES') or '').split('|') if x.strip()]
    timed = [m for m in meetings if m['days'] and m['start_time'] and m['end_time']]
    online = True if v('INST_TYPE') in ('Web Based', 'Synchronous Video/Web Conf') else False if v('INST_TYPE') == 'Traditional Face-to-Face (F2F)' else None
    return {'term_code': term, 'term_name': term_label, 'crn': crn,
        'campus': site or 'Unknown', 'campus_basis': 'section_site' if site else 'not_provided',
        'term_campus': term_campus, 'in_requested_campuses': site in ('College Station', 'Galveston', 'Qatar'),
        'subject': v('SUBJECT'), 'course_number': str(v('COURSE')), 'section': v('SECTION'),
        'course_title': v('TITLE'), 'credit_hours': raw.get('HRS_COLUMN_FIELD'),
        'credit_hours_min': v('HOURS_LOW'), 'credit_hours_max': v('HOURS_HIGH'),
        'session': v('SESSION'), 'schedule_type': v('SCHD'), 'instruction_type': v('INST_TYPE'),
        'is_online': online, 'is_honors': 'Honors' in attrs,
        'open_seats': {'Y': True, 'N': False}.get(raw.get('STUSEAT_OPEN')),
        'instructors_json': json.dumps(instructors, ensure_ascii=False),
        'meetings_json': json.dumps(meetings, ensure_ascii=False),
        'attributes_json': json.dumps(attrs, ensure_ascii=False),
        'meeting_time_status': 'complete' if timed and len(timed) == len(meetings) else 'partial' if timed else 'no_fixed_times',
        'timezone': 'Asia/Qatar' if site == 'Qatar' else 'America/Chicago' if site in ('College Station','Galveston') else '',
        'grade_rmp_links_json': '[]', 'grade_rmp_match_status': 'not_checked',
        'office_hours_status': 'not_checked', 'office_hours_text': '', 'office_location_text': '',
        'office_hours_instructor_evidence': '', 'office_hours_source_url': '',
        'office_hours_term_status': '', 'office_hours_checked_at': '',
        'office_hours_usable_for_conflict_checks': False,
        'syllabus_url': syllabus_url(term, crn), 'source_url': PUBLIC_SEARCH, 'fetched_at': fetched_at}


def link_history(sections, path):
    if not path.exists():
        return
    csv.field_size_limit(sys.maxsize)
    index = defaultdict(list)
    with path.open(newline='', encoding='utf-8-sig') as f:
        for g in csv.DictReader(f):
            index[(g['campus'], g['subject'], g['course_number'])].append(g)
    for s in sections:
        links = []
        for p in json.loads(s['instructors_json']):
            toks = norm(p['name']).split()
            candidates = []
            if len(toks) >= 2 and s['campus'] != 'Unknown':
                # Full RMP name preferred; source surname+initial only a heuristic.
                short_names = {' '.join(toks[i:]) + ' ' + toks[0][0] for i in range(1, len(toks))}
                pool = index[(s['campus'], s['subject'], s['course_number'])]
                exact = [g for g in pool if g.get('rmp_name') and norm(g['rmp_name']) == norm(p['name'])]
                candidates = exact or [g for g in pool if norm(g['instructor_name']) in short_names]
            identities = {g['instructor_name'] for g in candidates}
            if len(identities) == 1:
                for g in candidates:
                    links.append({'schedule_instructor': p['name'], 'campus': g['campus'], 'level': g['level'],
                        'subject': g['subject'], 'course_number': g['course_number'],
                        'historical_instructor': g['instructor_name'], 'rmp_professor_id': g.get('rmp_professor_id') or None,
                        'match_method': 'full_rmp_name' if norm(g.get('rmp_name','')) == norm(p['name']) else 'surname_initial_heuristic'})
            else:
                links.append({'schedule_instructor': p['name'], 'match_method': 'ambiguous' if candidates else 'unmatched'})
        s['grade_rmp_links_json'] = json.dumps(links, ensure_ascii=False)
        accepted = [x for x in links if x['match_method'] not in ('ambiguous', 'unmatched')]
        s['grade_rmp_match_status'] = 'matched' if links and len(accepted) == len(links) else 'partial' if accepted else 'unmatched'


class Client:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'TAMU-student-schedule-project/1.0'
        self.last = 0

    def request(self, method, url, **kwargs):
        time.sleep(max(0, 1 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        return self.session.request(method, url, timeout=45, **kwargs)


def extract_office_hours(html, section, source_url):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    term_ok = section['term_name'] in text
    course_ok = bool(re.search(r'\b' + re.escape(section['subject']) + r'\s+' + re.escape(section['course_number']) + r'\b', text))
    crn_ok = section['crn'] in text
    details = []
    for h in soup.find_all(['h2', 'h3']):
        if re.search(r'instructor|office hours', h.get_text(), re.I):
            parent = h.find_parent(class_='component-wrapper') or h.parent
            details.append(parent.get_text('\n', strip=True))
    evidence = '\n'.join(dict.fromkeys(details))
    match = re.search(r'Office Hours\s*:?\s*(.*?)(?=Preferred Contact|Office Location|Email:|Phone:|\Z)', evidence, re.I | re.S)
    hours = match.group(1).strip() if match else ''
    loc = re.search(r'Office Location\s*:?\s*(.*?)(?=Phone:|Office Hours|Email:|\Z)', evidence, re.I | re.S)
    status = 'published_text_needs_review' if hours else 'not_stated'
    if re.search(r'canvas|log\s*in', hours, re.I):
        status = 'login_required'
    elif re.search(r'by appointment', hours, re.I) and not re.search(r'\d\s*[:ap]', hours, re.I):
        status = 'by_appointment'
    if not (term_ok and course_ok and crn_ok):
        status = 'source_mismatch_needs_review'
    return {'office_hours_status': status, 'office_hours_text': hours,
        'office_location_text': loc.group(1).strip() if loc else '',
        'office_hours_instructor_evidence': evidence,
        'office_hours_source_url': source_url,
        'office_hours_term_status': 'Spring 2027 confirmed' if term_ok and course_ok and crn_ok else 'unverified',
        'office_hours_checked_at': stamp(), 'office_hours_usable_for_conflict_checks': False}


def fetch_office_hours(client, section):
    # Public PDF redirect resolves the published document code without using any login.
    response = client.request('GET', syllabus_url(section['term_code'], section['crn'], 'pdf'))
    path = urlparse(response.url).path
    code = re.search(r'/api2/doc-pdf/([A-Za-z0-9]+)', path)
    if response.status_code in (401, 403, 429):
        raise RuntimeError(f'Syllabus service returned {response.status_code}; stopping office-hour requests.')
    if not code:
        return {'office_hours_status': 'syllabus_unavailable', 'office_hours_checked_at': stamp(), 'office_hours_source_url': section['syllabus_url']}
    url = SIMPLE + '/api2/doc-html/' + code.group(1)
    html = client.request('GET', url)
    html.raise_for_status()
    return extract_office_hours(html.text, section, SIMPLE + '/en-US/doc/' + code.group(1))


def checkpoint(out, sections, state):
    write_csv(out / 'spring_2027_sections.csv', sections)
    if all('prerequisite_status' in s for s in sections):
        write_csv(out / 'spring_2027_sections_with_prerequisites.csv', sections)
    fields = ['term_code','crn','campus','subject','course_number','section','instructors_json'] + [k for k in sections[0] if k.startswith('office_')]
    write_csv(out / 'spring_2027_office_hours.csv', [{k:s[k] for k in fields} for s in sections])
    save_json(out / 'office_hours_progress.json', {'updated_at':stamp(), 'state':state,
        'total_sections':len(sections), 'status_counts':dict(Counter(s['office_hours_status'] for s in sections))})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'output')
    parser.add_argument('--history', type=Path, default=ROOT / 'output/schedule_dataset.csv')
    parser.add_argument('--offline', action='store_true', help='Use only saved schedule and office-hour caches.')
    parser.add_argument('--refresh-schedule', action='store_true')
    parser.add_argument('--office-hours', type=int, default=0, help='Maximum NEW section syllabus lookups this run; 0 uses cache only.')
    parser.add_argument('--office-subjects', default='', help='Prioritize comma-separated subjects for office hours; all sections still exported.')
    args = parser.parse_args()
    out, client = args.output_dir, Client()
    cache = out / 'schedule_cache'
    cache.mkdir(parents=True, exist_ok=True)
    terms_path = cache / 'terms.json'
    if not terms_path.exists() or args.refresh_schedule:
        if args.offline:
            raise RuntimeError('No term cache or refresh requested in offline mode.')
        r = client.request('GET', HOWDY + '/api/all-terms'); r.raise_for_status()
        save_json(terms_path, r.json())
    terms = json.loads(terms_path.read_text())
    selected = [t for t in terms if t['STVTERM_DESC'] in ('Spring 2027 - College Station','Spring 2027 - Galveston','Spring 2027 - Qatar')]
    if not selected:
        raise RuntimeError('Spring 2027 terms unavailable; no export written.')
    sections, counts = [], {}
    for t in selected:
        code = t['STVTERM_CODE']; path = cache / (code + '.json')
        if not path.exists() or args.refresh_schedule:
            if args.offline:
                raise RuntimeError(f'Missing cached term {code}')
            r = client.request('POST', HOWDY + '/api/course-sections', json={'startRow':0,'endRow':0,'termCode':code,'publicSearch':'Y'})
            r.raise_for_status(); raw = r.json()
            if not isinstance(raw, list) or not raw:
                raise RuntimeError(f'Empty or invalid section response for {code}; no export written.')
            if any(x.get(PREFIX+'TERM') != code for x in raw):
                raise RuntimeError('Returned term does not match request.')
            save_json(path, raw)
        raw = json.loads(path.read_text())
        fetched = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        counts[t['STVTERM_DESC']] = len(raw)
        sections.extend(normalize_section(x, t['STVTERM_DESC'], fetched) for x in raw)
    keys = [(s['term_code'],s['crn']) for s in sections]
    if len(keys) != len(set(keys)):
        raise RuntimeError('Duplicate term/CRN identifiers; refusing ambiguous export.')
    ensure_catalogs(client, cache, selected, offline=args.offline, refresh=args.refresh_schedule)
    attach_prerequisites(sections, cache)
    fill_missing_prerequisites(client, sections, cache, offline=args.offline)
    link_history(sections, args.history)
    priorities = args.office_subjects.upper().split(',')
    ordered = sorted(sections, key=lambda s:(s['subject'] not in priorities, s['subject'], s['course_number'], s['crn']))
    attempts, errors = 0, []
    for s in sections:
        path = cache / 'office_hours' / f'{s["term_code"]}_{s["crn"]}.json'
        if path.exists():
            s.update(json.loads(path.read_text()))
    checkpoint(out, sections, 'running' if args.office_hours and not args.offline else 'building_from_cache')
    for s in ordered:
        path = cache / 'office_hours' / f'{s["term_code"]}_{s["crn"]}.json'
        if path.exists():
            s.update(json.loads(path.read_text()))
        elif not args.offline and attempts < args.office_hours:
            attempts += 1
            try:
                result = fetch_office_hours(client, s)
                save_json(path, result); s.update(result)
                print(f'Office hours {attempts}: {s["subject"]} {s["course_number"]}-{s["section"]}: {s["office_hours_status"]}', flush=True)
                if attempts % 100 == 0:
                    checkpoint(out, sections, 'running')
            except KeyboardInterrupt:
                errors.append('Interrupted; rerun to resume.')
                break
            except Exception as exc:
                errors.append(str(exc)); s['office_hours_status'] = 'lookup_error'
                print(f'Office-hour collection stopped: {exc}', flush=True)
                break
    # Reload existing office caches for all rows, including those after a service failure.
    for s in sections:
        path = cache / 'office_hours' / f'{s["term_code"]}_{s["crn"]}.json'
        if path.exists():
            s.update(json.loads(path.read_text()))
    checkpoint(out, sections, 'stopped_on_error' if errors else 'run_finished')
    report = {'created_at':stamp(), 'section_count':len(sections), 'source_term_counts':counts,
        'section_site_counts':dict(Counter(s['campus'] for s in sections)),
        'history_match_counts':dict(Counter(s['grade_rmp_match_status'] for s in sections)),
        'prerequisite_status_counts':dict(Counter(s['prerequisite_status'] for s in sections)),
        'office_hour_status_counts':dict(Counter(s['office_hours_status'] for s in sections)),
        'meeting_time_status_counts':dict(Counter(s['meeting_time_status'] for s in sections)),
        'office_hour_errors':errors, 'history_file_found':args.history.exists(),
        'qatar_term_available':any(t['STVTERM_DESC']=='Spring 2027 - Qatar' for t in selected),
        'limitations':['Term campus is not the physical section site; filter campus explicitly.',
            'Unknown meeting times are not proof of an asynchronous course.',
            'Honors is based on the explicit section attribute, not section-number guesses.',
            'Section links to historical abbreviated names are heuristic.',
            'Office-hour free text needs review before use in time-conflict logic.',
            'Prerequisite text is from the term course catalog; section overrides and student eligibility are not validated.',
            'No prerequisite text listed is not proof that a course has no requirements.',
            'Linked-section registration requirements are not validated.',
            'No old-term office hours are substituted for Spring 2027.']}
    save_json(out / 'spring_2027_report.json', report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
