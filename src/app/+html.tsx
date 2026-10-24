import { ScrollViewStyleReset, useServerDocumentContext } from 'expo-router/html';
import type { PropsWithChildren } from 'react';

/**
 * The HTML shell around every statically rendered page. Web only — it has no
 * effect on iOS or Android.
 *
 * `headNodes` and `bodyNodes` carry the bundled CSS and JS, so they have to be
 * rendered or the page ships without styles or scripts.
 */
export default function Root({ children }: PropsWithChildren) {
  const { htmlAttributes, bodyAttributes, headNodes, bodyNodes } = useServerDocumentContext();

  return (
    <html lang="en" {...htmlAttributes}>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
        <title>MaroonWay</title>
        <meta
          name="description"
          content="An Expo Router starter that ships to web, iOS, and Android from one codebase."
        />
        {/* Gives #root a height so the app's single scroll container works. */}
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: bodyBackground }} />
        {headNodes}
      </head>
      <body {...bodyAttributes}>
        {children}
        {bodyNodes}
      </body>
    </html>
  );
}

/** Painted before React mounts, so there is no white flash in dark mode. */
const bodyBackground = `
body { background-color: #fff; }
@media (prefers-color-scheme: dark) {
  body { background-color: #141011; }
}`;
