import type { ReactNode } from 'react';
import { useEffect } from 'react';
import {
  Platform,
  ScrollView,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { NavBar } from '@/components/nav-bar';
import { Layout, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

export type ScreenProps = {
  children: ReactNode;
  /** Browser tab title. Ignored on iOS and Android. */
  title?: string;
  /** Hide the top navigation, e.g. for a full-bleed landing page. */
  hideNav?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
};

/** Page shell: safe areas, nav bar, and a centered max-width column. */
export function Screen({ children, title, hideNav, contentStyle }: ScreenProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  useDocumentTitle(title);

  return (
    <View style={[styles.root, { backgroundColor: theme.background, paddingTop: insets.top }]}>
      {hideNav ? null : <NavBar />}
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={[styles.content, contentStyle]}>{children}</View>
      </ScrollView>
    </View>
  );
}

/**
 * The static web export renders the shared <title> from src/app/+html.tsx, so the
 * per-page title is applied once the browser takes over.
 */
function useDocumentTitle(title?: string) {
  useEffect(() => {
    if (Platform.OS === 'web' && title) {
      document.title = title;
    }
  }, [title]);
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  scroll: {
    flexGrow: 1,
  },
  content: {
    width: '100%',
    maxWidth: Layout.maxWidth,
    alignSelf: 'center',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.xl,
    gap: Spacing.xl,
  },
});
