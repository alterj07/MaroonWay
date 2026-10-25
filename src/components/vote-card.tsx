'use client';

import { useState } from 'react';

import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Text } from '@/components/text';

/**
 * A Client Component: it holds state, so it needs 'use client'. Everything
 * around it stays a Server Component and ships no JavaScript.
 */
export function VoteCard() {
  const [votes, setVotes] = useState(0);

  return (
    <Card>
      <Text variant="subheading">Judge votes: {votes}</Text>
      <Text muted className="text-[0.9375rem]/relaxed">
        Plain React state. The page around this card is rendered on the server — only this
        component is hydrated in the browser.
      </Text>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button onClick={() => setVotes((v) => v + 1)}>+1 vote</Button>
        <Button variant="ghost" onClick={() => setVotes(0)}>
          Reset
        </Button>
      </div>
    </Card>
  );
}
