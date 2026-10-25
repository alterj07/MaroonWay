import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { buildPlans } from './actions';
import Home from './page';

vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/session', () => ({
  currentStudent: async () => ({ subject: 'demo-test', email: 'demo@tamu.edu', name: 'Demo' }),
  studentHeaders: () => ({ 'x-student-subject': 'demo-test' }),
}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function backend() {
  const preferences = {
    wants: 'no Fridays', courses: ['CSCE120'], weights: {}, engine: null,
    term: 'FALL 2026', updated_at: '2026-10-25T08:00:00Z',
  };
  vi.stubGlobal('fetch', async (url: string, options?: RequestInit) => {
    const path = new URL(url).pathname;
    if (path === '/healthz') return Response.json({ status: 'ok', database: 'ok', data_version: 1, detail: null });
    if (path === '/me/preferences') {
      if (options?.method === 'PUT') Object.assign(preferences, JSON.parse(options.body as string));
      return Response.json(preferences);
    }
    if (path === '/schedule/terms') return Response.json([{ term: 'FALL 2026', sections: 1, with_times: 1 }]);
    if (path === '/schedule/courses') return Response.json([{ code: 'MATH151', title: 'Calculus', with_times: 1 }]);
    if (path === '/schedule') return Response.json({ schedules: [], detail: 'No sections match' });
    if (path === '/courses/explore' || path === '/me/schedules') return Response.json([]);
    throw new Error(`Unexpected request ${path}`);
  });
  return preferences;
}

it('persists a deliberately empty preference instead of restoring the old one', async () => {
  const preferences = backend();
  await buildPlans(['CSCE120'], '', 'FALL 2026');
  expect(preferences.wants).toBe('');
});

it('keeps cleared courses and preferences empty after a page refresh', async () => {
  const preferences = backend();
  preferences.courses = [];
  preferences.wants = '';
  render(await Home({ searchParams: Promise.resolve({}) }));
  expect((screen.getByRole('button', { name: 'Continue' }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByPlaceholderText(/Tell us your preferences/) as HTMLInputElement).value).toBe('');
});
