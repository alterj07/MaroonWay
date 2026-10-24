# MaroonWay

A hackathon starter: one React Native codebase that runs as a **website** (via
React Native Web) and as an **iOS/Android app**, with file-based routing from
Expo Router.

Built on Expo SDK 58 · React Native 0.88 · React 19 · TypeScript.

## Quick start

```bash
npm install
npm run web        # opens the website at http://localhost:8081
```

Other entry points:

| Command              | What it does                                        |
| -------------------- | --------------------------------------------------- |
| `npm run web`        | Dev server in the browser, with fast refresh        |
| `npm start`          | Dev server with a QR code for Expo Go on a phone    |
| `npm run android`    | Open on an Android emulator/device                  |
| `npm run ios`        | Open on an iOS simulator (macOS only)               |
| `npm run build:web`  | Static site into `dist/`                            |
| `npm run typecheck`  | `tsc --noEmit`                                      |
| `npm run lint`       | ESLint                                              |

## Project layout

```
src/app/              routes — one file is one URL
  _layout.tsx         wraps every route: theme provider + stack
  index.tsx           /
  about.tsx           /about
  +not-found.tsx      404
  +html.tsx           the <head> of the static web build (web only)
src/components/       Text, Button, Card, NavBar, Screen
src/constants/theme.ts   colors, spacing, radii, breakpoints
src/hooks/            color scheme + theme access
assets/images/        icon, favicon, splash
```

`@/` is an alias for `src/`, so `import { Button } from '@/components/button'`
works from anywhere.

## Adding a page

Create the file, and the route exists:

```tsx
// src/app/teams.tsx  ->  /teams
import { Screen } from '@/components/screen';
import { Text } from '@/components/text';

export default function TeamsScreen() {
  return (
    <Screen title="Teams · MaroonWay">
      <Text variant="title">Teams</Text>
    </Screen>
  );
}
```

Then add it to `LINKS` in `src/components/nav-bar.tsx` so it shows up in the nav.
Folders nest (`src/app/teams/[id].tsx` → `/teams/42`, read with `useLocalSearchParams`).

## Theming

Every component reads from `src/constants/theme.ts`. Change `Palette.maroon` and
the buttons, links, and accents all follow. Light and dark variants live side by
side in `Colors`, and `useTheme()` returns the active one.

## Deploying the website

```bash
npm run build:web      # writes dist/
npx serve dist         # preview the built site locally
```

Preview with something that maps clean URLs to files (`npx serve` does). A bare
file server such as `python3 -m http.server` will 404 on `/about`, because the
page lives at `about.html`.

`dist/` is plain static files — drop it on Vercel, Netlify, GitHub Pages, Cloudflare
Pages, or `npx eas-cli@latest deploy` for EAS Hosting.

Need server-side code (an `/api/...` endpoint)? Set `web.output` to `"server"` in
`app.json`, add `src/app/api/thing+api.ts`, and deploy to a Node host instead of a
static one.

## Notes

- **Page titles.** The static HTML ships the shared `<title>` from `+html.tsx`, and the
  `title` prop on `<Screen>` sets the per-page title once the page is interactive.
  Expo Router's `<Head>` component renders nothing during static export on SDK 58, so
  the template does not use it.
- **Editing `+html.tsx`.** It must render `headNodes` and `bodyNodes` from
  `useServerDocumentContext()` — that is how SDK 58 injects the bundled CSS and JS.
  Drop them and every page ships unstyled with no scripts. Keep `<ScrollViewStyleReset />`
  too, or the page content collapses to zero height below the nav bar.
- **No animation libraries.** Reanimated and Gesture Handler are left out to keep the
  install small. Add them with `npx expo install react-native-reanimated react-native-gesture-handler`.
- **`eslint` is pinned to 9.x** because `eslint-config-expo@58` bundles
  `eslint-plugin-react@7`, which crashes on ESLint 10.
