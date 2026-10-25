import type { Metadata } from 'next';
import { connection } from 'next/server';

import { Card } from '@/components/card';
import { SignIn } from '@/components/sign-in';
import { Text } from '@/components/text';
import {
  buildSchedules,
  getStudentPreferences,
  getTerms,
  saveStudentPreferences,
  type Preferences,
  type Schedule,
  type ScheduleSection,
} from '@/lib/api';
import { currentStudent, studentHeaders } from '@/lib/session';

export const metadata: Metadata = { title: 'Schedule' };

const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI'] as const;
const GRID_START = 8 * 60;
const GRID_END = 18 * 60;
const COLORS = ['bg-primary', 'bg-maroon', 'bg-primary/70', 'bg-maroon/70'];

function minutes(clock: string) {
  const [h, m] = clock.split(':').map(Number);
  return h * 60 + m;
}

/** The form. A plain GET form, so it works without client JavaScript. */
function Ask({ courses, wants, term }: { courses: string; wants: string; term?: string }) {
  return (
    <form method="get" className="flex flex-col gap-3 rounded-card border border-line bg-surface p-6">
      {term ? <input type="hidden" name="term" value={term} /> : null}
      <label className="flex flex-col gap-1">
        <Text variant="eyebrow" muted>
          Classes you need
        </Text>
        <input
          name="courses"
          defaultValue={courses}
          placeholder="BIOL100, CHEM107, ANTH205"
          className="rounded-md border border-line bg-background px-3 py-2 text-base"
        />
      </label>
      <label className="flex flex-col gap-1">
        <Text variant="eyebrow" muted>
          What do you want out of the semester?
        </Text>
        <textarea
          name="wants"
          rows={2}
          defaultValue={wants}
          placeholder="easy A's with good lecturers, nothing before 10am, no Friday classes"
          className="rounded-md border border-line bg-background px-3 py-2 text-base"
        />
      </label>
      <button
        type="submit"
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white">
        Build schedules
      </button>
    </form>
  );
}

/** What the decision model made of the student's words. */
function Understood({ preferences }: { preferences: Preferences }) {
  const weights: [string, number][] = [
    ['Professor rating', preferences.rating],
    ['Easier classes', preferences.difficulty],
    ['Grade distribution', preferences.grades],
    ['Light workload', preferences.workload],
    ['Good lecturers', preferences.lecture],
    ['Attendance not taken', preferences.attendance],
    ['No early mornings', preferences.avoid_early_mornings],
    ['No Friday classes', preferences.avoid_fridays],
  ];
  const stated = weights.filter(([, weight]) => weight > 0);
  const engineLabel =
    preferences.engine === 'default'
      ? 'ranked by RateMyProfessors score, then difficulty'
      : `decided by ${preferences.engine}`;

  return (
    <Card title="What we understood" description={engineLabel}>
      <div className="flex flex-col gap-1">
        {stated.length === 0 ? (
          <Text variant="caption" muted>
            Nothing stated, so the default ranking applies.
          </Text>
        ) : (
          stated.map(([label, weight]) => (
            <div key={label} className="flex items-center gap-2">
              <Text variant="caption" className="w-44 shrink-0">
                {label}
              </Text>
              <div className="h-1.5 w-40 overflow-hidden rounded-full bg-line">
                <div className="h-full rounded-full bg-primary" style={{ width: `${weight * 100}%` }} />
              </div>
              <Text variant="caption" muted>
                {Math.round(weight * 100)}%
              </Text>
            </div>
          ))
        )}
      </div>
      <Text variant="caption" muted>
        At least {preferences.min_gap_minutes} minutes between classes
        {preferences.delivery ? ` · prefers ${preferences.delivery === 'WEB' ? 'online' : 'in person'}` : ''}
        {preferences.engine === 'heuristic'
          ? ' · keyword fallback, not a calibrated decision — set TYPESAFE_API_KEY for Jev'
          : ''}
      </Text>
    </Card>
  );
}

function Week({ schedule }: { schedule: Schedule }) {
  const span = GRID_END - GRID_START;
  return (
    <div className="flex gap-2">
      {DAYS.map((day) => (
        <div key={day} className="flex-1">
          <Text muted className="mb-1 text-center text-sm font-semibold">
            {day}
          </Text>
          <div className="relative h-64 rounded-md border border-line bg-background">
            {schedule.sections.flatMap((section, index) =>
              section.meetings
                .filter((meeting) => meeting.day === day)
                .map((meeting) => {
                  const top = ((minutes(meeting.start) - GRID_START) / span) * 100;
                  const height = ((minutes(meeting.end) - minutes(meeting.start)) / span) * 100;
                  return (
                    <div
                      key={`${section.section_id}-${meeting.day}`}
                      className={`absolute inset-x-1 overflow-hidden rounded px-1 py-0.5 text-xs leading-tight text-white ${COLORS[index % COLORS.length]}`}
                      style={{ top: `${top}%`, height: `${Math.max(height, 7)}%` }}
                      title={`${section.code} · ${section.instructor_name ?? 'staff'} · ${meeting.start}–${meeting.end}`}>
                      <span className="font-semibold">{section.code}</span>
                      <br />
                      {meeting.start}
                    </div>
                  );
                })
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function SectionRow({ section }: { section: ScheduleSection }) {
  const days = [...new Set(section.meetings.map((m) => m.day[0]))].join('');
  const when = section.meetings.length
    ? `${days} ${section.meetings[0].start}–${section.meetings[0].end}`
    : 'online';
  const where = section.meetings[0]
    ? [section.meetings[0].building, section.meetings[0].room].filter(Boolean).join(' ')
    : '';
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-line py-2 first:border-t-0">
      <div>
        <Text as="span" className="font-semibold">
          {section.code}
        </Text>{' '}
        <Text as="span" muted className="text-sm">
          sec {section.section_code} · {section.instructor_name ?? 'staff'}
        </Text>
      </div>
      <Text as="span" muted className="text-sm">
        {when} {where} ·{' '}
        {section.adj_rating === null ? 'unrated' : `rating ${section.adj_rating.toFixed(2)}`}
        {section.adj_difficulty === null ? '' : ` · difficulty ${section.adj_difficulty.toFixed(2)}`}
      </Text>
    </div>
  );
}

export default async function SchedulePage({
  searchParams,
}: {
  searchParams: Promise<{ courses?: string; term?: string; wants?: string; gap?: string }>;
}) {
  await connection();
  const params = await searchParams;

  const terms = await getTerms().catch(() => []);
  const term = params.term ?? terms[0]?.term;
  const rawCourses = params.courses ?? 'BIOL100, CHEM107, ANTH205';
  const courses = rawCourses
    .split(',')
    .map((c) => c.trim().toUpperCase().replace(/\s+/g, ''))
    .filter(Boolean);

  // A signed-in student's saved wants prefill the form, so they do not retype
  // them. Anything in the query string wins, since that is this visit's intent.
  const student = await currentStudent();
  const headers = student ? studentHeaders(student) : null;
  const saved = headers ? await getStudentPreferences(headers).catch(() => null) : null;
  const wants = params.wants ?? saved?.wants ?? '';

  const result =
    term && courses.length
      ? await buildSchedules({
          term,
          courses,
          wants: wants || null,
          min_gap_minutes: params.gap ? Number(params.gap) : undefined,
          limit: 4,
        }).catch((error) => ({
          count: 0,
          schedules: [],
          detail: String(error),
          request: { term, courses },
          preferences: null as Preferences | null,
        }))
      : null;

  // Remember what they asked for this time, for the next visit.
  if (headers && params.wants && result?.preferences) {
    await saveStudentPreferences(headers, {
      wants: params.wants,
      weights: result.preferences as unknown as Record<string, unknown>,
      engine: result.preferences.engine,
    }).catch(() => undefined);
  }

  return (
    <main className="mx-auto flex w-full max-w-page flex-col gap-6 px-6 py-10">
      <section className="flex flex-col gap-2">
        <Text variant="eyebrow" className="text-primary">
          Schedule builder
        </Text>
        <Text variant="title">Tell us what you want</Text>
        <Text muted>
          {term ? `${term} · ` : ''}conflict-free schedules with at least 20 minutes between
          classes, ranked by your preferences.
        </Text>
        {terms.length === 0 ? (
          <Text muted variant="caption">
            No terms have sections loaded yet — run{' '}
            <code>python -m app.ingest.load_sections &lt;file&gt;</code>.
          </Text>
        ) : null}
      </section>

      <SignIn />

      <Ask courses={rawCourses} wants={wants} term={params.term} />

      {result?.preferences ? <Understood preferences={result.preferences} /> : null}

      {result && result.count > 0 ? (
        result.schedules.map((schedule, index) => (
          <Card key={index} className="gap-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Text variant="subheading">
                {index === 0 ? 'Best match' : `Option ${index + 1}`}
                {schedule.reasons.length ? (
                  <Text as="span" muted variant="caption">
                    {' '}
                    — {schedule.reasons.join(', ')}
                  </Text>
                ) : null}
              </Text>
              <Text muted className="text-sm">
                {schedule.preference_score > 0
                  ? `${Math.round(schedule.preference_score * 100)}% match · `
                  : ''}
                rating {schedule.mean_rating.toFixed(2)} · difficulty{' '}
                {schedule.mean_difficulty.toFixed(2)}
                {schedule.tightest_gap === null
                  ? ''
                  : ` · tightest gap ${schedule.tightest_gap} min`}
                {schedule.earliest_start ? ` · starts ${schedule.earliest_start}` : ''}
              </Text>
            </div>
            <Week schedule={schedule} />
            <div>
              {schedule.sections.map((section) => (
                <SectionRow key={section.section_id} section={section} />
              ))}
            </div>
          </Card>
        ))
      ) : (
        <Card
          title="No schedule fits"
          description={result?.detail ?? 'Add some classes above to get started.'}
        />
      )}
    </main>
  );
}
