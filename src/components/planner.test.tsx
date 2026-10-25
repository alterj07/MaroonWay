import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Planner, type Plan } from './planner';

afterEach(cleanup);

const plan: Plan = {
  id: 1, name: 'Best match', subtitle: 'A schedule', score: 80,
  rating: '4.0', aRate: '70%', gap: '20 min', earliest: '9:00 AM',
  tags: ['Conflict-free'], courses: [],
};

function setup(initialTerm = 'FALL 2026') {
  const props = {
    plans: [plan], courses: [], student: null,
    savedCourses: ['CSCE120'], savedWants: '',
    initialTerm, terms: ['FALL 2026', 'SPRING 2027'],
    onSaveCourses: vi.fn(async () => ({ saved: true })),
    onBuildPlans: vi.fn(async (_codes: string[], _wants: string, _term?: string | null) => [plan]),
    onUseSchedule: vi.fn(async () => ({ saved: true })),
  };
  render(<Planner {...props} />);
  return props;
}

async function openBuilder() {
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
}

describe('planner semester selection', () => {
  it('builds the saved semester even when it is not the first available semester', async () => {
    const props = setup('SPRING 2027');
    await openBuilder();
    expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).value)
      .toBe('SPRING 2027');
    expect(props.onBuildPlans).toHaveBeenLastCalledWith(['CSCE120'], '', 'SPRING 2027');
  });

  it('rebuilds and saves using the newly selected semester', async () => {
    const props = setup();
    await openBuilder();
    fireEvent.change(screen.getByRole('combobox', { name: 'Semester' }), {
      target: { value: 'SPRING 2027' },
    });
    await waitFor(() => expect(props.onBuildPlans).toHaveBeenLastCalledWith(
      ['CSCE120'], expect.any(String), 'SPRING 2027',
    ));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Use this schedule' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Use this schedule' }));
    await waitFor(() => expect(props.onUseSchedule).toHaveBeenCalledWith('SPRING 2027', 'Best match', plan));
  });

  it('prevents a second semester change and saving while a rebuild is pending', async () => {
    const props = setup();
    await openBuilder();
    let finish!: (plans: Plan[]) => void;
    props.onBuildPlans.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Semester' }), {
      target: { value: 'SPRING 2027' },
    });
    expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Use this schedule' }) as HTMLButtonElement).disabled).toBe(true);
    finish([plan]);
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).disabled).toBe(false));
  });

  it('does not allow saving an old-semester result after the new build fails', async () => {
    const props = setup();
    await openBuilder();
    props.onBuildPlans.mockRejectedValueOnce(new Error('Network unavailable'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Semester' }), {
      target: { value: 'SPRING 2027' },
    });
    await screen.findByRole('heading', { name: 'No schedule could be built' });
    expect(screen.queryByRole('button', { name: 'Use this schedule' })).toBeNull();
    expect(props.onUseSchedule).not.toHaveBeenCalled();
    expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).disabled).toBe(false);
  });
});
