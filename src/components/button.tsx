import { type Href, useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, type StyleProp, type ViewStyle } from 'react-native';

import { Text } from '@/components/text';
import { Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

type Variant = 'primary' | 'secondary' | 'ghost';

export type ButtonProps = {
  label: string;
  /** Navigate to this route when pressed. */
  href?: Href;
  onPress?: () => void;
  variant?: Variant;
  style?: StyleProp<ViewStyle>;
};

export function Button({ label, href, onPress, variant = 'primary', style }: ButtonProps) {
  const theme = useTheme();
  const router = useRouter();
  const [hovered, setHovered] = useState(false);

  const palette = {
    primary: {
      background: hovered ? theme.primaryHover : theme.primary,
      border: 'transparent',
      label: theme.onPrimary,
    },
    secondary: {
      background: hovered ? theme.surfaceAlt : theme.surface,
      border: theme.border,
      label: theme.text,
    },
    ghost: {
      background: hovered ? theme.surface : 'transparent',
      border: 'transparent',
      label: theme.primary,
    },
  }[variant];

  return (
    <Pressable
      accessibilityRole="button"
      onHoverIn={() => setHovered(true)}
      onHoverOut={() => setHovered(false)}
      onPress={() => {
        onPress?.();
        if (href) router.navigate(href);
      }}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: palette.background,
          borderColor: palette.border,
          opacity: pressed ? 0.8 : 1,
        },
        style,
      ]}>
      <Text variant="subheading" style={[styles.label, { color: palette.label }]}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    paddingVertical: Spacing.sm + 4,
    paddingHorizontal: Spacing.lg,
    borderRadius: Radius.pill,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    fontSize: 16,
  },
});
