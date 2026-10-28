// ==UserScript==
// @name         MaroonWay — import a whole term from Aggie Schedule Builder
// @namespace    maroonway
// @version      0.1.0
// @description  Walks every course in a term through the Schedule Builder's own API and sends the sections to MaroonWay. Your NetID and password never leave your browser.
// @match        https://tamu.collegescheduler.com/*
// @grant        none
// ==/UserScript==

/*
 * Why this exists, and why it replaces the Howdy scraper.
 *
 * Aggie Schedule Builder is a single-page app over a JSON API, and the session
 * you are already signed into is all the authorisation it needs. So there is
 * nothing to scrape: no selectors, no table parsing, no guessing at markup
 * behind a login. Three endpoints carry the whole term.
 *
 *   GET /api/app-data
 *       { terms: [{ id: "Spring 2027 - College Station", code: "202711" }, ...] }
 *       Eight terms, each a campus-specific id. The id, not the code, is what
 *       the other two routes take.
 *
 *   GET /api/terms/{term}/courses
 *       Every course in the term in one response -- 4,240 for Spring 2027,
 *       3,295 for Fall 2026 -- each with title, description, prerequisites and
 *       corequisites.
 *
 *   GET /api/terms/{term}/subjects/{SUBJ}/courses/{NUM}/regblocks
 *       { registrationBlocks: [...], sections: [...] } for one course. This is
 *       the only per-course call, so a term costs one request per course.
 *
 * What a section carries that we could not get before:
 *
 *   instructor[].name  "Cantu, Justin Colt" -- the full name. The grade
 *                      reports give "CANTU J", and matching an initial against
 *                      RateMyProfessors is what leaves 64% of our instructors
 *                      unlinked. A full first name is a different problem.
 *   isHonors           the flag itself, rather than inferred from a title.
 *   isOnline           and instructionMode alongside it.
 *   openSeats          live.
 *   meetings[]         days ("R" for Thursday, which our parser already
 *                      speaks), startTime/endTime as HHMM integers, building
 *                      code and room.
 *
 * One trap worth knowing: meetings include exams. A meeting with
 * meetingType "EXAM" is a final sitting in November, not a weekly class, and
 * importing it would put a phantom block on the calendar and wreck every gap
 * calculation. Those are dropped below; only real class meetings are sent.
 *
 * Usage:
 *   1. Install Tampermonkey or Violentmonkey and add this script.
 *   2. Set TOKEN to your backend's IMPORT_TOKEN, and ENDPOINT if the backend
 *      is not on localhost.
 *   3. Sign in to tamu.collegescheduler.com as usual.
 *   4. Click "MaroonWay export", bottom right. It previews first -- a dry run
 *      that writes nothing -- and asks before importing.
 *
 * It is deliberately unhurried: one course at a time with a pause between, so
 * it reads like a person using the site rather than a crawler. A term takes a
 * few minutes. Progress is saved, so closing the tab and starting again
 * resumes rather than restarting.
 */

const ENDPOINT = 'http://127.0.0.1:8000/sections/import';
const TOKEN = 'change-me';

/** Pause between course requests, ms. Courtesy, not a limit we were given. */
const DELAY = 180;
/** The backend accepts 5000 sections per request. */
const BATCH = 2000;
const PROGRESS_KEY = 'maroonway.export.progress';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function api(path) {
  const response = await fetch(path, { credentials: 'include' });
  if (!response.ok) throw new Error(`${response.status} for ${path}`);
  const type = response.headers.get('content-type') || '';
  // Unknown /api/ paths fall through to the SPA's own HTML with a 200, so a
  // wrong route looks like success until something downstream explodes.
  if (!type.includes('json')) throw new Error(`not JSON: ${path}`);
  return response.json();
}

/** "Cantu, Justin Colt" -> "Justin Colt Cantu". */
function readableName(name) {
  const text = String(name || '').trim();
  if (!text.includes(',')) return text;
  const [last, rest] = text.split(/\s*,\s*/, 2);
  return `${(rest || '').trim()} ${last.trim()}`.trim();
}

/** 1730 -> "17:30". The API gives HHMM as an integer. */
function clock(value) {
  if (value === null || value === undefined || value === '') return null;
  const minutes = Number(value);
  if (!Number.isFinite(minutes)) return null;
  const hour = Math.floor(minutes / 100);
  const minute = minutes % 100;
  if (hour > 23 || minute > 59) return null;
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

/**
 * Weekly class meetings only.
 *
 * meetingType "EXAM" is a single sitting on one date. It shares the shape of a
 * class meeting and would import as a recurring block, so it is dropped rather
 * than normalised.
 */
function meetingsOf(section) {
  return (section.meetings || [])
    .filter((m) => String(m.meetingType || '').toUpperCase() !== 'EXAM')
    .map((m) => ({
      days: m.daysRaw || m.days || null,
      start: clock(m.startTime),
      end: clock(m.endTime),
      building: m.buildingCode || m.building || null,
      room: m.room || null,
    }))
    .filter((m) => m.days && m.start && m.end);
}

/** Our four campus codes, read off the section rather than the term name. */
function campusOf(section, term) {
  const text = `${section.campusCode || ''} ${section.campus || ''} ${term}`.toUpperCase();
  if (text.includes('GALVESTON') || text.includes('AGLV')) return 'GALV';
  if (text.includes('QATAR') || text.includes('AQAT')) return 'QATAR';
  if (text.includes('BLINN')) return 'BLINN';
  return 'CSTAT';
}

function deliveryOf(section) {
  if (section.isOnline) return 'WEB';
  const mode = String(section.instructionMode || '').toUpperCase();
  if (mode.includes('ONLINE') || mode.includes('WEB')) return 'WEB';
  if (mode.includes('HYBRID') || mode.includes('BLEND')) return 'HYBRID';
  return 'F2F';
}

function toImported(section, course, term) {
  const who = (section.instructor || [])
    .map((i) => readableName(i.name))
    .filter(Boolean);
  return {
    term,
    subject: course.subjectId,
    number: course.number,
    section: String(section.sectionNumber ?? section.id ?? '').trim(),
    // The instructor of record is the first; the rest are co-teachers and our
    // schema holds one. Sending a joined string would invent a person.
    instructor: who[0] || null,
    campus: campusOf(section, term),
    delivery: deliveryOf(section),
    honors: Boolean(section.isHonors),
    seats: null,
    seats_open: typeof section.openSeats === 'number' ? section.openSeats : null,
    meetings: meetingsOf(section),
  };
}

async function collect(term, onProgress) {
  const encoded = encodeURIComponent(term);
  const courses = await api(`/api/terms/${encoded}/courses`);
  const saved = JSON.parse(localStorage.getItem(PROGRESS_KEY) || '{}');
  const done = saved.term === term ? new Set(saved.done || []) : new Set();
  const out = saved.term === term ? saved.sections || [] : [];

  for (let i = 0; i < courses.length; i += 1) {
    const course = courses[i];
    if (done.has(course.id)) continue;
    try {
      const block = await api(
        `/api/terms/${encoded}/subjects/${encodeURIComponent(course.subjectId)}` +
          `/courses/${encodeURIComponent(course.number)}/regblocks`,
      );
      for (const section of block.sections || []) {
        out.push(toImported(section, course, term));
      }
    } catch (error) {
      // One bad course must not lose a term's worth of work.
      console.warn('[MaroonWay] skipped', course.id, error.message);
    }
    done.add(course.id);
    if (i % 25 === 0) {
      localStorage.setItem(
        PROGRESS_KEY,
        JSON.stringify({ term, done: [...done], sections: out }),
      );
      onProgress(i + 1, courses.length, out.length);
    }
    await sleep(DELAY);
  }
  localStorage.setItem(PROGRESS_KEY, JSON.stringify({ term, done: [...done], sections: out }));
  onProgress(courses.length, courses.length, out.length);
  return out;
}

async function send(sections, dryRun) {
  const totals = { received: 0, accepted: 0, sections_written: 0, meetings: 0 };
  for (let i = 0; i < sections.length; i += BATCH) {
    const response = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Import-Token': TOKEN },
      body: JSON.stringify({ sections: sections.slice(i, i + BATCH), dry_run: dryRun }),
    });
    if (!response.ok) throw new Error(`import failed: ${response.status} ${await response.text()}`);
    const body = await response.json();
    for (const key of Object.keys(totals)) totals[key] += body[key] || 0;
  }
  return totals;
}

(function ui() {
  const button = document.createElement('button');
  button.textContent = 'MaroonWay export';
  button.style.cssText =
    'position:fixed;right:16px;bottom:16px;z-index:99999;padding:10px 14px;' +
    'border-radius:10px;border:0;background:#500000;color:#fff;font:600 13px system-ui;cursor:pointer';
  const say = (text) => {
    button.textContent = text;
    console.log('[MaroonWay]', text);
  };

  button.onclick = async () => {
    button.disabled = true;
    try {
      const app = await api('/api/app-data');
      const names = app.terms.map((t, i) => `${i + 1}. ${t.id}`).join('\n');
      const answer = prompt(`Which term?\n\n${names}\n\nNumber:`, '1');
      const term = app.terms[Number(answer) - 1];
      if (!term) return;

      say('Reading courses…');
      const sections = await collect(term.id, (done, total, found) =>
        say(`${done}/${total} courses · ${found} sections`),
      );
      const withTimes = sections.filter((s) => s.meetings.length).length;

      say('Previewing…');
      const preview = await send(sections, true);
      const ok = confirm(
        `${term.id}\n\n` +
          `${sections.length} sections, ${withTimes} with meeting times.\n` +
          `The backend would accept ${preview.accepted} and write ` +
          `${preview.meetings} meetings.\n\nImport for real?`,
      );
      if (!ok) return say('MaroonWay export');

      say('Importing…');
      const result = await send(sections, false);
      localStorage.removeItem(PROGRESS_KEY);
      say(`Done: ${result.sections_written} sections`);
      console.log('[MaroonWay] import result', result);
    } catch (error) {
      console.error('[MaroonWay]', error);
      say('Failed — see console');
    } finally {
      button.disabled = false;
    }
  };

  document.body.appendChild(button);
})();
