'use server';

import { revalidatePath } from 'next/cache';

import { ApiError, getCourseSections, getTerms, saveSchedule, saveStudentPreferences } from '@/lib/api';
import type { SectionLock } from '@/lib/api';
import type { Plan } from '@/components/planner';
import { emptyPlan, normalizeCourseCodes, plansFor } from '@/lib/plans';
import { currentStudent, studentHeaders } from '@/lib/session';

/**
 * Server Actions for the client components.
 *
 * These exist so the planner and explorer — which are client components — can
 * save to the account without the identity headers ever reaching the browser.
 * Each is a no-op when nobody is signed in, so the UI works either way.
 */

export async function saveCourses(courses: string[], term?: string | null) {
  const student = await currentStudent();
  if (!student) return { saved: false, reason: 'not signed in' as const };

  await saveStudentPreferences(studentHeaders(student), {
    courses,
    term: term ?? null,
  });
  revalidatePath('/');
  return { saved: true as const };
}

export async function saveWants(wants: string) {
  const student = await currentStudent();
  if (!student) return { saved: false, reason: 'not signed in' as const };

  await saveStudentPreferences(studentHeaders(student), { wants });
  revalidatePath('/');
  revalidatePath('/schedule');
  return { saved: true as const };
}


/**
 * Build schedules for the courses and wants a student entered.
 *
 * The landing page used to fake this with a 1.9-second timer and throw the
 * entered courses away. This runs the real thing, and saves what they asked
 * for when they are signed in.
 */
export async function buildPlans(
  courses: string[],
  wants: string,
  term?: string | null,
  // Pinned by hand in the course panel. These are hard filters, so they go to
  // the API untouched rather than being folded into the wants text, where
  // they would become one more thing to infer and get wrong.
  locks?: Record<string, SectionLock>
  // `relaxed` travels with the plans: a preference the timetable could not
  // honour is part of the answer, and dropping it leaves a student reading a
  // schedule that quietly disobeys them.
): Promise<{ plans: Plan[]; relaxed: string[]; pinned: string[] }> {
  const terms = await getTerms().catch(() => []);
  const chosen = term ?? terms.find((t) => t.with_times > 0)?.term ?? terms[0]?.term;
  if (!chosen) {
    return {
      plans: emptyPlan('No term loaded', 'Load a term with section times first'),
      relaxed: [],
      pinned: [],
    };
  }

  const codes = normalizeCourseCodes(courses);
  if (codes.length > 10) {
    return {
      plans: emptyPlan('Too many classes', 'Choose up to 10 classes at a time'),
      relaxed: [],
      pinned: [],
    };
  }

  const student = await currentStudent();
  if (student) {
    await saveStudentPreferences(studentHeaders(student), {
      courses: codes,
      term: chosen,
      wants: wants.trim(),
    }).catch(() => undefined);
  }

  try {
    const result = await plansFor(chosen, codes, wants, locks);
    return {
      plans: result.plans,
      relaxed: result.relaxed ?? [],
      pinned: result.pinned ?? [],
    };
  } catch (error) {
    return {
      plans: emptyPlan('Could not build schedules', error instanceof ApiError
        ? error.message : 'The schedule service is unavailable. Please try again.'),
      relaxed: [],
      pinned: [],
    };
  }
}

/**
 * Keep a built schedule against the student's account.
 *
 * What the "Use this schedule" button does: the backend already stores saved
 * schedules, and nothing was calling it, so the button looked like it worked
 * and lost the schedule the moment the page reloaded.
 */
export async function useSchedule(term: string, label: string, payload: Plan) {
  const student = await currentStudent();
  if (!student) return { saved: false, reason: 'not signed in' as const };

  const schedule = await saveSchedule(studentHeaders(student), {
    term,
    label,
    // The plan as the UI holds it, so a saved schedule can be shown again
    // without rebuilding it against data that may have moved on.
    payload: payload as unknown as Record<string, unknown>,
  });
  revalidatePath('/');
  return { saved: true as const, schedule };
}


/**
 * The sections of one course, for the panel that pins one by hand.
 *
 * A Server Action rather than a fetch from the browser, for the same reason
 * as the rest of this file: BACKEND_URL and its tokens stay on the server.
 * Failure is an empty list -- the panel's other controls still work without
 * it, and a thrown error would take the whole planner down with it.
 */
export async function courseSections(term: string, code: string) {
  try {
    return await getCourseSections(term, code);
  } catch {
    return [];
  }
}
