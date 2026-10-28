/**
 * Typed client for the MaroonWay backend (backend/, FastAPI).
 *
 * Server-side only: every caller is a Server Component, so `BACKEND_URL` and
 * anything else in the environment stays on the server, the backend needs no
 * CORS, and it does not have to be exposed publicly. Do not import this from a
 * file with `'use client'` — use a Server Action or a route handler instead.
 *
 * `cache: 'no-store'` is deliberate: the backend keeps its own hot cache for
 * recently viewed professors, so caching the same payload again here would only
 * make it staler.
 */

/**
 * Where the API lives.
 *
 * Accepts a bare hostname as well as a full URL, because Render's blueprint
 * fills this in from the API service with `fromService`, which yields a host
 * like `maroonway-api.onrender.com` and cannot prepend a scheme. A bare host
 * is assumed to be https; only a local address is assumed to be http.
 */
function backendBase(): string {
  const configured = (process.env.BACKEND_URL ?? '').trim();

  // A localhost default is right on a laptop and actively misleading on a
  // server: nothing listens on 127.0.0.1 inside a Render container, so an
  // unset BACKEND_URL surfaced as "could not reach 127.0.0.1:8000" -- an
  // error about the wrong machine, which reads as the app falling back to
  // localhost rather than as a variable nobody set.
  if (!configured) {
    if (process.env.NODE_ENV === 'production') return '';
    return 'http://127.0.0.1:8000';
  }

  const raw = configured;
  const withScheme = /^https?:\/\//.test(raw)
    ? raw
    : `${/^(localhost|127\.0\.0\.1|\[::1\])(:|$)/.test(raw) ? 'http' : 'https'}://${raw}`;
  // A trailing slash would turn every path into a double slash.
  return withScheme.replace(/\/+$/, '');
}

const BACKEND_URL = backendBase();

export type Score = {
  rating_count: number;
  raw_rating: number | null;
  raw_difficulty: number | null;
  would_take_again_percent: number | null;
  adj_rating: number;
  adj_difficulty: number;
  adj_would_take_again: number | null;
  adj_gpa: number | null;
  composite: number;
};

export type CourseScore = {
  course_id: number;
  code: string;
  title: string | null;
  campus: string | null;
  honors: boolean;
  class_rating_count: number;
  section_count: number;
  adj_rating: number;
  adj_difficulty: number;
  adj_would_take_again: number | null;
  adj_gpa: number | null;
  composite: number;
};

export type GradeRow = {
  code: string;
  title: string | null;
  term: string;
  term_year: number | null;
  term_season: string | null;
  section: string | null;
  gpa: number | null;
  enrolled: number | null;
};

export type Comment = {
  class_code: string | null;
  comment: string;
  helpful: number | null;
  clarity: number | null;
  difficulty: number | null;
  rated_at: string | null;
};

export type Summary = {
  subject_type: 'instructor' | 'instructor_course';
  course_id: number | null;
  course_code: string | null;
  model: string;
  prompt_version: string;
  summary_md: string;
  facets: Record<string, unknown>;
  window_start: string | null;
  window_end: string | null;
  source_rating_count: number;
  generated_at: string | null;
};

export type Professor = {
  instructor_id: number;
  full_name: string;
  department: string | null;
  rmp_id: number | null;
  score: Score;
  courses: CourseScore[];
  grades: GradeRow[];
  recent_comments: Comment[];
  summaries: Summary[];
};

export type SearchHit = {
  instructor_id: number;
  full_name: string;
  department: string | null;
  rmp_id: number | null;
  name_similarity: number | null;
  score: Score;
};

export type SearchResponse = {
  query: string;
  department: string | null;
  total: number;
  limit: number;
  offset: number;
  results: SearchHit[];
};

export type CourseInstructor = {
  instructor_id: number;
  full_name: string;
  department: string | null;
  rmp_id: number | null;
  class_rating_count: number;
  instructor_rating_count: number;
  section_count: number;
  adj_rating: number;
  adj_difficulty: number;
  adj_would_take_again: number | null;
  adj_gpa: number | null;
  composite: number;
};

export type SummaryEnvelope = {
  status: 'ready' | 'missing';
  instructor_id: number;
  course_code: string | null;
  prompt_version: string;
  summary: Summary | null;
};

export type Health = {
  status: string;
  database: string;
  data_version: number;
  detail: string | null;
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function url(path: string, query?: Query) {
  const target = new URL(path, BACKEND_URL);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== '') {
      target.searchParams.set(key, String(value));
    }
  }
  return target.toString();
}

async function get<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  const target = url(path, query);
  const response = await fetch(target, {
    cache: 'no-store',
    headers: { accept: 'application/json' },
    signal,
  });

  if (!response.ok) {
    const body = await response.text().catch(() => '');
    // A gateway error arrives as a full HTML page, which is useless in a
    // message and drowns the one part that matters -- the status.
    const detail = /^\s*<(!doctype|html)/i.test(body)
      ? ''
      : `: ${body.slice(0, 200)}`;
    throw new ApiError(response.status, path, `${response.status} from ${path}${detail}`);
  }
  return (await response.json()) as T;
}

/** `null` for a professor that does not exist, rather than a thrown 404. */
export async function getProfessor(instructorId: number): Promise<Professor | null> {
  try {
    return await get<Professor>(`/professors/${instructorId}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export function searchProfessors(params: {
  q?: string;
  dept?: string;
  limit?: number;
  offset?: number;
}): Promise<SearchResponse> {
  return get<SearchResponse>('/professors/search', params);
}

export function getProfessorCourses(instructorId: number): Promise<CourseScore[]> {
  return get<CourseScore[]>(`/professors/${instructorId}/courses`);
}

/**
 * Summaries are generated in batch, so `status: 'missing'` is a normal answer
 * and not an error — render a placeholder, not a failure.
 */
export function getProfessorSummary(
  instructorId: number,
  courseCode?: string
): Promise<SummaryEnvelope> {
  return get<SummaryEnvelope>(`/professors/${instructorId}/summary`, { course: courseCode });
}

export function getCourseInstructors(
  dept: string,
  number: string,
  limit?: number
): Promise<CourseInstructor[]> {
  return get<CourseInstructor[]>(
    `/courses/${encodeURIComponent(dept)}/${encodeURIComponent(number)}/instructors`,
    { limit }
  );
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return get<Health>('/healthz', undefined, signal);
}

// --- scheduling --------------------------------------------------------------

export type Meeting = {
  day: string;
  start: string;
  end: string;
  building: string | null;
  room: string | null;
};

export type ScheduleSection = {
  section_id: number;
  course_id: number;
  code: string;
  section_code: string;
  instructor_id: number | null;
  instructor_name: string | null;
  campus: string | null;
  delivery: string | null;
  honors: boolean;
  seats_open: number | null;
  meetings: Meeting[];
  adj_rating: number | null;
  adj_difficulty: number | null;
  adj_gpa: number | null;
  /** Share of students who earned an A in this course with this instructor. */
  pct_a: number | null;
  /** Reviews behind the rating: for this course, and for the instructor. */
  class_reviews: number;
  professor_reviews: number;
  /** Other sections at exactly these times taught by someone else. */
  same_time_alternatives: number;
};

export type Schedule = {
  sections: ScheduleSection[];
  /** 0-1 against the stated preferences; 0 when none were expressed. */
  preference_score: number;
  /** What earned this schedule its place. */
  reasons: string[];
  contributions: Contribution[];
  tightest_gap: number | null;
  mean_rating: number;
  mean_difficulty: number;
  mean_gpa: number | null;
  /** Share of students who earned an A, 0-1. */
  mean_pct_a: number | null;
  earliest_start: string | null;
  days_on_campus: number;
  /** An earlier option has this exact timetable; only the staff differ. */
  /** Whether the student expressed anything to score against. */
  scored?: boolean;
  /** Minutes waiting between classes, summed over the week. */
  idle_minutes: number;
};

export type Preferences = {
  rating: number;
  difficulty: number;
  grades: number;
  workload: number;
  lecture: number;
  attendance: number;
  avoid_early_mornings: number;
  avoid_fridays: number;
  delivery: string | null;
  campus: string | null;
  honors: boolean | null;
  min_gap_minutes: number;
  /** "jev-1.14" when Jev decided, "heuristic" for the keyword fallback, "default" when nothing was stated. */
  engine: string;
  low_confidence: string[];
  stated: string | null;
};

export type Contribution = { name: string; weight: number; value: number; points: number };

export type PreferenceAnswer = {
  kind: string;
  value: unknown;
  confidence: number | null;
  unit: number;
};

/** One course pinned by hand. Every field optional; unset does not constrain. */
export type SectionLock = {
  section_code?: string | null;
  instructor_id?: number | null;
  honors?: boolean | null;
  delivery?: string | null;
  campus?: string | null;
  /** Days this class may meet on, e.g. ['MON', 'WED']. */
  days?: string[];
  earliest?: string | null;
  latest?: string | null;
};

/** A section as the pinning panel lists it. */
export type CourseSection = {
  section_id: number;
  section_code: string;
  instructor_id: number | null;
  instructor_name: string | null;
  campus: string | null;
  delivery: string | null;
  honors: boolean;
  seats_open: number | null;
  adj_rating: number | null;
  adj_difficulty: number | null;
  class_reviews: number;
  professor_reviews: number;
  meetings: Meeting[];
};

export function getCourseSections(term: string, code: string): Promise<CourseSection[]> {
  return get<CourseSection[]>(
    `/schedule/sections?term=${encodeURIComponent(term)}&code=${encodeURIComponent(code)}`,
  );
}

export type ScheduleRequest = {
  term: string;
  courses: string[];
  /** What the student wants, in their own words. Jev turns it into weights. */
  wants?: string | null;
  min_gap_minutes?: number;
  earliest?: string;
  latest?: string;
  excluded_days?: string[];
  campus?: string;
  honors?: boolean;
  delivery?: string;
  open_only?: boolean;
  /** Course code -> what the student pinned. Hard filters, not preferences. */
  locks?: Record<string, SectionLock>;
  limit?: number;
};

export type ScheduleResponse = {
  request: ScheduleRequest;
  count: number;
  schedules: Schedule[];
  preferences: Preferences;
  /** Set when nothing could be built — says which constraint bit. */
  detail: string | null;
  /** Preferences the timetable could not honour, stated plainly. */
  relaxed?: string[];
  /** What these courses can offer where they could not offer what was asked. */
  closest_fit?: string[];
  /** What the student's own words pinned. Confirmations, not warnings. */
  pinned?: string[];
};

export type PreferenceResponse = {
  preferences: Preferences;
  answers: Record<string, PreferenceAnswer>;
};

/**
 * Ask Jev what the student's words mean, without building anything — so the UI
 * can show what was understood before committing to a schedule.
 */
export async function readPreferences(wants: string): Promise<PreferenceResponse> {
  const response = await fetch(url('/schedule/preferences'), {
    method: 'POST',
    cache: 'no-store',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({ wants }),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new ApiError(response.status, '/schedule/preferences', `${response.status}: ${detail}`);
  }
  return (await response.json()) as PreferenceResponse;
}

export type TermSummary = { term: string; sections: number; with_times: number };

/** Terms that have sections loaded. `with_times` is what the scheduler needs. */
export function getTerms(): Promise<TermSummary[]> {
  return get<TermSummary[]>('/schedule/terms');
}

export async function buildSchedules(request: ScheduleRequest): Promise<ScheduleResponse> {
  const response = await fetch(url('/schedule'), {
    method: 'POST',
    cache: 'no-store',
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail :
      'Check your course codes and time filters, then try again.';
    throw new ApiError(response.status, '/schedule', detail);
  }
  return (await response.json()) as ScheduleResponse;
}

export type CourseOption = {
  code: string;
  dept: string;
  number: string;
  title: string | null;
  sections: number;
  instructors: number;
  with_times: number;
};

/** Courses with sections this term, most choice first. */
export function getCourseOptions(term: string, limit = 200): Promise<CourseOption[]> {
  return get<CourseOption[]>('/schedule/courses', { term, limit });
}

// --- per-student storage ------------------------------------------------------
//
// These take the identity headers from src/lib/session.ts, so they are
// server-only like everything else here.

export type StudentPreferences = {
  wants: string | null;
  weights: Record<string, unknown>;
  engine: string | null;
  /** The courses they are planning around. */
  courses: string[];
  term: string | null;
  updated_at: string | null;
};

export type SavedSchedule = {
  id: number;
  term: string;
  label: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
};

async function send<T>(
  path: string,
  method: string,
  headers: Record<string, string>,
  body?: unknown
): Promise<T> {
  const response = await fetch(url(path), {
    method,
    cache: 'no-store',
    headers: { 'content-type': 'application/json', accept: 'application/json', ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new ApiError(response.status, path, `${response.status}: ${detail}`);
  }
  return (await response.json()) as T;
}

/** What this student asked for last time. Null when they have saved nothing. */
export async function getStudentPreferences(
  headers: Record<string, string>
): Promise<StudentPreferences | null> {
  try {
    return await send<StudentPreferences>('/me/preferences', 'GET', headers);
  } catch (error) {
    // Not signed in, or accounts are not configured: not an error worth
    // breaking a page over.
    if (error instanceof ApiError && [401, 403, 503].includes(error.status)) return null;
    throw error;
  }
}

/**
 * Save part or all of a student's preferences.
 *
 * Partial: the backend keeps what is not mentioned, so saving a course list
 * from the explorer will not erase wants typed on the schedule page.
 */
export function saveStudentPreferences(
  headers: Record<string, string>,
  preferences: {
    wants?: string | null;
    weights?: Record<string, unknown>;
    engine?: string | null;
    courses?: string[];
    term?: string | null;
  }
): Promise<StudentPreferences> {
  return send<StudentPreferences>('/me/preferences', 'PUT', headers, preferences);
}

export function getSavedSchedules(headers: Record<string, string>): Promise<SavedSchedule[]> {
  return send<SavedSchedule[]>('/me/schedules', 'GET', headers);
}

export function saveSchedule(
  headers: Record<string, string>,
  schedule: { term: string; label?: string | null; payload: Record<string, unknown> }
): Promise<SavedSchedule> {
  return send<SavedSchedule>('/me/schedules', 'POST', headers, schedule);
}

// --- the course explorer ------------------------------------------------------

export type CourseProfessor = {
  instructor_id: number | null;
  name: string | null;
  /** The department the grade reports file most of their sections under. */
  department: string | null;
  adj_rating: number | null;
  adj_difficulty: number | null;
  adj_gpa: number | null;
  pct_a: number | null;
  class_reviews: number;
  professor_reviews: number;
  sections: number;
};

export type ExploreCourse = {
  course_id: number;
  code: string;
  dept: string;
  number: string;
  title: string | null;
  credits: string | null;
  honors: boolean;
  prereq_text: string | null;
  /** "Undergraduate" or "Graduate", from the grade reports. */
  level: string | null;
  dept_code: string | null;
  /** Where most of its sections run: A&M teaches the same number at College
   *  Station, Galveston and in Qatar, and a student can attend only one. */
  campus: string | null;
  professor_count: number;
  avg_rating: number | null;
  avg_pct_a: number | null;
  /** Everyone who has taught it, best rated first. */
  professors: CourseProfessor[];
};

export function exploreCourses(q = '', limit = 60): Promise<ExploreCourse[]> {
  return get<ExploreCourse[]>('/courses/explore', { q, limit });
}

/** Whether the backend can reach its database. Used to explain an empty page. */
export async function backendStatus(): Promise<{ ok: boolean; detail: string | null }> {
  if (!BACKEND_URL) {
    return {
      ok: false,
      detail:
        'BACKEND_URL is not set, so there is no API to read from. Point it at the ' +
        'deployed backend (for example https://maroonway-api.onrender.com).',
    };
  }

  // A free instance sleeps after fifteen minutes idle, and while it wakes the
  // host answers 502 *immediately* and keeps doing so for several seconds --
  // measured at three in a row, then healthy at about eight. So a single retry
  // after a short pause still lands on a 502 and reports the backend as down.
  // Keep trying until a deadline instead, which is the difference between a
  // slow first visit and an app that looks broken.
  const deadline = Date.now() + 45000;
  let lastDetail: string | null = null;
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt += 1;
    try {
      const health = await getHealth(AbortSignal.timeout(attempt === 1 ? 6000 : 20000));
      return { ok: health.database === 'ok', detail: health.detail };
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;
      const waking = [502, 503, 504].includes(status);
      lastDetail = waking
        ? `the API is starting up (it answered ${status} for ${Math.round((45000 - (deadline - Date.now())) / 1000)}s). Reload in a moment.`
        : error instanceof Error
          ? error.message
          : String(error);
      // Only a gateway error is worth waiting out; anything else will not fix
      // itself by being asked again.
      if (!waking) break;
      await new Promise((resume) => setTimeout(resume, 3000));
    }
  }
  return { ok: false, detail: lastDetail };
}
