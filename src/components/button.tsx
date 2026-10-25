import Link from 'next/link';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';

import { cn } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'ghost';

const BASE =
  'inline-flex cursor-pointer items-center justify-center rounded-full border px-6 py-3 text-base font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary active:opacity-80';

const VARIANT_CLASS: Record<Variant, string> = {
  primary: 'border-transparent bg-primary text-on-primary hover:bg-primary-hover',
  secondary: 'border-line bg-surface text-foreground hover:bg-surface-alt',
  ghost: 'border-transparent text-primary hover:bg-surface',
};

type Common = {
  children: ReactNode;
  variant?: Variant;
  className?: string;
};

type AsLink = Common & { href: string } & Omit<
    ComponentPropsWithoutRef<typeof Link>,
    'href' | 'className' | 'children'
  >;

type AsButton = Common & { href?: undefined } & Omit<
    ComponentPropsWithoutRef<'button'>,
    'className' | 'children'
  >;

export type ButtonProps = AsLink | AsButton;

/**
 * Renders a `<Link>` when given an `href` and a `<button>` otherwise, so
 * navigation stays a real link (middle-click, open in new tab, crawlable).
 */
export function Button({ children, variant = 'primary', className, ...rest }: ButtonProps) {
  const classes = cn(BASE, VARIANT_CLASS[variant], className);

  if (rest.href !== undefined) {
    const { href, ...linkProps } = rest as AsLink;
    return (
      <Link href={href} className={classes} {...linkProps}>
        {children}
      </Link>
    );
  }

  const { href: _href, type, ...buttonProps } = rest as AsButton;
  return (
    <button type={type ?? 'button'} className={classes} {...buttonProps}>
      {children}
    </button>
  );
}
