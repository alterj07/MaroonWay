import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { connection } from 'next/server';

import { ProfessorReviews } from '@/components/professor-reviews';
import { Card } from '@/components/card';
import { Text } from '@/components/text';
import { getProfessor } from '@/lib/api';

export const metadata: Metadata = { title: 'Professor' };

/** Keeps the 1-5 scores readable without a chart. */
function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <Text variant="eyebrow" muted>
        {label}
      </Text>
      <Text variant="heading">{value}</Text>
      {hint ? (
        <Text variant="caption" muted>
          {hint}
        </Text>
      ) : null}
    </div>
  );
}

const fixed = (value: number | null, digits = 2) =>
  value === null ? '—' : value.toFixed(digits);

export default async function ProfessorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const instructorId = Number(id);
  if (!Number.isInteger(instructorId) || instructorId < 1) notFound();

  // Stops this page being prerendered at build time, when the backend is not
  // running. The backend's own hot cache is what makes the request fast.
  await connection();
  const professor = await getProfessor(instructorId);
  if (!professor) notFound();

  const { score } = professor;
  const instructorSummary = professor.summaries.find((s) => s.subject_type === 'instructor');

  return (
    // The root layout renders a bare <body>, so this page carries its own
    // centred column.
    <main className="mx-auto flex w-full max-w-page flex-col gap-10 px-6 py-10">
      <section className="flex flex-col gap-2">
        <Text variant="eyebrow" className="text-primary">
          {professor.department ?? 'Department unknown'}
        </Text>
        <Text variant="title">{professor.full_name}</Text>
        <Text muted>
          {score.rating_count > 0
            ? `${score.rating_count} RateMyProfessors ratings`
            : 'No RateMyProfessors ratings yet'}
          {professor.grades.length > 0 ? ` · ${professor.grades.length} graded sections` : ''}
        </Text>
      </section>

      <section className="flex flex-wrap gap-4 *:grow *:basis-45">
        <Card>
          <Stat
            label="Rating"
            value={fixed(score.adj_rating)}
            hint={`raw ${fixed(score.raw_rating)} · weighted by ${score.rating_count} reviews`}
          />
        </Card>
        <Card>
          <Stat
            label="Difficulty"
            value={fixed(score.adj_difficulty)}
            hint={`raw ${fixed(score.raw_difficulty)}`}
          />
        </Card>
        <Card>
          <Stat
            label="Would take again"
            value={
              score.would_take_again_percent === null
                ? '—'
                : `${Math.round(score.would_take_again_percent)}%`
            }
            hint={score.would_take_again_percent === null ? 'nobody answered' : undefined}
          />
        </Card>
        <Card>
          <Stat label="Grade score (0-5)" value={fixed(score.adj_gpa)} hint="normalized from A&M GPA" />
        </Card>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">What students say</Text>
        {instructorSummary ? (
          <Card>
            <Text className="whitespace-pre-line">{instructorSummary.summary_md}</Text>
            <Text variant="caption" muted>
              {instructorSummary.model} · {instructorSummary.source_rating_count} reviews
            </Text>
          </Card>
        ) : (
          <Card description="No summary generated yet. Run backend/app/ingest/run_summaries.py." />
        )}
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Courses</Text>
        <div className="flex flex-wrap gap-4 *:grow *:basis-65">
          {professor.courses.length === 0 ? (
            <Card description="No courses on record for this professor." />
          ) : (
            professor.courses.map((course) => (
              <Card key={course.course_id} title={course.code} description={course.title ?? ''}>
                <Text variant="caption" muted>
                  rating {fixed(course.adj_rating)} · difficulty {fixed(course.adj_difficulty)} ·{' '}
                  {course.class_rating_count > 0
                    ? `${course.class_rating_count} reviews of this class`
                    : "using this professor's overall score"}
                </Text>
              </Card>
            ))
          )}
        </div>
      </section>

      <ProfessorReviews comments={professor.recent_comments} rmpId={professor.rmp_id} />
    </main>
  );
}
