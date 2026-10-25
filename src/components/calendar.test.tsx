import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';

import { toCourse } from '@/lib/plans';
import type { ScheduleSection } from '@/lib/api';
import { Planner, type Course, type Plan } from './planner';

afterEach(cleanup);

const section: ScheduleSection = {
  section_id: 1, course_id: 1, code: 'CSCE120', section_code: '501',
  instructor_id: 1, instructor_name: 'Professor', campus: 'CSTAT', delivery: 'F2F',
  honors: false, seats_open: 10, adj_rating: 4, adj_difficulty: 3, adj_gpa: 3,
  pct_a: 0.6, class_reviews: 25, professor_reviews: 25, same_time_alternatives: 0,
  meetings: [
    { day: 'MON', start: '09:00', end: '09:50', building: 'HRBB', room: '101' },
    { day: 'TUE', start: '14:00', end: '15:50', building: 'ZACH', room: '202' },
    { day: 'TUE', start: '17:00', end: '17:50', building: 'ZACH', room: '303' },
    { day: 'SAT', start: '07:00', end: '08:00', building: 'HELD', room: '404' },
    { day: 'SUN', start: '19:00', end: '20:00', building: null, room: null },
  ],
};

async function showCalendar(input = section, course?: Course) {
  const plan: Plan = {
    id: 1, name: 'Best match', subtitle: '', score: 80, rating: '4.0',
    aRate: '60%', gap: '20 min', earliest: '7:00 AM', tags: [],
    courses: [course ?? toCourse(input, 0)],
  };
  const { container } = render(<Planner
    plans={[plan]} courses={[]} student={null} savedCourses={['CSCE120']} savedWants=""
    terms={['FALL 2026']} onSaveCourses={async () => ({ saved: true })}
    onBuildPlans={async () => ({ plans: [plan], relaxed: [] })} onUseSchedule={async () => ({ saved: true })}
  />);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByRole('combobox', { name: 'Semester' });
  return container;
}

it('renders every meeting with its own time and room, including two meetings on one day', async () => {
  const container = await showCalendar();
  const blocks = container.querySelectorAll('.cal article');
  expect(blocks).toHaveLength(5);
  expect(within(blocks[1] as HTMLElement).getAllByText('2:00 PM–3:50 PM').length).toBeGreaterThan(0);
  expect(within(blocks[1] as HTMLElement).getAllByText('ZACH 202').length).toBeGreaterThan(0);
  expect(within(blocks[2] as HTMLElement).getAllByText('ZACH 303').length).toBeGreaterThan(0);
  const mini = container.querySelector('.mini');
  expect(mini?.querySelectorAll('span')).toHaveLength(5);
  const miniBlocks = mini!.querySelectorAll('span');
  expect(miniBlocks[1].style.gridRow).not.toBe(miniBlocks[2].style.gridRow);
});

it('shows weekend columns and expands the clock range for early and evening classes', async () => {
  const container = await showCalendar();
  const calendar = container.querySelector('.cal') as HTMLElement;
  expect(within(calendar).getByText('SAT')).toBeTruthy();
  expect(within(calendar).getByText('SUN')).toBeTruthy();
  expect(within(calendar).getByText('7 AM')).toBeTruthy();
  expect(within(calendar).getByText('7 PM')).toBeTruthy();
  expect(calendar.style.gridTemplateColumns).toBe('var(--cal-gutter) repeat(7, 1fr)');
  const blocks = calendar.querySelectorAll('article');
  expect((blocks[3] as HTMLElement).style.top).toContain('+ 0 *');
  expect((blocks[4] as HTMLElement).style.top).toContain('+ 12 *');
  expect(within(blocks[4] as HTMLElement).getAllByText('Location TBA').length).toBeGreaterThan(0);
});

it('does not invent calendar meetings for an asynchronous online class', async () => {
  const container = await showCalendar({ ...section, delivery: 'WEB', meetings: [] });
  expect(container.querySelectorAll('.cal article')).toHaveLength(0);
  expect(container.querySelectorAll('.cal > header')).toHaveLength(5);
});

it('continues to render older saved courses that have no per-meeting data', async () => {
  const container = await showCalendar(section, {
    code: 'CSCE 120', prof: 'Professor', days: [0, 2],
    start: 9, end: 10, room: 'HRBB 101', color: 'berry',
  });
  const blocks = container.querySelectorAll('.cal article');
  expect(blocks).toHaveLength(2);
  expect(within(blocks[1] as HTMLElement).getAllByText('HRBB 101').length).toBeGreaterThan(0);
});

it('shows each meeting in the schedule analysis instead of repeating the first time', async () => {
  await showCalendar();
  fireEvent.click(screen.getByRole('button', { name: 'View full analysis' }));
  expect(screen.getByText('TUE 2:00 PM–3:50 PM · ZACH 202')).toBeTruthy();
  expect(screen.getByText('TUE 5:00 PM–5:50 PM · ZACH 303')).toBeTruthy();
  expect(screen.getByText('SUN 7:00 PM–8:00 PM · Location TBA')).toBeTruthy();
});

it('labels midnight correctly when the calendar expands to include it', async () => {
  const container = await showCalendar({ ...section, meetings: [
    { day: 'MON', start: '00:00', end: '01:00', building: 'HRBB', room: '101' },
  ] });
  const calendar = container.querySelector('.cal') as HTMLElement;
  expect(within(calendar).getByText('12 AM')).toBeTruthy();
  expect(within(calendar).getAllByText('12:00 AM–1:00 AM').length).toBeGreaterThan(0);
});

it('displays GPA on the academic 0–4 scale rather than the ranking 0–5 scale', async () => {
  const container = await showCalendar({ ...section, adj_gpa: 5 });
  const block = container.querySelector('.cal article') as HTMLElement;
  expect(within(block).getByText('4.00 / 4.0')).toBeTruthy();
});

it('labels a class ending at 24:00 as midnight rather than noon', async () => {
  const container = await showCalendar({ ...section, meetings: [
    { day: 'MON', start: '23:00', end: '24:00', building: 'HRBB', room: '101' },
  ] });
  const block = container.querySelector('.cal article') as HTMLElement;
  expect(within(block).getAllByText('11:00 PM–12:00 AM').length).toBeGreaterThan(0);
});
