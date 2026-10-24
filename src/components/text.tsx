import { StyleSheet, Text as RNText, type TextProps } from 'react-native';

import { Fonts } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

type Variant = 'title' | 'heading' | 'subheading' | 'body' | 'caption' | 'eyebrow';

export type AppTextProps = TextProps & {
  variant?: Variant;
  muted?: boolean;
};

/** Text that already knows about the theme and the type scale. */
export function Text({ variant = 'body', muted, style, ...rest }: AppTextProps) {
  const theme = useTheme();
  const color = muted ? theme.textMuted : theme.text;

  return <RNText {...rest} style={[styles.base, { color }, styles[variant], style]} />;
}

const styles = StyleSheet.create({
  base: {
    fontFamily: Fonts.sans,
  },
  title: {
    fontSize: 40,
    lineHeight: 46,
    fontWeight: '800',
    letterSpacing: -0.5,
  },
  heading: {
    fontSize: 26,
    lineHeight: 32,
    fontWeight: '700',
    letterSpacing: -0.3,
  },
  subheading: {
    fontSize: 18,
    lineHeight: 26,
    fontWeight: '600',
  },
  body: {
    fontSize: 16,
    lineHeight: 25,
  },
  caption: {
    fontSize: 13,
    lineHeight: 18,
  },
  eyebrow: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },
});
