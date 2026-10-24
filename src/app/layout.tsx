import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { NavBar } from '@/components/nav-bar';

import './globals.css';

export const metadata: Metadata = {
  title: {
    default: 'MaroonWay',
    template: '%s · MaroonWay',
  },
  description: 'A Next.js + Tailwind CSS starter.',
};

/**
 * Wraps every route: the <html> shell, the nav bar, and the centered
 * max-width column that pages render into.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-dvh flex-col">
        <NavBar />
        <main className="mx-auto flex w-full max-w-page grow flex-col gap-10 px-6 py-10">
          {children}
        </main>
      </body>
    </html>
  );
}
