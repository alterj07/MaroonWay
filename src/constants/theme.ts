/**
 * Design tokens for the app. Change these values and the whole UI follows.
 */
import { Platform } from 'react-native';

export const Palette = {
  maroon: '#500000',
  maroonDark: '#3A0000',
  maroonLight: '#8E2436',
  rose: '#D86B78',
  gold: '#E0B35C',
} as const;

export type ThemeColors = {
  background: string;
  surface: string;
  surfaceAlt: string;
  text: string;
  textMuted: string;
  border: string;
  primary: string;
  primaryHover: string;
  onPrimary: string;
  accent: string;
};

export const Colors: Record<'light' | 'dark', ThemeColors> = {
  light: {
    background: '#FFFFFF',
    surface: '#FAF7F7',
    surfaceAlt: '#F3EBEC',
    text: '#1B1416',
    textMuted: '#6E6065',
    border: '#E7DDDE',
    primary: Palette.maroon,
    primaryHover: Palette.maroonDark,
    onPrimary: '#FFFFFF',
    accent: Palette.gold,
  },
  dark: {
    background: '#141011',
    surface: '#1D1719',
    surfaceAlt: '#272023',
    text: '#F5EFF0',
    textMuted: '#A99DA1',
    border: '#332A2D',
    primary: Palette.maroonLight,
    primaryHover: Palette.rose,
    onPrimary: '#FFFFFF',
    accent: Palette.gold,
  },
};

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 40,
  xxl: 64,
} as const;

export const Radius = {
  sm: 6,
  md: 12,
  lg: 20,
  pill: 999,
} as const;

export const Layout = {
  /** Max content width, so the site does not sprawl on big monitors. */
  maxWidth: 1040,
  /** Breakpoint used to switch to the wide (desktop) layout. */
  wide: 760,
} as const;

export const Fonts = Platform.select({
  web: {
    sans: 'var(--font-sans)',
    mono: 'var(--font-mono)',
  },
  ios: {
    sans: 'system-ui',
    mono: 'ui-monospace',
  },
  default: {
    sans: 'sans-serif',
    mono: 'monospace',
  },
});
