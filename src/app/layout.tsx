import type { Metadata } from "next";
import "./globals.css";
import "./theme.css";
import "./mode.css";
import "./pages.css";
import "./continuity.css";
import "./loading.css";
import "./picker.css";

export const metadata: Metadata = {
  title: "Maroonway | Build a Better TAMU Schedule",
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
      <body className="antialiased">{children}</body>
    </html>
  );
}
