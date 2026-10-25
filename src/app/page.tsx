import { buildPlans, saveCourses, useSchedule } from '@/app/actions';
import { Planner, type Plan } from '@/components/planner';
import { Welcome } from '@/components/welcome';
import {
  backendStatus,
  exploreCourses,
  getCourseOptions,
  getStudentPreferences,
  getTerms,
} from '@/lib/api';
import { DEFAULT_PRIORITIES, emptyPlan, leadCourses, plansFor } from '@/lib/plans';
import { currentStudent, studentHeaders } from '@/lib/session';

/**
 * The first paint.
 *
 * Everything the planner shows comes from here: the course catalogue with its
 * instructors, the signed-in student, what they saved last time, and a first
 * set of schedules. Pressing Build calls the buildPlans action instead, so the
 * courses and wants a student actually enters are the ones used.
 *
 * When the backend cannot be reached the plan card says so in as many words,
 * rather than claiming no schedule fits — which is a different problem with a
 * different fix.
 */
export default async function Home({
  searchParams,
}: {
  // A Promise in this version of Next; `error` arrives here when NextAuth
  // bounces a failed sign-in back to the gate.
  searchParams: Promise<{ error?: string }>;
}) {
  const student = await currentStudent();

  // The gate comes first, and before the backend is touched. Everything here
  // is per-student, so there is nothing to show an anonymous visitor -- and
  // asking the API for a catalogue nobody will see would make a signed-out
  // visitor wait on a cold start for a screen that needs no data.
  if (!student) return <Welcome error={(await searchParams).error} />;

  const status = await backendStatus();

  if (!status.ok) {
    return (
      <Planner
        plans={emptyPlan(
          'Backend unavailable',
          status.detail
            ? `The API could not reach its database: ${status.detail.slice(0, 160)}`
            : 'The API is not reachable. Start it, and set DATABASE_URL.'
        )}
        courses={[]}
        student={student}
        savedCourses={[]}
        savedWants=""
        onSaveCourses={saveCourses}
        onBuildPlans={buildPlans}
        terms={[]}
        onUseSchedule={useSchedule}
      />
    );
  }

  const headers = student ? studentHeaders(student) : null;
  const [courses, terms, saved] = await Promise.all([
    exploreCourses('', 200).catch(() => []),
    getTerms().catch(() => []),
    headers ? getStudentPreferences(headers).catch(() => null) : Promise.resolve(null),
  ]);

  const term = saved?.term ?? terms.find((t) => t.with_times > 0)?.term ?? terms[0]?.term;

  // A signed-in student's own courses come first; otherwise lead with courses
  // that actually have sections this term, so the first paint is not empty.
  let chosen = saved?.courses ?? [];
  if (!chosen.length && term) {
    const options = await getCourseOptions(term, 120).catch(() => []);
    chosen = leadCourses(options, 4);
  }

  let plans: Plan[];
  if (!term) {
    plans = emptyPlan('No sections loaded', 'Import a term with meeting times to build schedules');
  } else {
    // The same priorities the planner shows as chips, so the first schedule is
    // built against what the student can actually see.
    plans = (await plansFor(
      term,
      chosen,
      saved?.wants || DEFAULT_PRIORITIES.join(', ')
    ).catch(() => ({
      plans: emptyPlan('Could not build schedules', 'The backend returned an error'),
    }))).plans;
  }

  return (
    <Planner
      plans={plans}
      courses={courses}
      student={student}
      savedCourses={chosen}
      savedWants={saved?.wants ?? ''}
      onSaveCourses={saveCourses}
      onBuildPlans={buildPlans}
      terms={terms.map((t) => t.term)}
      onUseSchedule={useSchedule}
    />
  );
}
