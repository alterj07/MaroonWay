import type { Metadata } from "next";
import "./globals.css";
import "./theme.css";
import "./mode.css";
import "./pages.css";
import "./continuity.css";
import "./loading.css";
import "./picker.css";
import "./explorer.css";
import "./uniform.css";
import "./gate.css";

export const metadata: Metadata = {
  title: "MaroonWay | Build a Better TAMU Schedule",
  description: "AI-powered course schedule recommendations for Texas A&M students.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      {/* Extensions such as Grammarly add attributes to <body> before React
          hydrates, which React reports as a mismatch against the server's
          HTML. Suppressing it here covers the attributes themselves without
          hiding a real mismatch inside the app. */}
      <body className="antialiased" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
