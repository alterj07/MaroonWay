import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Card } from '@/components/card';
import { Screen } from '@/components/screen';
import { Text } from '@/components/text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

export default function HomeScreen() {
  const theme = useTheme();
  const [votes, setVotes] = useState(0);

  return (
    <Screen title="MaroonWay — Hackathon starter">

      <View style={styles.hero}>
        <Text variant="eyebrow" style={{ color: theme.primary }}>
          Hackathon starter
        </Text>
        <Text variant="title">
          One codebase.{'\n'}Web, iOS, and Android.
        </Text>
        <Text muted style={styles.lede}>
          MaroonWay is an Expo Router + React Native Web template. Edit the files in{' '}
          <Text style={styles.code}>src/app</Text> and the routes update instantly in the browser.
        </Text>
        <View style={styles.actions}>
          <Button label="See what's inside" href="/about" />
          <Button label="Expo docs" variant="secondary" href="/about" />
        </View>
      </View>

      <View style={styles.section}>
        <Text variant="heading">What you get</Text>
        <View style={styles.grid}>
          <Card
            title="File-based routing"
            description="Every file in src/app becomes a URL. Real links, real back button, deep links on mobile."
          />
          <Card
            title="Themed components"
            description="Text, Button, Card, and Screen read from one token file and follow light/dark mode."
          />
          <Card
            title="Static web export"
            description="npm run build:web writes a dist/ folder you can drop on any host during demo hour."
          />
        </View>
      </View>

      <View style={styles.section}>
        <Text variant="heading">It is interactive, too</Text>
        <Card>
          <Text variant="subheading">Judge votes: {votes}</Text>
          <Text muted style={styles.cardLede}>
            Plain React state — the same component runs on the web page and in the mobile app.
          </Text>
          <View style={styles.actions}>
            <Button label="+1 vote" onPress={() => setVotes((v) => v + 1)} />
            <Button label="Reset" variant="ghost" onPress={() => setVotes(0)} />
          </View>
        </Card>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: {
    gap: Spacing.md,
    paddingTop: Spacing.lg,
  },
  lede: {
    fontSize: 18,
    lineHeight: 28,
    maxWidth: 620,
  },
  code: {
    fontSize: 16,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.sm,
    marginTop: Spacing.sm,
  },
  section: {
    gap: Spacing.md,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: Spacing.md,
  },
  cardLede: {
    fontSize: 15,
  },
});
