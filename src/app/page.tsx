import {
  buildSchedules,
  getCourseOptions,
  getTerms,
  type Schedule,
  type ScheduleSection,
} from '@/lib/api';
import { Planner, type Course, type Plan } from '@/components/planner';

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

function toCourse(section: ScheduleSection, index: number): Course {
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

function toPlan(schedule: Schedule, index: number): Plan {
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
    aRate:
      schedule.mean_pct_a === null ? '—' : `${Math.round(schedule.mean_pct_a * 100)}%`,
    gap: schedule.tightest_gap === null ? 'no clash' : `${schedule.tightest_gap} min`,
    earliest: clockLabel(schedule.earliest_start),
    tags: reasons.length ? reasons : ['Conflict-free', 'At least 20 minutes between classes'],
    courses: schedule.sections.map(toCourse),
  };
}

/** Shown when the backend has no sections loaded, so the page still explains itself. */
const EMPTY: Plan[] = [
  {
    id: 1,
    name: 'No sections loaded',
    subtitle: 'Load a term to see real schedules',
    score: 0,
    rating: '—',
    aRate: '—',
    gap: '—',
    earliest: '—',
    tags: ['Run python -m app.ingest.load_sections <file>'],
    courses: [],
  },
];

export default async function Home() {
  // Real schedules, built from whatever term is loaded. The planner was
  // previously driven by a hardcoded array; it now gets this.
  const plans = await (async (): Promise<Plan[]> => {
    const terms = await getTerms();
    const term = terms.find((t) => t.with_times > 0)?.term ?? terms[0]?.term;
    if (!term) return EMPTY;

    const options = await getCourseOptions(term, 40);
    const courses = options
      .filter((option) => option.with_times > 0)
      .slice(0, 4)
      .map((option) => option.code);
    if (courses.length === 0) return EMPTY;

    const result = await buildSchedules({ term, courses, limit: 3 });
    return result.schedules.length ? result.schedules.map(toPlan) : EMPTY;
  })().catch(() => EMPTY);

  return <Planner plans={plans} />;
}
