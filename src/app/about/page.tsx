import type { Metadata } from 'next';

import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Text } from '@/components/text';

export const metadata: Metadata = {
  title: 'About',
  description: 'How the MaroonWay template fits together.',
};

const LAYOUT = [
  'src/app/              routes (one folder = one URL)',
  '  layout.tsx          wraps every route: nav bar + page column',
  '  page.tsx            /',
  '  about/page.tsx      /about',
  '  not-found.tsx       404',
  '  globals.css         Tailwind import + design tokens',
  '  icon.png            favicon (Next picks this up by name)',
  'src/components/       Text, Button, Card, NavBar, VoteCard',
  'src/lib/cn.ts         class-name merge helper',
  'public/               files served as-is at the site root',
];

const STEPS = [
  {
    title: '1. Add a page',
    body: 'Create src/app/teams/page.tsx and it is live at /teams. Nested folders become nested paths.',
  },
  {
    title: '2. Restyle everything',
    body: 'The @theme block in src/app/globals.css holds the colors, fonts, and radii every utility reads from.',
  },
  {
    title: '3. Ship it',
    body: 'npm run build, then deploy to Vercel, Netlify, Cloudflare, or any Node host with npm start.',
  },
];

export default function AboutPage() {
  return (
    <>
      <section className="flex flex-col gap-4">
        <Text variant="eyebrow" muted>
          About
        </Text>
        <Text variant="title">How this template fits together</Text>
        <Text muted className="max-w-[38rem] text-lg/relaxed">
          The App Router gives each URL a folder. Pages render on the server, Tailwind styles them
          with utility classes, and only the components marked{' '}
          <code className="font-mono text-[0.9375rem]">&apos;use client&apos;</code> are hydrated in
          the browser.
        </Text>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Project layout</Text>
        <Card>
          <pre className="overflow-x-auto font-mono text-[0.8125rem]/6">{LAYOUT.join('\n')}</pre>
        </Card>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Next steps</Text>
        <div className="flex flex-wrap gap-4 *:grow *:basis-65">
          {STEPS.map((step) => (
            <Card key={step.title} title={step.title} description={step.body} />
          ))}
        </div>
      </section>

      <Button href="/" variant="secondary" className="self-start">
        Back to home
      </Button>
    </>
  );
}
