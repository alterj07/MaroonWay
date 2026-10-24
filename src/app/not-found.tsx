import type { Metadata } from 'next';

import { Button } from '@/components/button';
import { Text } from '@/components/text';

export const metadata: Metadata = {
  title: 'Not found',
};

export default function NotFound() {
  return (
    <section className="flex flex-col items-start gap-4 pt-10">
      <Text variant="title">404</Text>
      <Text muted>That page does not exist yet.</Text>
      <Button href="/" className="mt-2">
        Go home
      </Button>
    </section>
  );
}
