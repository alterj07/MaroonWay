'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { Text } from '@/components/text';
import { cn } from '@/lib/cn';

const LINKS = [
  { href: '/', label: 'Home' },
  { href: '/about', label: 'About' },
] as const;

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="border-b border-line bg-background">
      <nav className="mx-auto flex w-full max-w-page items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-center gap-2 rounded-md">
          <span className="size-3.5 rounded-full bg-primary" />
          <Text as="span" variant="subheading">
            MaroonWay
          </Text>
        </Link>

        <ul className="flex items-center gap-4">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'block px-2 py-1 text-base/relaxed transition-colors',
                    active ? 'font-semibold text-primary' : 'text-muted hover:text-foreground'
                  )}>
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
