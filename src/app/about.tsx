import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Screen } from '@/components/screen';
import { Text } from '@/components/text';
import { Spacing } from '@/constants/theme';

const STEPS = [
  {
    title: '1. Add a page',
    body: 'Create src/app/teams.tsx and it is live at /teams. Nested folders become nested paths.',
  },
  {
    title: '2. Restyle everything',
    body: 'src/constants/theme.ts holds the colors, spacing, and radii every component reads from.',
  },
  {
    title: '3. Ship it',
    body: 'npm run build:web, then deploy dist/ to Vercel, Netlify, GitHub Pages, or EAS Hosting.',
  },
];

export default function AboutScreen() {
  return (
    <Screen title="About · MaroonWay">

      <View style={styles.header}>
        <Text variant="eyebrow" muted>
          About
        </Text>
        <Text variant="title">How this template fits together</Text>
        <Text muted style={styles.lede}>
          Expo Router gives React Native the routing model of a website. The same components render
          to HTML in the browser and to native views on a phone.
        </Text>
      </View>

      <View style={styles.section}>
        <Text variant="heading">Project layout</Text>
        <Card>
          <Text style={styles.tree}>
            {[
              'src/app/          routes (one file = one URL)',
              '  _layout.tsx     wraps every route: theme + stack',
              '  index.tsx       /',
              '  about.tsx       /about',
              '  +not-found.tsx  404',
              '  +html.tsx       <head> for the web build',
              'src/components/   Text, Button, Card, NavBar, Screen',
              'src/constants/    design tokens',
              'src/hooks/        color scheme + theme access',
            ].join('\n')}
          </Text>
        </Card>
      </View>

      <View style={styles.section}>
        <Text variant="heading">Next steps</Text>
        <View style={styles.grid}>
          {STEPS.map((step) => (
            <Card key={step.title} title={step.title} description={step.body} />
          ))}
        </View>
      </View>

      <Button label="Back to home" variant="secondary" href="/" style={styles.back} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    gap: Spacing.md,
    paddingTop: Spacing.lg,
  },
  lede: {
    fontSize: 18,
    lineHeight: 28,
    maxWidth: 620,
  },
  section: {
    gap: Spacing.md,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.md,
  },
  tree: {
    fontFamily: 'monospace',
    fontSize: 13,
    lineHeight: 22,
  },
  back: {
    alignSelf: 'flex-start',
  },
});
