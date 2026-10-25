'use client';

import { useState } from 'react';
import type { Comment } from '@/lib/api';
import { Card } from '@/components/card';
import { Text } from '@/components/text';

export function ProfessorReviews({ comments, rmpId }: { comments: Comment[]; rmpId: number | null }) {
  const [visible, setVisible] = useState(5);
  return (
    <section className="flex flex-col gap-4" aria-labelledby="professor-reviews-heading">
      <Text variant="heading" id="professor-reviews-heading">RateMyProfessors reviews</Text>
      {comments.length === 0 ? (
        <Card description="No review text is available for this professor yet." />
      ) : (
        <>
          <Text variant="caption" muted aria-live="polite">
            Showing {Math.min(visible, comments.length)} of {comments.length} loaded reviews
          </Text>
          <Text variant="caption" muted>
            These are the latest review comments stored in MaroonWay, not necessarily every rating on RateMyProfessors.
          </Text>
          {comments.slice(0, visible).map((comment, index) => (
            <Card key={index}>
              <Text className="whitespace-pre-line break-words">{comment.comment}</Text>
              <Text variant="caption" muted>
                {[
                  comment.class_code,
                  comment.rated_at?.slice(0, 10),
                  comment.difficulty === null ? null : `difficulty ${comment.difficulty.toFixed(1)}`,
                ].filter(Boolean).join(' · ')}
              </Text>
            </Card>
          ))}
          {visible < comments.length ? (
            <button type="button" className="self-start rounded-md border border-line px-4 py-2 text-sm font-semibold" onClick={() => setVisible((count) => count + 5)}>
              Show more reviews
            </button>
          ) : null}
        </>
      )}
      {rmpId !== null ? (
        <a className="self-start text-sm text-primary underline" href={`https://www.ratemyprofessors.com/professor/${rmpId}`} target="_blank" rel="noopener noreferrer">
          View on RateMyProfessors
        </a>
      ) : null}
    </section>
  );
}
