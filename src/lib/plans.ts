import type { Plan, Course } from '@/components/planner';
import { buildSchedules, type Schedule, type ScheduleSection } from '@/lib/api';

/**
 * Turning built schedules into the shape the planner UI speaks.
 *
 * Shared by the server page (first paint) and the Server Action (when a
 * student presses Build), so both produce identical cards.
 */

/** The planner's day numbering: 0 = Monday. */
const DAY_INDEX: Record<string, number> = { MON: 0, TUE: 1, WED: 2, THU: 3, FRI: 4 };
const COLORS = ['berry', 'blue', 'gold', 'green'];

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
    room: [first?.building, first?.room].filter(Boolean).join(' ') || 'Online',
    color: COLORS[index % COLORS.length],
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
    tags: reasons.length ? reasons : ['Conflict-free', 'At least 20 minutes between classes'],
    courses: schedule.sections.map(toCourse),
  };
}

/** Shown when there is nothing to build from, so the UI explains itself. */
export function emptyPlan(title: string, detail: string): Plan[] {
  return [
    {
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
