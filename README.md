# MaroonWay

A hackathon starter: a **Next.js** website with the App Router, **Tailwind CSS v4**,
and TypeScript.

Built on Next.js 16 · React 19 · Tailwind CSS 4 · TypeScript.

## Quick start

```bash
npm install
npm run dev        # http://localhost:3000
```

| Command             | What it does                                 |
| ------------------- | -------------------------------------------- |
| `npm run dev`       | Dev server with fast refresh                 |
| `npm run build`     | Production build into `.next/`               |
| `npm start`         | Serve the production build                   |
| `npm run typecheck` | `tsc --noEmit`                               |
| `npm run lint`      | ESLint (`eslint-config-next`, flat config)   |

## Project layout

```
src/app/              routes — one folder is one URL
  layout.tsx          wraps every route: <html>, nav bar, page column
  page.tsx            /
  about/page.tsx      /about
  not-found.tsx       404
  globals.css         Tailwind import + all design tokens
  icon.png            favicon (Next serves it by filename)
  apple-icon.png      touch icon
src/components/       Text, Button, Card, NavBar, VoteCard
src/lib/cn.ts         class-name merge helper
public/               served as-is at the site root
```

`@/` is an alias for `src/`, so `import { Button } from '@/components/button'`
works from anywhere.

## Adding a page

Create the folder and a `page.tsx`, and the route exists:

```tsx
// src/app/teams/page.tsx  ->  /teams
import type { Metadata } from 'next';

import { Text } from '@/components/text';

export const metadata: Metadata = { title: 'Teams' };

export default function TeamsPage() {
  return <Text variant="title">Teams</Text>;
}
```

The `title` is slotted into the `%s · MaroonWay` template set in
`src/app/layout.tsx`. Add the route to `LINKS` in `src/components/nav-bar.tsx`
so it shows up in the nav. Dynamic segments are folders too:
`src/app/teams/[id]/page.tsx` → `/teams/42`, read from the `params` prop.

## Server and Client Components

Everything under `src/app` is a **Server Component** by default: it renders on
the server and ships no JavaScript. A component only needs `'use client'` at the
top when it uses state, effects, or browser events — see
`src/components/vote-card.tsx` and `src/components/nav-bar.tsx`.

Keep client components small and push them down the tree, so the pages around
them stay server-rendered.

## Theming

Tailwind v4 is configured **in CSS**, not in a `tailwind.config.js`. All tokens
live in the `@theme` blocks at the top of `src/app/globals.css`:

- `@theme` holds the fixed brand palette (`--color-maroon` → `bg-maroon`,
  `text-maroon`, …), the fonts, `--container-page` (→ `max-w-page`), and
  `--radius-card` (→ `rounded-card`).
- `:root` holds the semantic colors (`--background`, `--surface`, `--primary`, …),
  and a `prefers-color-scheme: dark` block swaps them for dark mode.
- `@theme inline` exposes those semantic variables as utilities
  (`bg-background`, `text-muted`, `border-line`, `bg-primary`, …). `inline` is
  what keeps the `var()` reference live, so the dark-mode swap takes effect.

Change `--color-maroon` and the buttons, links, and accents all follow. Dark mode
follows the OS setting; there is no theme toggle.

## Components

| Component    | Notes                                                             |
| ------------ | ----------------------------------------------------------------- |
| `Text`       | The type scale. `variant` also picks a semantic tag (`title` → `h1`); override with `as`. |
| `Button`     | Renders a `<Link>` when given `href`, a `<button>` otherwise.      |
| `Card`       | Bordered surface with optional `title`/`description`.              |
| `NavBar`     | Client component — highlights the active route via `usePathname`.  |
| `VoteCard`   | Example of local state in a client component.                      |

Every component takes `className`, merged with `cn()` (clsx + tailwind-merge),
so a passed utility wins over the component's default.

## Deploying

```bash
npm run build
npm start          # preview the production build locally
```

Push to Vercel, Netlify, Cloudflare, or any Node host. For a fully static export
instead, set `output: 'export'` in `next.config.ts` and serve the `out/` folder —
note that this turns off server-only features.

Need an API endpoint? Add `src/app/api/thing/route.ts` and export `GET`/`POST`.

## Notes

- **No `tailwind.config.js`.** Tailwind v4 runs through PostCSS
  (`postcss.config.mjs`) and reads its configuration from `@theme` in the CSS.
- **Icons.** `src/app/icon.png` and `src/app/apple-icon.png` are picked up by
  filename; `public/maroonway-icon.png` is the 1024px master.
- **ESLint** uses flat config in `eslint.config.mjs`.
