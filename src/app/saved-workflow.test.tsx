import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useSchedule } from './actions';
import Home from './page';
import type { Plan } from '@/components/planner';
import type { SavedSchedule } from '@/lib/api';

vi.mock('next/cache', () => ({ revalidatePath: vi.fn() }));
vi.mock('@/lib/session', () => ({
  currentStudent: async () => ({ subject: 'student-1', email: 'student@tamu.edu', name: 'Student' }),
  studentHeaders: () => ({ 'x-student-subject': 'student-1' }),
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function backend(failList = false) {
  const records: SavedSchedule[] = [];
  vi.stubGlobal('fetch', async (url: string, options?: RequestInit) => {
    const path = new URL(url).pathname;
    if (path === '/healthz') return Response.json({ status: 'ok', database: 'ok', data_version: 1, detail: null });
    if (path === '/courses/explore' || path === '/schedule/terms') return Response.json([]);
    if (path === '/me/preferences') return Response.json({
      wants: null, weights: {}, engine: null, courses: [], term: null, updated_at: null,
    });
    if (path === '/me/schedules') {
      if (options?.method === 'POST') {
        records.push({ id: 42, ...JSON.parse(options.body as string), created_at: '2026-10-25T08:00:00Z' });
        return Response.json(records[records.length - 1]);
      }
      if (failList) return new Response('Unavailable', { status: 503 });
      return Response.json(records);
    }
    throw new Error(`Unexpected backend request: ${path}`);
  });
}

it('loads the stored snapshot through the server page after saving and refreshing', async () => {
  backend();
  const plan: Plan = {
    id: 3, name: 'Original saved plan', subtitle: '', score: 80,
    rating: '4.0', aRate: '60%', gap: '20 min', earliest: '9:00 AM', tags: [], courses: [],
  };
  const result = await useSchedule('SPRING 2025', 'Spring favorite', plan);
  expect(result.saved).toBe(true);
  expect(result).toMatchObject({ schedule: { id: 42, term: 'SPRING 2025', payload: { name: 'Original saved plan' } } });
  render(await Home({ searchParams: Promise.resolve({}) }));
  fireEvent.click(screen.getByRole('button', { name: 'My schedules' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open Spring favorite' }));
  expect(screen.getAllByRole('heading', { name: 'Original saved plan' }).length).toBeGreaterThan(0);
  expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).value).toBe('SPRING 2025');
});

it('distinguishes a failed saved-list request from an empty account', async () => {
  backend(true);
  render(await Home({ searchParams: Promise.resolve({}) }));
  fireEvent.click(screen.getByRole('button', { name: 'My schedules' }));
  expect(screen.getByRole('alert').textContent).toContain('Could not load your saved schedules');
  expect(screen.queryByText('No saved schedules yet')).toBeNull();
});
