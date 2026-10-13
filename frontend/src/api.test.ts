import { describe, expect, it } from 'vitest';
import { photoLink, query, shiftDate } from './api';
describe('report filters and calendar',()=>{
  it('preserves the unassigned district sentinel and removes empty filters',()=>{expect(query({district_id:'0',chat_id:'',status:'NEEDS_REVIEW'})).toBe('district_id=0&status=NEEDS_REVIEW');});
  it('crosses month and year boundaries consistently',()=>{expect(shiftDate('2026-01-01',-1)).toBe('2025-12-31');expect(shiftDate('2024-03-01',-1)).toBe('2024-02-29');});
});

describe('photo navigation', () => {
  it('keeps the all-dates choice when returning from a photo', () => {
    const link = new URL(photoLink(74, { district_id: '0' }), 'http://test');
    expect(link.pathname).toBe('/photos/74');
    expect(link.searchParams.get('all_dates')).toBe('1');
    expect(link.searchParams.get('district_id')).toBe('0');
  });
  it('preserves the resolved date range and review mode in both photo links', () => {
    const link = new URL(photoLink(74, { date_from: '2026-10-01', date_to: '2026-10-02' }, true), 'http://test');
    expect(link.searchParams.has('all_dates')).toBe(false);
    expect(link.searchParams.get('date_from')).toBe('2026-10-01');
    expect(link.searchParams.get('date_to')).toBe('2026-10-02');
    expect(link.searchParams.get('review')).toBe('1');
  });
});
