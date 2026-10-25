import { Text } from '@/components/text';
import { currentStudent } from '@/lib/session';

/**
 * Who you are signed in as, and the way out.
 *
 * The sign-*in* half lives on the gate (`components/welcome.tsx`), which every
 * route redirects to while signed out, so this only ever renders for a student
 * who is already through it.
 */
export async function SignIn() {
  const student = await currentStudent();

  // Signed out is the gate's job now, and a second sign-in button here would
  // undercut having a single way in.
  if (!student) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-surface px-4 py-3">
      <Text variant="caption" muted>
        Signed in as <strong>{student.email}</strong>
      </Text>
      {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
      <a
        href="/api/auth/signout?callbackUrl=/schedule"
        className="shrink-0 rounded-md border border-line px-3 py-1.5 text-sm font-semibold">
        Sign out
      </a>
    </div>
  );
}
