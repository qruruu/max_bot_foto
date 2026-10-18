import { describe, expect, it } from 'vitest';
import { filterOptionLabel } from './filterCounts';

describe('counts in filter options', () => {
  const facet = {total: 1240, values: {BIN_EMPTYING: 1200, NONE: 40, '0': 40}};
  it('shows the whole matching count for all options', () => {
    expect(filterOptionLabel('Все виды работ', facet)).toBe('Все виды работ (1\u00a0240)');
  });
  it('shows the count for a category and unassigned values', () => {
    expect(filterOptionLabel('УРНЫ', facet, 'BIN_EMPTYING')).toBe('УРНЫ (1\u00a0200)');
    expect(filterOptionLabel('Не определён', facet, 'NONE')).toBe('Не определён (40)');
    expect(filterOptionLabel('Не проверено', facet, '0')).toBe('Не проверено (40)');
  });
  it('keeps zero alternatives visible and leaves labels intact while loading or on error', () => {
    expect(filterOptionLabel('ГАЗОН', facet, 'GREEN_CLEANING')).toBe('ГАЗОН (0)');
    expect(filterOptionLabel('ГАЗОН', undefined, 'GREEN_CLEANING')).toBe('ГАЗОН');
  });
});
