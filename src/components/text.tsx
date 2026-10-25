import type { ComponentPropsWithoutRef, ElementType } from 'react';

import { cn } from '@/lib/cn';

type Variant = 'title' | 'heading' | 'subheading' | 'body' | 'caption' | 'eyebrow';

/** The type scale, in one place. */
const VARIANT_CLASS: Record<Variant, string> = {
  title: 'text-4xl/tight font-extrabold tracking-tight sm:text-5xl/tight',
  heading: 'text-2xl/snug font-bold tracking-tight',
  subheading: 'text-lg/relaxed font-semibold',
  body: 'text-base/relaxed',
  caption: 'text-[0.8125rem]/5',
  eyebrow: 'text-xs/4 font-bold tracking-[0.1em] uppercase',
};

/** Each variant also picks a sensible element, so the markup stays semantic. */
const VARIANT_TAG: Record<Variant, ElementType> = {
  title: 'h1',
  heading: 'h2',
  subheading: 'h3',
  body: 'p',
  caption: 'p',
  eyebrow: 'p',
};

export type TextProps<T extends ElementType> = {
  /** Override the element the variant would pick, e.g. `as="span"`. */
  as?: T;
  variant?: Variant;
  muted?: boolean;
} & Omit<ComponentPropsWithoutRef<T>, 'as'>;

/** Text that already knows about the theme and the type scale. */
export function Text<T extends ElementType = 'p'>({
  as,
  variant = 'body',
  muted,
  className,
  ...rest
}: TextProps<T>) {
  const Tag = (as ?? VARIANT_TAG[variant]) as ElementType;

  return (
    <Tag className={cn(VARIANT_CLASS[variant], muted && 'text-muted', className)} {...rest} />
  );
}
