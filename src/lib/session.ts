import { getServerSession } from 'next-auth';

import { authOptions } from '@/lib/auth';

export type Student = { subject: string; email: string; name: string | null };

/**
 * The signed-in student, or null.
 *
 * Read on the server only. The subject and email are what identify a student
 * to the backend; nothing from Google is forwarded beyond those and a display
 * name.
 */
export async function currentStudent(): Promise<Student | null> {
  const session = await getServerSession(authOptions);
  const user = session?.user as { subject?: string; email?: string; name?: string } | undefined;
  if (!user?.subject || !user.email) return null;
  return { subject: user.subject, email: user.email, name: user.name ?? null };
}

/**
 * Headers that let the backend trust this request's identity.
 *
 * The backend has no way to verify a Google session itself, so it trusts these
 * only when INTERNAL_TOKEN matches — which is why this must never be called
 * from client code.
 */
export function studentHeaders(student: Student): Record<string, string> {
  return {
    'x-internal-token': process.env.INTERNAL_TOKEN ?? '',
    'x-student-subject': student.subject,
    'x-student-email': student.email,
    ...(student.name ? { 'x-student-name': student.name } : {}),
  };
}
