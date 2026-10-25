import type { NextAuthOptions } from 'next-auth';
import GoogleProvider from 'next-auth/providers/google';

/**
 * Google sign-in, restricted to Texas A&M accounts.
 *
 * What this is: proof that someone holds a `@tamu.edu` Google account, and a
 * stable id to hang their saved preferences and schedules on.
 *
 * What this is **not**: a Howdy login. Howdy authenticates a NetID through CAS
 * (`cas.tamu.edu`) with Duo two-factor — a different credential entirely;
 * Google only serves A&M email. So signing in here grants no access to a
 * student's registration, schedule or grades. Class times come from the
 * importer in tools/, which runs in the student's own browser.
 */
const ALLOWED_DOMAIN = 'tamu.edu';

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? '',
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? '',
      authorization: {
        params: {
          // Asks Google to show only A&M accounts. A hint, not a guarantee —
          // the signIn callback below is what actually enforces it.
          hd: ALLOWED_DOMAIN,
          prompt: 'select_account',
        },
      },
    }),
  ],
  callbacks: {
    async signIn({ profile }) {
      const email = profile?.email?.toLowerCase();
      // `hd` can be spoofed in a crafted request, and a personal Gmail would
      // otherwise sail through, so the domain is checked here too.
      return Boolean(email?.endsWith(`@${ALLOWED_DOMAIN}`));
    },
    async jwt({ token, profile }) {
      // Google's `sub` is stable; the email is not, so the subject is what the
      // backend keys a student on.
      if (profile?.sub) token.sub = profile.sub;
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as { subject?: string }).subject = token.sub;
      }
      return session;
    },
  },
  // Both land on our own gate. Left to NextAuth they render its default page,
  // which answers a dropped state cookie with "Try signing in with a different
  // account." -- advice that cannot work, since the account was never the
  // problem.
  pages: { signIn: '/', error: '/' },
};
