import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ProfessorPage from './page';

vi.mock('next/server', () => ({ connection: async () => {} }));
vi.mock('next/navigation', () => ({ notFound: () => { throw new Error('NOT_FOUND'); } }));
vi.mock('@/lib/api', () => ({ getProfessor: vi.fn() }));
import { getProfessor } from '@/lib/api';
afterEach(cleanup);

function profile(count: number) {
 return {
  instructor_id: 1, full_name: 'Test Professor', department: 'CSCE', rmp_id: 123,
  score: { rating_count: 100, adj_rating: 4, raw_rating: 4, adj_difficulty: 3, raw_difficulty: 3, would_take_again_percent: 80, adj_gpa: null },
  courses: [], grades: [], summaries: [],
  recent_comments: Array.from({length: count}, (_, i) => ({ class_code: 'CSCE121', comment: `Review number ${i+1}`, difficulty: 3, rated_at: '2026-01-01' })),
 } as unknown as Awaited<ReturnType<typeof getProfessor>>;
}
it('reveals all 25 stored comments in batches without mistaking profile rating count for loaded reviews', async () => {
 vi.mocked(getProfessor).mockResolvedValue(profile(25));
 render(await ProfessorPage({ params: Promise.resolve({id: '1'}) }));
 expect(screen.queryByText('Review number 6')).toBeNull();
 fireEvent.click(screen.getByRole('button', {name: 'Show more reviews'}));
 expect(screen.getByText('Review number 10')).toBeTruthy();
 for(let i=0; i<3; i++) fireEvent.click(screen.getByRole('button', {name: 'Show more reviews'}));
 expect(screen.getByText('Review number 25')).toBeTruthy();
 expect(screen.queryByRole('button', {name: 'Show more reviews'})).toBeNull();
 expect(screen.getByText('Showing 25 of 25 loaded reviews')).toBeTruthy();
 expect(screen.getByRole('link', {name: 'View on RateMyProfessors'}).getAttribute('href')).toBe('https://www.ratemyprofessors.com/professor/123');
});
it('explains when no review text is available', async () => {
 vi.mocked(getProfessor).mockResolvedValue(profile(0));
 render(await ProfessorPage({ params: Promise.resolve({id: '1'}) }));
 expect(screen.getByText('No review text is available for this professor yet.')).toBeTruthy();
 expect(screen.queryByRole('button', {name: 'Show more reviews'})).toBeNull();
});
