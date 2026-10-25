"""Term-specific course-catalog prerequisite enrichment; not an eligibility engine."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

API_URL = 'https://howdyportal.tamu.edu/api/get-catalog-courses'
HEADING = re.compile(r'\b(?P<label>prerequisite(?:s|\(s\))?(?:\s*/\s*corequisite(?:s|\(s\))?)?|corequisite(?:s|\(s\))?|cross[ -]?listing|cross[ -]?listed)\s*:?\s*', re.I)


def extract_requirements(narrative):
    text = ' '.join(BeautifulSoup(narrative or '', 'html.parser').get_text(' ', strip=True).split())
    pre, co = [], []
    # Don't mistake prose such as 'additional prerequisites' for a heading.
    matches = [m for m in HEADING.finditer(text) if ':' in m.group()
               or (m['label'][0].isupper() and
                   (not text[:m.start()].strip() or text[:m.start()].rstrip()[-1] in '.;!?'))]
    for i, match in enumerate(matches):
        label = match['label'].lower()
        value = text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)].strip()
        if label.startswith('prerequisite'):
            pre.append(value)
            if '/' in label:
                co.append(value)
        elif label.startswith('corequisite'):
            co.append(value)
    prerequisite, corequisite = ' '.join(pre), ' '.join(co)
    if not text:
        status = 'catalog_description_missing'
    elif prerequisite or corequisite:
        status = 'requirements_listed'
        if prerequisite.lower().strip(' .') in ('none', 'no prerequisites') and not corequisite:
            status = 'explicitly_none'
    else:
        status = 'not_listed_in_catalog'
    return {'prerequisite_text': prerequisite, 'corequisite_text': corequisite,
            'prerequisite_status': status, 'prerequisite_catalog_narrative': text}


def ensure_catalogs(client, cache, terms, offline=False, refresh=False):
    for term in terms:
        code = term['STVTERM_CODE']
        path = cache / f'catalog_{code}.json'
        if path.exists() and not refresh:
            continue
        if offline:
            raise RuntimeError(f'Missing prerequisite catalog cache for {code}; run once without --offline.')
        response = client.request('POST', API_URL, json={'termCode':code})
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            raise ValueError(f'Invalid prerequisite catalog for {code}')
        if any(str(r.get('TERM')) != code for r in rows):
            raise ValueError('Prerequisite catalog returned a different term.')
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)


def attach_prerequisites(sections, cache):
    catalogs = {}
    for term in {s['term_code'] for s in sections}:
        path = cache / f'catalog_{term}.json'
        rows = json.loads(path.read_text())
        index = {}
        for r in rows:
            key = (r['SCBCRKY_SUBJ_CODE'], str(r['SCBCRKY_CRSE_NUMB']))
            if key in index:
                raise ValueError(f'Duplicate catalog course: {term} {key}')
            index[key] = extract_requirements(r.get('COURSE_NARRATIVE'))
        catalogs[term] = (index, datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    for s in sections:
        index, fetched = catalogs[s['term_code']]
        requirements = index.get((s['subject'], s['course_number']))
        s.update(requirements or {'prerequisite_text':'', 'corequisite_text':'',
                                  'prerequisite_status':'course_not_in_catalog', 'prerequisite_catalog_narrative':''})
        s.update(prerequisite_source_url=API_URL, prerequisite_source_term=s['term_code'],
                 prerequisite_source_fetched_at=fetched, prerequisite_scope='term_course_catalog',
                 prerequisite_section_verified=False)


def fill_missing_prerequisites(client, sections, cache, offline=False):
    """Ask Howdy's section prerequisite display when no catalog narrative exists."""
    for s in sections:
        if s['prerequisite_status'] not in ('catalog_description_missing', 'course_not_in_catalog'):
            continue
        path = cache / 'section_prerequisites' / f'{s["term_code"]}_{s["crn"]}.json'
        if not path.exists() and not offline:
            response = client.request('POST', 'https://howdyportal.tamu.edu/api/section-prereqs',
                                      json={'term':s['term_code'], 'crn':s['crn']})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or 'P_PRE_REQS_OUT' not in result:
                raise ValueError('Unexpected section prerequisite response; no empty value assumed.')
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(result), encoding='utf-8'); tmp.replace(path)
        if path.exists():
            result = json.loads(path.read_text())
            text = ' '.join((result['P_PRE_REQS_OUT'] or '').split())
            s.update(prerequisite_text=text,
                prerequisite_status='requirements_listed' if text else 'none_reported_by_section_search',
                prerequisite_scope='section_prerequisite_display', prerequisite_section_verified=True,
                prerequisite_source_url='https://howdyportal.tamu.edu/api/section-prereqs',
                prerequisite_source_fetched_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
