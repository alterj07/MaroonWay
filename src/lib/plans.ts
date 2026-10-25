import type { Plan, Course } from '@/components/planner';
import {
  buildSchedules,
  type CourseOption,
  type Schedule,
  type ScheduleSection,
} from '@/lib/api';

/**
 * Turning built schedules into the shape the planner UI speaks.
 *
 * Shared by the server page (first paint) and the Server Action (when a
 * student presses Build), so both produce identical cards.
 */

/**
 * The priorities a student starts with.
 *
 * Shared by the server's first build and the planner's chips, because they
 * used to disagree: the chips were a client-side default the server had never
 * heard of, so the first schedule was built without them and arrived at 8am
 * under a chip reading "No classes before 9 AM".
 */
export const DEFAULT_PRIORITIES = ['No classes before 9 AM', 'Avoid Friday classes'];

/** Old or incompatible stored snapshots must not crash the saved-list page. */
export function readSavedPlan(value: unknown): Plan | null {
  const object = (v: unknown): v is Record<string, unknown> =>
    v !== null && typeof v === 'object' && !Array.isArray(v);
  const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
  const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every((s) => typeof s === 'string');
  const day = (v: unknown) => number(v) && Number.isInteger(v) && v >= 0 && v <= 6;
  const interval = (start: unknown, end: unknown) =>
    number(start) && number(end) && start >= 0 && start < end && end <= 24;
  if (!object(value) || value.failed || !number(value.id) || !number(value.score) ||
      !['name', 'subtitle', 'rating', 'aRate', 'gap', 'earliest'].every((k) => typeof value[k] === 'string') ||
      !strings(value.tags) || (value.reasons !== undefined && !strings(value.reasons)) ||
      !Array.isArray(value.courses)) return null;
  for (const course of value.courses) {
    if (!object(course) || !['code', 'prof', 'room', 'color'].every((k) => typeof course[k] === 'string') ||
        !number(course.start) || !number(course.end) || !Array.isArray(course.days) || !course.days.every(day) ||
        !['section', 'campus', 'delivery'].every((k) => course[k] == null || typeof course[k] === 'string')) return null;
    if (course.days.length && !interval(course.start, course.end)) return null;
    if (course.meetings !== undefined && (!Array.isArray(course.meetings) ||
        !course.meetings.every((m) => object(m) && day(m.day) && interval(m.start, m.end) && typeof m.room === 'string'))) return null;
  }
  return value as unknown as Plan;
}

/** The planner's day numbering: 0 = Monday. */
const DAY_INDEX: Record<string, number> = { MON: 0, TUE: 1, WED: 2, THU: 3, FRI: 4, SAT: 5, SUN: 6 };
/** One per class, in the order courses are chosen. Five, because a student
 *  taking five classes should not see two of them share a colour. */
const COLORS = ['berry', 'blue', 'green', 'gold', 'purple'];

/** "09:35" -> 9.58, which is how the planner lays blocks out. */
function decimalHours(clock: string) {
  const [h, m] = clock.split(':').map(Number);
  return h + m / 60;
}

function clockLabel(clock: string | null) {
  if (!clock) return '—';
  const [h, m] = clock.split(':').map(Number);
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}:${String(m).padStart(2, '0')} ${h >= 12 ? 'PM' : 'AM'}`;
}

export function toCourse(section: ScheduleSection, index: number): Course {
  const first = section.meetings[0];
  const dept = section.code.replace(/[0-9].*$/, '');
  const number = section.code.slice(dept.length);
  return {
    // The planner splits on the space to get the subject.
    code: `${dept} ${number}`,
    prof: section.instructor_name ?? 'Staff',
    days: [...new Set(section.meetings.map((m) => DAY_INDEX[m.day]))].filter(
      (d) => d !== undefined
    ),
    start: first ? decimalHours(first.start) : 0,
    end: first ? decimalHours(first.end) : 0,
    room: [first?.building, first?.room].filter(Boolean).join(' ') ||
      (section.delivery === 'WEB' && !first ? 'Online' : 'Location TBA'),
    meetings: section.meetings.flatMap((meeting) => {
      const day = DAY_INDEX[meeting.day];
      if (day === undefined) return [];
      return [{
        day,
        start: decimalHours(meeting.start),
        end: decimalHours(meeting.end),
        room: [meeting.building, meeting.room].filter(Boolean).join(' ') || 'Location TBA',
      }];
    }),
    color: COLORS[index % COLORS.length],
    // Carried through for the hover card: a block is a choice of instructor as
    // much as a time, so the numbers behind that choice belong on it.
    section: section.section_code,
    rating: section.adj_rating,
    difficulty: section.adj_difficulty,
    pctA: section.pct_a,
    gpa: section.adj_gpa,
    campus: section.campus,
    delivery: section.delivery,
    honors: section.honors,
    seatsOpen: section.seats_open,
  };
}

export function toPlan(schedule: Schedule, index: number): Plan {
  const reasons = schedule.reasons;
  return {
    id: index + 1,
    name: index === 0 ? 'Best match' : `Option ${index + 1}`,
    subtitle: reasons.length ? reasons.join(' · ') : 'Highest rated professors available',
    score:
      schedule.preference_score > 0
        ? Math.round(schedule.preference_score * 100)
        : Math.round((schedule.mean_rating / 5) * 100),
    rating: schedule.mean_rating.toFixed(1),
    aRate: schedule.mean_pct_a === null ? '—' : `${Math.round(schedule.mean_pct_a * 100)}%`,
    gap: schedule.tightest_gap === null ? 'no clash' : `${schedule.tightest_gap} min`,
    earliest: clockLabel(schedule.earliest_start),
    days: schedule.days_on_campus,
    idle: schedule.idle_minutes,
    tags: reasons.length ? reasons : ['Conflict-free', 'At least 20 minutes between classes'],
    reasons,
    courses: schedule.sections.map(toCourse),
  };
}

/** Shown when there is nothing to build from, so the UI explains itself. */
export function emptyPlan(title: string, detail: string): Plan[] {
  return [
    {
      // Marks this as a failure rather than a schedule, so the planner says so
      // instead of rendering an empty week with dashes for every metric.
      failed: detail,
      id: 1,
      name: title,
      subtitle: detail,
      score: 0,
      rating: '—',
      aRate: '—',
      gap: '—',
      earliest: '—',
      tags: [detail],
      courses: [],
    },
  ];
}

/** Build schedules and map them, or explain why there are none. */
export async function plansFor(
  term: string,
  courses: string[],
  wants?: string | null
): Promise<{ plans: Plan[]; detail: string | null }> {
  if (!courses.length) {
    return { plans: emptyPlan('No classes chosen', 'Add the classes you need'), detail: null };
  }
  const result = await buildSchedules({ term, courses, wants: wants || null, limit: 3 });
  if (!result.schedules.length) {
    const detail = result.detail ?? 'No conflict-free combination exists';
    return { plans: emptyPlan('No schedule fits', detail), detail };
  }
  return { plans: result.schedules.map(toPlan), detail: null };
}

/**
 * Courses whose title says they are arranged individually with a professor
 * rather than taught on a timetable.
 *
 * These dominate a term by section count -- one per student, so MEEN691 runs
 * 121 sections -- and a student picking classes never means them. The number
 * alone does not identify them: 691 is graduate research but 491 is
 * undergraduate research, and both are wrong to propose.
 */
const ARRANGED_TITLE =
  /\b(RESEARCH|THESIS|DISSERTATION|INTERNSHIP|PRACTICUM|DIRECTED STUD|INDEPENDENT STUD|SPECIAL TOPIC|SPECIAL PROBLEM|FIELD (WORK|EXPERIENCE)|STUDY ABROAD|SEMINAR)\b/;

/**
 * Courses to lead with when a student has not chosen any yet.
 *
 * Ordered by how much choice a course offers, but only real taught classes:
 * undergraduate, with meeting times, and not arranged individually.
 */
export function leadCourses(options: CourseOption[], count: number): string[] {
  return options
    .filter((option) => option.with_times > 0 && isTaughtClass(option))
    .slice(0, count)
    .map((option) => option.code);
}

/** Whether this is a class a student sits in, rather than arranged work. */
export function isTaughtClass(option: CourseOption): boolean {
  const number = Number.parseInt(option.code.replace(/^[A-Z]+/, ''), 10);
  if (!Number.isFinite(number) || number >= 500) return false;
  return !ARRANGED_TITLE.test((option.title ?? '').toUpperCase());
}
