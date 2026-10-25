// ==UserScript==
// @name         MaroonWay — import sections from Howdy
// @namespace    maroonway
// @version      0.1.0
// @description  Reads the class-search results you are already looking at and sends them to MaroonWay. Your NetID and password never leave your browser.
// @match        https://howdy.tamu.edu/*
// @match        https://compassxe-ssb.tamu.edu/*
// @match        https://tamu.collegescheduler.com/*
// @grant        none
// ==/UserScript==

/*
 * Why a userscript.
 *
 * A&M closed its public course API in 2023 and the replacement sits behind
 * NetID plus Duo two-factor, so nothing server-side can read class times. But
 * you can: you are already logged in. This runs in your own browser, reads the
 * results already on screen, and posts them to MaroonWay. No credential is
 * read, stored or transmitted.
 *
 * How to use it:
 *   1. Install Tampermonkey (or Violentmonkey) and add this script.
 *   2. Set TOKEN below to your backend's IMPORT_TOKEN, and ENDPOINT if the
 *      backend is not on localhost.
 *   3. Open Howdy's class search and run a search.
 *   4. Click the "MaroonWay" button, bottom right. It previews first (a dry
 *      run that writes nothing) and asks before importing.
 *
 * On selectors: Howdy's markup is behind a login, so this script cannot be
 * written blind against it. It therefore tries, in order:
 *   a) any JSON the page already fetched (Banner's searchResults payload),
 *   b) a generic results-table parse driven by the column headers,
 *   c) failing both, it dumps what it did find to the console so the selectors
 *      can be finished in one pass.
 * Run the preview first and read the console output.
 */

const ENDPOINT = 'http://127.0.0.1:8000/sections/import';
const TOKEN = 'change-me';

const DAY_WORDS = {
  monday: 'MON', mon: 'MON', m: 'MON',
  tuesday: 'TUE', tue: 'TUE', tues: 'TUE', t: 'TUE',
  wednesday: 'WED', wed: 'WED', w: 'WED',
  thursday: 'THU', thu: 'THU', thur: 'THU', thurs: 'THU', r: 'THU',
  friday: 'FRI', fri: 'FRI', f: 'FRI',
  saturday: 'SAT', sat: 'SAT', s: 'SAT',
  sunday: 'SUN', sun: 'SUN', u: 'SUN',
};

/** "MWF", "Mon Wed Fri", "TR" -> "MWF"-style codes the backend parses. */
function days(text) {
  if (!text) return '';
  const cleaned = String(text).trim();
  const words = cleaned.toLowerCase().split(/[\s,/;]+/).filter(Boolean);
  const named = words.map((w) => DAY_WORDS[w]).filter(Boolean);
  if (named.length === words.length && named.length) return named.join(',');
  // A compact pattern such as MWF or TR; the backend understands it directly.
  return /^[MTWRFSU]+$/i.test(cleaned.replace(/\s+/g, '')) ? cleaned.replace(/\s+/g, '') : '';
}

/** "9:10 am - 10:00 am" -> { start, end } */
function timeRange(text) {
  if (!text) return null;
  const parts = String(text).split(/\s*(?:-|–|to)\s*/);
  if (parts.length < 2) return null;
  return { start: parts[0].trim(), end: parts[1].trim() };
}

/** (a) Banner's own JSON, if the page fetched it and left it around. */
function fromBannerPayload() {
  const pools = [window.searchResults, window.__SEARCH_RESULTS__, window.sectionResults];
  for (const pool of pools) {
    const rows = pool && (pool.data || pool.sections || pool);
    if (!Array.isArray(rows) || !rows.length) continue;
    return rows
      .map((row) => {
        const meetings = (row.meetingsFaculty || row.meetingTimes || [])
          .map((entry) => {
            const m = entry.meetingTime || entry;
            const picked = Object.entries(DAY_WORDS)
              .filter(([word]) => m[word] === true)
              .map(([, code]) => code);
            if (!picked.length || !m.beginTime) return null;
            const pad = (t) => `${String(t).slice(0, 2)}:${String(t).slice(2, 4)}`;
            return {
              days: [...new Set(picked)].join(','),
              start: pad(m.beginTime),
              end: pad(m.endTime),
              building: m.buildingDescription || m.building || null,
              room: m.room || null,
            };
          })
          .filter(Boolean);
        return {
          term: row.termDesc || row.term,
          subject: row.subject,
          number: row.courseNumber,
          section: row.sequenceNumber || row.section,
          instructor: (row.faculty || []).map((f) => f.displayName).join('; ') || null,
          campus: row.campusDescription || null,
          delivery: row.instructionalMethodDescription || null,
          seats: row.maximumEnrollment ?? null,
          seats_open: row.seatsAvailable ?? null,
          meetings,
        };
      })
      .filter((s) => s.term && s.section);
  }
  return [];
}

/** (b) A generic table parse, driven by whatever the headers say. */
function fromTable() {
  const tables = [...document.querySelectorAll('table')];
  const wanted = /subject|course|section|crn|days|time|instructor/i;
  const table = tables.find((t) =>
    [...t.querySelectorAll('th')].some((th) => wanted.test(th.textContent || ''))
  );
  if (!table) return [];

  const headers = [...table.querySelectorAll('th')].map((th) =>
    (th.textContent || '').trim().toLowerCase()
  );
  const find = (...names) => headers.findIndex((h) => names.some((n) => h.includes(n)));
  const columns = {
    term: find('term'),
    subject: find('subject'),
    number: find('course number', 'catalog', 'number'),
    course: find('course'),
    section: find('section', 'crn'),
    instructor: find('instructor', 'faculty'),
    days: find('days', 'meeting days'),
    time: find('time', 'meeting time'),
    location: find('location', 'room', 'building'),
    campus: find('campus'),
    delivery: find('method', 'mode', 'delivery'),
    seats: find('capacity', 'max'),
    open: find('available', 'remaining', 'open'),
  };

  const termOnPage =
    (document.querySelector('[class*="term"], [id*="term"]')?.textContent || '').trim() || null;

  return [...table.querySelectorAll('tbody tr')]
    .map((tr) => {
      const cells = [...tr.querySelectorAll('td')].map((td) => (td.textContent || '').trim());
      if (!cells.length) return null;
      const at = (index) => (index >= 0 ? cells[index] || null : null);
      const range = timeRange(at(columns.time));
      const location = (at(columns.location) || '').split(/\s+/);
      return {
        term: at(columns.term) || termOnPage,
        subject: at(columns.subject),
        number: at(columns.number),
        course: at(columns.course),
        section: at(columns.section),
        instructor: at(columns.instructor),
        campus: at(columns.campus),
        delivery: at(columns.delivery),
        seats: Number(at(columns.seats)) || null,
        seats_open: Number(at(columns.open)) || null,
        meetings: range
          ? [
              {
                days: days(at(columns.days)),
                start: range.start,
                end: range.end,
                building: location[0] || null,
                room: location.slice(1).join(' ') || null,
              },
            ]
          : [],
      };
    })
    .filter((s) => s && s.section && (s.term || termOnPage));
}

function collect() {
  const fromJson = fromBannerPayload();
  if (fromJson.length) {
    console.info(`[MaroonWay] read ${fromJson.length} sections from the page's own JSON`);
    return fromJson;
  }
  const fromDom = fromTable();
  if (fromDom.length) {
    console.info(`[MaroonWay] read ${fromDom.length} sections from the results table`);
    return fromDom;
  }
  console.warn(
    '[MaroonWay] found no sections. Tables on this page:',
    [...document.querySelectorAll('table')].map((t) =>
      [...t.querySelectorAll('th')].map((th) => th.textContent.trim())
    )
  );
  return [];
}

async function send(sections, dryRun) {
  const response = await fetch(ENDPOINT, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-import-token': TOKEN },
    body: JSON.stringify({ sections, dry_run: dryRun }),
  });
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

function button() {
  const el = document.createElement('button');
  el.textContent = 'MaroonWay: import sections';
  el.style.cssText =
    'position:fixed;right:18px;bottom:18px;z-index:99999;padding:10px 14px;border:0;' +
    'border-radius:8px;background:#500000;color:#fff;font:600 13px system-ui;cursor:pointer;' +
    'box-shadow:0 2px 10px rgba(0,0,0,.25)';
  el.onclick = async () => {
    const sections = collect();
    if (!sections.length) {
      el.textContent = 'MaroonWay: nothing found — see console';
      return;
    }
    el.disabled = true;
    try {
      el.textContent = 'MaroonWay: checking…';
      const preview = await send(sections, true);
      const ok = confirm(
        `Found ${preview.received} rows.\n` +
          `${preview.accepted} sections, ${preview.meetings} meetings.\n` +
          `Skipped: ${JSON.stringify(preview.skipped)}\n\nImport them?`
      );
      if (!ok) {
        el.textContent = 'MaroonWay: import sections';
        return;
      }
      const result = await send(sections, false);
      el.textContent = `MaroonWay: imported ${result.sections_written}`;
      console.info('[MaroonWay] import result', result);
    } catch (error) {
      el.textContent = 'MaroonWay: failed — see console';
      console.error('[MaroonWay]', error);
    } finally {
      el.disabled = false;
    }
  };
  return el;
}

document.addEventListener('DOMContentLoaded', () => document.body.appendChild(button()));
if (document.readyState !== 'loading') document.body.appendChild(button());
