import { Link, usePathname } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Text } from '@/components/text';
import { Layout, Radius, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

const LINKS = [
  { href: '/', label: 'Home' },
  { href: '/about', label: 'About' },
] as const;

export function NavBar() {
  const theme = useTheme();
  const pathname = usePathname();

  return (
    <View style={[styles.bar, { backgroundColor: theme.background, borderColor: theme.border }]}>
      <View style={styles.inner}>
        <Link href="/" style={styles.brandLink}>
          <View style={styles.brand}>
            <View style={[styles.dot, { backgroundColor: theme.primary }]} />
            <Text variant="subheading">MaroonWay</Text>
          </View>
        </Link>

        <View style={styles.links}>
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link key={link.href} href={link.href} style={styles.link}>
                <Text
                  variant="body"
                  muted={!active}
                  style={active ? { color: theme.primary, fontWeight: '600' } : undefined}>
                  {link.label}
                </Text>
              </Link>
            );
          })}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    borderBottomWidth: 1,
  },
  inner: {
    width: '100%',
    maxWidth: Layout.maxWidth,
    alignSelf: 'center',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
  },
  brandLink: {
    borderRadius: Radius.sm,
  },
  brand: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  dot: {
    width: 14,
    height: 14,
    borderRadius: Radius.pill,
  },
  links: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
  },
  link: {
    paddingVertical: Spacing.xs,
    paddingHorizontal: Spacing.sm,
  },
});
