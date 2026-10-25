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

const BACKEND_URL = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000';

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

async function get<T>(path: string, query?: Query): Promise<T> {
  const target = url(path, query);
  const response = await fetch(target, {
    cache: 'no-store',
    headers: { accept: 'application/json' },
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => '');
    throw new ApiError(response.status, path, `${response.status} from ${path}: ${detail}`);
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

export function getHealth(): Promise<Health> {
  return get<Health>('/healthz');
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
};

export type Schedule = {
  sections: ScheduleSection[];
  tightest_gap: number | null;
  mean_rating: number;
  mean_difficulty: number;
  mean_gpa: number | null;
  earliest_start: string | null;
  days_on_campus: number;
};

export type ScheduleRequest = {
  term: string;
  courses: string[];
  min_gap_minutes?: number;
  earliest?: string;
  latest?: string;
  excluded_days?: string[];
  campus?: string;
  honors?: boolean;
  delivery?: string;
  open_only?: boolean;
  limit?: number;
};

export type ScheduleResponse = {
  request: ScheduleRequest;
  count: number;
  schedules: Schedule[];
  /** Set when nothing could be built — says which constraint bit. */
  detail: string | null;
};

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
    const detail = await response.text().catch(() => '');
    throw new ApiError(response.status, '/schedule', `${response.status}: ${detail}`);
  }
  return (await response.json()) as ScheduleResponse;
}
