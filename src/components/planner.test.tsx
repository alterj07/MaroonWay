import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Planner, type Plan, type ExploreCourse } from './planner';

afterEach(cleanup);

const plan: Plan = {
  id: 1, name: 'Best match', subtitle: 'A schedule', score: 80,
  rating: '4.0', aRate: '70%', gap: '20 min', earliest: '9:00 AM',
  tags: ['Conflict-free'], courses: [],
};

function setup(initialTerm = 'FALL 2026', catalog: ExploreCourse[] = [], initialPlans = [plan]) {
  const props = {
    plans: initialPlans, courses: catalog, student: { email: 'demo@tamu.edu', name: 'Demo' },
    savedCourses: ['CSCE120'], savedWants: '',
    initialTerm, terms: ['FALL 2026', 'SPRING 2027'],
    onSaveCourses: vi.fn(async () => ({ saved: true })),
    onBuildPlans: vi.fn(async (
      _codes: string[],
      _wants: string,
      _term?: string | null,
      _locks?: Record<string, unknown>,
    ) => ({ plans: [plan], relaxed: [] as string[] })),
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
    fireEvent.click(screen.getByRole('button', { name: /^Remove$/ }));
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
    expect(screen.getByRole('combobox', { name: 'Semester' }).textContent)
      .toContain('SPRING 2027');
    // The fourth argument is the pins. Nothing pinned, nothing sent.
    expect(props.onBuildPlans).toHaveBeenLastCalledWith(['CSCE120'], '', 'SPRING 2027', undefined);
  });

  it('rebuilds and saves using the newly selected semester', async () => {
    const props = setup();
    await openBuilder();
    fireEvent.click(screen.getByRole('combobox', { name: 'Semester' }));
    fireEvent.click(screen.getByRole('option', { name: 'SPRING 2027' }));
    await waitFor(() => expect(props.onBuildPlans).toHaveBeenLastCalledWith(
      ['CSCE120'], expect.any(String), 'SPRING 2027', undefined,
    ));
    await waitFor(() => expect((screen.getByRole('button', { name: 'Use this schedule' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Use this schedule' }));
    await waitFor(() => expect(props.onUseSchedule).toHaveBeenCalledWith('SPRING 2027', 'Best match', plan));
  });

  it('prevents a second semester change and saving while a rebuild is pending', async () => {
    const props = setup();
    await openBuilder();
    let finish!: (result: { plans: Plan[]; relaxed: string[] }) => void;
    props.onBuildPlans.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    fireEvent.click(screen.getByRole('combobox', { name: 'Semester' }));
    fireEvent.click(screen.getByRole('option', { name: 'SPRING 2027' }));
    expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Use this schedule' }) as HTMLButtonElement).disabled).toBe(true);
    finish({ plans: [plan], relaxed: [] as string[] });
    await waitFor(() => expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).disabled).toBe(false));
  });

  it('does not allow saving an old-semester result after the new build fails', async () => {
    const props = setup();
    await openBuilder();
    props.onBuildPlans.mockRejectedValueOnce(new Error('Network unavailable'));
    fireEvent.click(screen.getByRole('combobox', { name: 'Semester' }));
    fireEvent.click(screen.getByRole('option', { name: 'SPRING 2027' }));
    await screen.findByRole('heading', { name: 'No schedule could be built' });
    expect(screen.queryByRole('button', { name: 'Use this schedule' })).toBeNull();
    expect(props.onUseSchedule).not.toHaveBeenCalled();
    expect((screen.getByRole('combobox', { name: 'Semester' }) as HTMLSelectElement).disabled).toBe(false);
  });
});


it('links explorer professor names to their review pages without inventing links for unknown identities', async () => {
  setup('FALL 2026', [{
    course_id: 2, code: 'CSCE181', title: 'Introduction to Computing', credits: '1', honors: false,
    prereq_text: null, level: null, dept_code: null, campus: null,
    professor_count: 2, avg_rating: 4, avg_pct_a: null,
    professors: [1, null].map((id) => ({
      instructor_id: id, name: id === null ? 'Unknown professor' : 'TYAGI A', department: 'CSCE',
      adj_rating: 4, adj_difficulty: 3, adj_gpa: null, pct_a: null,
      class_reviews: 2, professor_reviews: 10, sections: 1,
    })),
  }]);
  await openBuilder();
  fireEvent.click(screen.getByRole('button', { name: 'Course explorer' }));
  expect(screen.getByRole('link', { name: 'TYAGI A' }).getAttribute('href')).toBe('/professors/1');
  expect(screen.queryByRole('link', { name: 'Unknown professor' })).toBeNull();
});


it('keeps additional generated options accessible without presenting them as saved schedules', () => {
  setup('FALL 2026', [], Array.from({ length: 4 }, (_, i) => ({ ...plan, id: i + 1, name: `Candidate ${i + 1}` })));
  fireEvent.click(screen.getByRole('button', { name: 'Schedule builder' }));
  expect(screen.queryByRole('heading', { name: 'Candidate 4' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Show all 4 options' }));
  expect(screen.getByRole('heading', { name: 'Candidate 4' })).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Saved schedules' }));
  expect(screen.getByText('No saved schedules yet')).toBeTruthy();
  expect(screen.queryByRole('heading', { name: 'Candidate 4' })).toBeNull();
});

describe('pinning a class by hand', () => {
  it('sends what was pinned as a hard filter, and rebuilds', async () => {
    const props = setup('SPRING 2027');
    await openBuilder();

    fireEvent.click(screen.getByRole('button', { name: 'Pin CSCE 120' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Honors only' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(props.onBuildPlans).toHaveBeenLastCalledWith(
      ['CSCE120'], expect.any(String), 'SPRING 2027', { CSCE120: { honors: true } },
    ));
  });

  it('does not spend a build when the panel is opened and closed unchanged', async () => {
    const props = setup('SPRING 2027');
    await openBuilder();
    const before = props.onBuildPlans.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: 'Pin CSCE 120' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Done' }));

    expect(props.onBuildPlans.mock.calls.length).toBe(before);
  });

  it('a cleared pin is not sent as a constraint that matches everything', async () => {
    const props = setup('SPRING 2027');
    await openBuilder();

    fireEvent.click(screen.getByRole('button', { name: 'Pin CSCE 120' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Honors only' }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));

    await waitFor(() => expect(props.onBuildPlans).toHaveBeenLastCalledWith(
      ['CSCE120'], expect.any(String), 'SPRING 2027', undefined,
    ));
  });
});
