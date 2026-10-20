import { describe, expect, it } from 'vitest';
import { dayNeedsReviewLink, dayPhotoFilters, dayPhotoLink, dayReviewDate } from './dayReviewData';
import { photoListBackLink } from './photoNavigation';

describe('day verification navigation', () => {
  it('reviews late arrivals by the exact photo date and returns to the same day and category', () => {
    const filters = dayPhotoFilters('2026-10-16', 'BIN_EMPTYING', 2);
    expect(filters).toMatchObject({review_day: '2026-10-16', day_review: 'pending', work_only: 'true'});
    const link = new URL(dayPhotoLink(70, '2026-10-16', filters), 'http://test');
    expect(photoListBackLink(70, link.searchParams)).toBe('/days?day=2026-10-16&view=pending&work=BIN_EMPTYING&page=2');
  });
  it('opens all unresolved photos for that photo date independently of the AI gallery filter', () => {
    const link = new URL(dayNeedsReviewLink('2026-10-16'), 'http://test');
    expect(link.pathname).toBe('/review');
    expect(Object.fromEntries(link.searchParams)).toEqual({review_day: '2026-10-16', date_from: '2026-10-16', date_to: '2026-10-16', date_basis: 'photo', work_only: 'true', status: 'NEEDS_REVIEW', sort_order: 'desc'});
  });
  it('falls back from invalid calendar dates in a saved URL', () => {
    for (const value of [null, '2026-99-99', '2026-02-30', 'bad']) expect(dayReviewDate(value, '2026-10-18')).toBe('2026-10-18');
    expect(dayReviewDate('2026-10-16', '2026-10-18')).toBe('2026-10-16');
  });
});
