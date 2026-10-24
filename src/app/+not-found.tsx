import { Stack } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/button';
import { Screen } from '@/components/screen';
import { Text } from '@/components/text';
import { Spacing } from '@/constants/theme';

export default function NotFoundScreen() {
  return (
    <>
      <Stack.Screen options={{ title: 'Not found' }} />
      <Screen title="Not found · MaroonWay">
        <View style={styles.body}>
          <Text variant="title">404</Text>
          <Text muted>That page does not exist yet.</Text>
          <Button label="Go home" href="/" style={styles.action} />
        </View>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  body: {
    gap: Spacing.md,
    paddingTop: Spacing.xl,
    alignItems: 'flex-start',
  },
  action: {
    marginTop: Spacing.sm,
  },
});
