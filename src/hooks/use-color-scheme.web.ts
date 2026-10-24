import { useSyncExternalStore } from 'react';
import { useColorScheme as useRNColorScheme } from 'react-native';

/** Nothing to subscribe to — the snapshot only has to differ server vs. client. */
const subscribe = () => () => {};

/**
 * Static rendering means the first paint happens without a browser, so the real
 * color scheme is only known once the page hydrates. Returning 'light' for the
 * server snapshot keeps the markup identical on both sides of hydration.
 */
export function useColorScheme() {
  const hasHydrated = useSyncExternalStore(
    subscribe,
    () => true,
    () => false
  );
  const colorScheme = useRNColorScheme();

  return hasHydrated ? colorScheme : 'light';
}
