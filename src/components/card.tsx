import type { ReactNode } from 'react';

import { Text } from '@/components/text';
import { cn } from '@/lib/cn';

export type CardProps = {
  title?: string;
  description?: string;
  children?: ReactNode;
  className?: string;
};

export function Card({ title, description, children, className }: CardProps) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-card border border-line bg-surface p-6',
        className
      )}>
      {title ? <Text variant="subheading">{title}</Text> : null}
      {description ? (
        <Text muted className="text-[0.9375rem]/relaxed">
          {description}
        </Text>
      ) : null}
      {children}
    </div>
  );
}
