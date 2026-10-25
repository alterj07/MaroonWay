'use server';

import { revalidatePath } from 'next/cache';

import { getTerms, saveSchedule, saveStudentPreferences } from '@/lib/api';
import type { Plan } from '@/components/planner';
import { emptyPlan, plansFor } from '@/lib/plans';
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
  term?: string | null
): Promise<Plan[]> {
  const terms = await getTerms().catch(() => []);
  const chosen = term ?? terms.find((t) => t.with_times > 0)?.term ?? terms[0]?.term;
  if (!chosen) {
    return emptyPlan('No term loaded', 'Load a term with section times first');
  }

  const codes = courses
    .map((code) => code.trim().toUpperCase().replace(/\s+/g, ''))
    .filter(Boolean);

  const student = await currentStudent();
  if (student) {
    await saveStudentPreferences(studentHeaders(student), {
      courses: codes,
      term: chosen,
      ...(wants.trim() ? { wants } : {}),
    }).catch(() => undefined);
  }

  try {
    return (await plansFor(chosen, codes, wants)).plans;
  } catch (error) {
    return emptyPlan('Could not reach the backend', String(error));
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

  await saveSchedule(studentHeaders(student), {
    term,
    label,
    // The plan as the UI holds it, so a saved schedule can be shown again
    // without rebuilding it against data that may have moved on.
    payload: payload as unknown as Record<string, unknown>,
  });
  revalidatePath('/');
  return { saved: true as const };
}
