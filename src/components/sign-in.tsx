import { Text } from '@/components/text';
import { currentStudent } from '@/lib/session';

/**
 * Sign in with a Texas A&M Google account.
 *
 * Deliberately explicit about what this does and does not do: students will
 * reasonably assume a tamu.edu login reaches their Howdy schedule, and it does
 * not — Howdy is a NetID/CAS login with Duo. This only remembers their
 * preferences.
 */
export async function SignIn() {
  const student = await currentStudent();

  if (!student) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-line bg-surface px-4 py-3">
        <Text variant="caption" muted>
          Sign in with your <strong>@tamu.edu</strong> Google account to save what you want.
          This is not your Howdy login and cannot see your registration.
        </Text>
        {/* A real <a>, not <Link>: NextAuth's routes return HTML pages, and a
            client-side navigation to them would try to fetch an RSC payload. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a
          href="/api/auth/signin?callbackUrl=/schedule"
          className="shrink-0 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white">
          Sign in
        </a>
      </div>
    );
  }

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
