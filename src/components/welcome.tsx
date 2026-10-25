import { CalendarDays, Clock3, GraduationCap, Star } from 'lucide-react';

import { GoogleButton } from '@/components/google-button';

/**
 * The gate.
 *
 * Nothing in MaroonWay is useful anonymously -- a schedule is built from a
 * student's own courses and saved against their account -- so signing in comes
 * first rather than being offered later and losing whatever they typed.
 *
 * Deliberately the only page that needs no backend: a student arriving while
 * the API is asleep still gets a working screen instead of an error, which
 * matters on a free host that spins down when idle.
 */
/** What NextAuth's `?error=` codes actually mean to a student. */
const SIGN_IN_ERRORS: Record<string, string> = {
  OAuthCallback:
    'That sign-in attempt expired before it finished. Try again — this usually works on the second go.',
  OAuthSignin: 'Google could not be reached. Try again in a moment.',
  AccessDenied:
    'That account is not a tamu.edu account. Sign in with your Texas A&M Google account.',
  Verification: 'That sign-in link has already been used. Start again below.',
  Configuration:
    'Sign-in is not configured on this server yet. If this is your deployment, check NEXTAUTH_SECRET and the Google credentials.',
};

export function Welcome({ error }: { error?: string }) {
  const problem = error
    ? (SIGN_IN_ERRORS[error] ?? 'Something went wrong signing in. Try again below.')
    : null;

  return (
    <main className="gate">
      <div className="gate-inner">
        <section className="gate-copy">
          <a className="gate-brand">
            <span>
              <CalendarDays size={18} />
            </span>
            <b>MaroonWay</b>
          </a>

          <h1>Build a better schedule.</h1>
          <p>
            Sign in with your Texas A&amp;M Google account to pick your classes,
            tell us what a good week looks like, and get schedules ranked by the
            professors and grade data behind them.
          </p>

          {problem ? (
            <p className="gate-error" role="alert">
              {problem}
            </p>
          ) : null}

          <GoogleButton callbackUrl="/" />

          <small className="gate-note">
            Your <strong>@tamu.edu</strong> account only. This is not your Howdy
            login &mdash; it cannot see your registration, and it is used to
            remember your courses and preferences.
          </small>
        </section>

        <section className="gate-preview" aria-hidden="true">
          <SchedulePreview />
        </section>
      </div>
    </main>
  );
}

/**
 * A still of the product, the way the reference layout shows one.
 *
 * Fixed content on purpose: it illustrates the shape of the result before a
 * student has an account, and loading real courses here would mean waiting on
 * the API for a screen whose whole point is that it does not need it.
 */
function SchedulePreview() {
  const blocks = [
    { day: 0, label: 'ENGL 104', time: '9:10', tone: 'a', top: 0, span: 2 },
    { day: 1, label: 'KINE 223', time: '10:05', tone: 'b', top: 1, span: 2 },
    { day: 2, label: 'ENGL 104', time: '9:10', tone: 'a', top: 0, span: 2 },
    { day: 3, label: 'KINE 223', time: '10:05', tone: 'b', top: 1, span: 2 },
    { day: 2, label: 'ENGL 203', time: '12:45', tone: 'c', top: 4, span: 2 },
  ];

  return (
    <div className="gate-card">
      <header>
        <span>
          <i />
          YOUR BEST FIT
        </span>
        <em>84% match</em>
      </header>

      <div className="gate-week">
        {['M', 'T', 'W', 'R', 'F'].map((day) => (
          <b key={day}>{day}</b>
        ))}
        {[0, 1, 2, 3, 4].map((day) => (
          <div className="gate-col" key={day}>
            {blocks
              .filter((block) => block.day === day)
              .map((block) => (
                <span
                  className={`gate-block t-${block.tone}`}
                  key={`${block.day}-${block.label}`}
                  style={{
                    top: `${block.top * 17}%`,
                    height: `${block.span * 17}%`,
                  }}>
                  <b>{block.label}</b>
                  <small>{block.time}</small>
                </span>
              ))}
          </div>
        ))}
      </div>

      <footer>
        <span>
          <Star size={12} /> 4.6 professors
        </span>
        <span>
          <GraduationCap size={12} /> 64% A rate
        </span>
        <span>
          <Clock3 size={12} /> 55 min gap
        </span>
      </footer>
    </div>
  );
}
