import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Planner, type Plan, type ExploreCourse } from './planner';

afterEach(cleanup);

const plan: Plan = {
  id: 1, name: 'Best match', subtitle: 'A schedule', score: 80,
  rating: '4.0', aRate: '70%', gap: '20 min', earliest: '9:00 AM',
  tags: ['Conflict-free'], courses: [],
};

function setup(initialTerm = 'FALL 2026', catalog: ExploreCourse[] = []) {
  const props = {
    plans: [plan], courses: catalog, student: { email: 'demo@tamu.edu', name: 'Demo' },
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
  it('keeps an explorer course change saved even if rebuilding subsequently fails', async () => {
    const props = setup('FALL 2026', [{
      course_id: 2, code: 'MATH151', title: 'Calculus', credits: '4', honors: false,
      prereq_text: null, level: null, dept_code: null, campus: null,
      professor_count: 0, avg_rating: null, avg_pct_a: null, professors: [],
    }]);
    await openBuilder();
    props.onBuildPlans.mockRejectedValueOnce(new Error('Network unavailable'));
    fireEvent.click(screen.getByRole('button', { name: 'Course explorer' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add to my plan' }));
    await screen.findByRole('button', { name: 'Saved to your plan' });
    fireEvent.click(screen.getByRole('button', { name: 'Schedule builder' }));
    expect(screen.getByRole('button', { name: 'Remove MATH 151' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'No schedule could be built' })).toBeTruthy();
  });
  it('clears the final course instead of leaving its old schedule on screen', async () => {
    setup();
    await openBuilder();
    fireEvent.click(screen.getByRole('button', { name: 'Remove CSCE 120' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove CSCE 120' })).toBeNull());
    expect(screen.getByText('Add the classes you need')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Use this schedule' })).toBeNull();
  });

  it('shows the preferences entered on the landing page after building', async () => {
    setup();
    fireEvent.change(screen.getByPlaceholderText(/Tell us your preferences/), { target: { value: 'Prefer online classes' } });
    await openBuilder();
    expect(screen.getByRole('button', { name: 'Prefer online classes' })).toBeTruthy();
  });
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
