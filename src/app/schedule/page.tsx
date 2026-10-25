import type { Metadata } from 'next';
import { connection } from 'next/server';

import { Card } from '@/components/card';
import { Text } from '@/components/text';
import { buildSchedules, getTerms, type Schedule, type ScheduleSection } from '@/lib/api';

export const metadata: Metadata = { title: 'Schedule' };

const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI'] as const;

/** Minutes since midnight, for laying a meeting out on the grid. */
function minutes(clock: string) {
  const [h, m] = clock.split(':').map(Number);
  return h * 60 + m;
}

const GRID_START = 8 * 60;
const GRID_END = 18 * 60;
const COLORS = ['bg-primary', 'bg-maroon'];

function Week({ schedule }: { schedule: Schedule }) {
  const span = GRID_END - GRID_START;
  return (
    <div className="flex gap-2">
      {DAYS.map((day) => (
        <div key={day} className="flex-1">
          <Text variant="caption" muted className="mb-1 text-center">
            {day}
          </Text>
          <div className="relative h-72 rounded-md border border-line bg-background">
            {schedule.sections.flatMap((section, index) =>
              section.meetings
                .filter((meeting) => meeting.day === day)
                .map((meeting) => {
                  const top = ((minutes(meeting.start) - GRID_START) / span) * 100;
                  const height = ((minutes(meeting.end) - minutes(meeting.start)) / span) * 100;
                  return (
                    <div
                      key={`${section.section_id}-${meeting.day}`}
                      className={`absolute inset-x-1 overflow-hidden rounded px-1 py-0.5 text-[0.625rem] leading-tight text-white ${COLORS[index % COLORS.length]}`}
                      style={{ top: `${top}%`, height: `${Math.max(height, 6)}%` }}
                      title={`${section.code} ${meeting.start}-${meeting.end}`}>
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
  const when = section.meetings.length
    ? `${[...new Set(section.meetings.map((m) => m.day))].join('')} ${section.meetings[0].start}–${section.meetings[0].end}`
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
        <Text as="span" muted variant="caption">
          sec {section.section_code} · {section.instructor_name ?? 'staff'}
        </Text>
      </div>
      <Text as="span" variant="caption" muted>
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
  searchParams: Promise<{ courses?: string; term?: string; gap?: string }>;
}) {
  await connection();
  const params = await searchParams;

  const terms = await getTerms().catch(() => []);
  const term = params.term ?? terms[0]?.term;
  const courses = (params.courses ?? 'ACCT229,ACCT230,ACCT327')
    .split(',')
    .map((c) => c.trim().toUpperCase())
    .filter(Boolean);
  const minGap = Number(params.gap ?? 20);

  const result = term
    ? await buildSchedules({ term, courses, min_gap_minutes: minGap, limit: 5 }).catch((error) => ({
        count: 0,
        schedules: [],
        detail: String(error),
        request: { term, courses },
      }))
    : null;

  return (
    <main className="mx-auto flex w-full max-w-page flex-col gap-8 px-6 py-10">
      <section className="flex flex-col gap-2">
        <Text variant="eyebrow" className="text-primary">
          Schedule builder
        </Text>
        <Text variant="title">{courses.join(' · ')}</Text>
        <Text muted>
          {term ? `${term} · ` : ''}at least {minGap} minutes between classes · ranked by
          RateMyProfessors score, then difficulty
        </Text>
        {terms.length === 0 ? (
          <Text muted variant="caption">
            No terms have sections loaded. Run{' '}
            <code>python -m app.ingest.load_sections &lt;file&gt;</code>.
          </Text>
        ) : null}
      </section>

      {result && result.count > 0 ? (
        result.schedules.map((schedule, index) => (
          <Card key={index} className="gap-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <Text variant="subheading">
                Option {index + 1}
                {index === 0 ? ' — best match' : ''}
              </Text>
              <Text variant="caption" muted>
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
          description={result?.detail ?? 'Pick some courses to get started.'}
        />
      )}
    </main>
  );
}
