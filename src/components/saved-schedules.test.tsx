import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { SavedSchedule } from '@/lib/api';
import { Planner, type Plan } from './planner';

afterEach(cleanup);

const current: Plan = {
  id: 1, name: 'Current unsaved candidate', subtitle: '', score: 80,
  rating: '4.0', aRate: '60%', gap: '20 min', earliest: '9:00 AM', tags: [],
  courses: [{ code: 'CSCE 120', prof: 'Professor', days: [0], start: 9, end: 10, room: 'HRBB', color: 'berry' }],
};
const stored: SavedSchedule = {
  id: 42, term: 'SPRING 2025', label: 'My saved spring schedule', created_at: '2026-10-25T08:00:00Z',
  payload: { ...current, id: 3, name: 'Historical plan' },
};

function setup(schedules: SavedSchedule[] = [], candidates = [current]) {
  const props = {
    plans: candidates, courses: [], student: { email: 'student@tamu.edu', name: 'Student' },
    savedCourses: ['CSCE120'], savedWants: '', terms: ['FALL 2026'], initialTerm: 'FALL 2026',
    savedSchedules: schedules,
    onSaveCourses: vi.fn(async () => ({ saved: true })),
    onBuildPlans: vi.fn(async () => ({ plans: candidates, relaxed: [] as string[] })),
    onUseSchedule: vi.fn(async (): Promise<{ saved: boolean; schedule?: SavedSchedule }> => ({
      saved: true, schedule: { ...stored, term: 'FALL 2026', payload: current },
    })),
  };
  const view = render(<Planner {...props} />);
  return { ...view, props };
}

it('shows persisted schedules instead of unsaved generation candidates', () => {
  setup([stored]);
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  expect(screen.getByRole('heading', { name: 'My saved spring schedule' })).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Current unsaved candidate' })).toBeNull();
});

it('opens the saved snapshot and its original semester without rebuilding it', async () => {
  const { props } = setup([stored]);
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open My saved spring schedule' }));
  expect(screen.getAllByRole('heading', { name: 'Historical plan' }).length).toBeGreaterThan(0);
  expect(screen.getByRole('combobox', { name: 'Semester' }).textContent).toContain('SPRING 2025');
  expect(props.onBuildPlans).not.toHaveBeenCalled();
});

it('shows an empty state when there are no saved schedules', () => {
  setup();
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  expect(screen.getByText('No saved schedules yet')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Open Current unsaved candidate' })).toBeNull();
});

it('adds the record returned by a successful save to the saved list immediately', async () => {
  const { props } = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
  fireEvent.click(screen.getByRole('button', { name: 'Use this schedule' }));
  await screen.findByRole('heading', { name: 'Your schedules' });
  expect(screen.getByRole('heading', { name: 'My saved spring schedule' })).toBeTruthy();
  expect(props.onUseSchedule).toHaveBeenCalledWith('FALL 2026', 'Current unsaved candidate', current);
});

it('does not crash when a stored snapshot has an unsupported payload', () => {
  setup([{ ...stored, payload: { arbitrary: 'old data' } }]);
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  expect(screen.getByText('This saved schedule cannot be displayed.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Open My saved spring schedule' })).toBeNull();
});

it('persists the heart button through the same save action', async () => {
  const { props } = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
  fireEvent.click(screen.getByRole('button', { name: 'Save schedule' }));
  await screen.findByRole('heading', { name: 'Your schedules' });
  expect(props.onUseSchedule).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Open My saved spring schedule' })).toBeTruthy();
});

it('shows save errors and allows retrying without claiming success', async () => {
  const { props } = setup();
  props.onUseSchedule.mockRejectedValueOnce(new Error('API unavailable'));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
  fireEvent.click(screen.getByRole('button', { name: 'Use this schedule' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Could not save');
  expect(screen.queryByRole('heading', { name: 'Your schedules' })).toBeNull();
  await waitFor(() => expect((screen.getByRole('button', { name: 'Use this schedule' }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Use this schedule' }));
  await screen.findByRole('heading', { name: 'Your schedules' });
  expect(props.onUseSchedule).toHaveBeenCalledTimes(2);
});

it('keeps the selected candidate stable while its save is pending', async () => {
  const { props } = setup([], [current, { ...current, id: 2, name: 'Alternative candidate' }]);
  let finish!: (result: { saved: boolean; schedule?: SavedSchedule }) => void;
  props.onUseSchedule.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
  fireEvent.click(screen.getByRole('button', { name: 'Use this schedule' }));
  fireEvent.click(screen.getByRole('button', { name: /Alternative candidate/ }));
  finish({ saved: true, schedule: { ...stored, payload: current } });
  await screen.findByRole('heading', { name: 'Your schedules' });
  fireEvent.click(screen.getByRole('button', { name: 'Schedule builder' }));
  expect(screen.getByRole('button', { name: /Current unsaved candidate/ }).classList.contains('selected')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: /Alternative candidate/ }));
  expect((screen.getByRole('button', { name: 'Use this schedule' }) as HTMLButtonElement).disabled).toBe(false);
});

it('rejects corrupt meeting times before rendering or opening a stored snapshot', () => {
  setup([{ ...stored, payload: { ...current, courses: [{ ...current.courses[0], meetings: [
    { day: 0, start: 9, end: 1e12, room: 'HRBB' },
  ] }] } }]);
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  expect(screen.getByText('This saved schedule cannot be displayed.')).toBeTruthy();
});

it('does not open a different-semester saved snapshot while a rebuild is pending', async () => {
  const { props } = setup([stored]);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
  let finish!: (result: { plans: Plan[]; relaxed: string[] }) => void;
  props.onBuildPlans.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Rebuild my schedule' }));
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open My saved spring schedule' }));
  finish({ plans: [current], relaxed: [] as string[] });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Open My saved spring schedule' }).getAttribute('aria-disabled')).toBe('false'));
  fireEvent.click(screen.getByRole('button', { name: 'Schedule builder' }));
  expect(screen.getByRole('combobox', { name: 'Semester' }).textContent).toContain('FALL 2026');
});

it('does not carry a generated schedule warning into an unrelated saved snapshot', () => {
  setup([stored], [{ ...current, warnings: ['No Friday classes was impossible'] }]);
  fireEvent.click(screen.getByRole('button', { name: 'Schedule builder' }));
  expect(screen.getAllByText(/No Friday classes was impossible/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  fireEvent.click(screen.getByRole('button', { name: 'Open My saved spring schedule' }));
  expect(screen.queryByText(/No Friday classes was impossible/)).toBeNull();
});
