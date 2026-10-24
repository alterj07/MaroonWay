import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Text } from '@/components/text';
import { VoteCard } from '@/components/vote-card';

const FEATURES = [
  {
    title: 'File-based routing',
    description:
      'Every folder in src/app with a page.tsx becomes a URL. Real links, real back button, prefetched navigation.',
  },
  {
    title: 'Tailwind CSS v4',
    description:
      'Utility classes with the design tokens defined in src/app/globals.css. No config file, no runtime CSS-in-JS.',
  },
  {
    title: 'Server Components',
    description:
      'Pages render on the server by default and ship zero JavaScript. Add "use client" only where you need state.',
  },
];

export default function HomePage() {
  return (
    <>
      <section className="flex flex-col gap-4">
        <Text variant="eyebrow" className="text-primary">
          Hackathon starter
        </Text>
        <Text variant="title">
          One codebase.
          <br />
          Server-rendered and styled.
        </Text>
        <Text muted className="max-w-[38rem] text-lg/relaxed">
          MaroonWay is a Next.js App Router + Tailwind CSS template. Edit the files in{' '}
          <code className="font-mono text-[0.9375rem]">src/app</code> and the page updates
          instantly in the browser.
        </Text>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button href="/about">See what&apos;s inside</Button>
          <Button href="https://nextjs.org/docs" variant="secondary">
            Next.js docs
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">What you get</Text>
        <div className="flex flex-wrap gap-4 *:grow *:basis-65">
          {FEATURES.map((feature) => (
            <Card key={feature.title} title={feature.title} description={feature.description} />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">It is interactive, too</Text>
        <VoteCard />
      </section>
    </>
  );
}
