import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, photoLink, query, reportPhotoLink, shiftDate } from './api';

afterEach(() => vi.unstubAllGlobals());

it('uploads the original image bytes with session credentials and CSRF protection', async () => {
  vi.stubGlobal('document', {cookie: 'csrf=test%2Btoken'});
  const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({avatar_url: '/api/auth/avatar/1?v=photo'})});
  vi.stubGlobal('fetch', fetch);
  const image = new Blob([new Uint8Array([137, 80, 78, 71])], {type: 'image/png'});
  await api('/auth/avatar', 'PUT', image);
  const [url, request] = fetch.mock.calls[0];
  expect(url).toBe('/api/auth/avatar');
  expect(request.body).toBe(image);
  expect(request.credentials).toBe('same-origin');
  expect(request.headers).toEqual({'Content-Type': 'image/png', 'X-CSRF-Token': 'test+token'});
});
describe('report filters and calendar',()=>{
  it('preserves the unassigned district sentinel and removes empty filters',()=>{expect(query({district_id:'0',chat_id:'',status:'NEEDS_REVIEW'})).toBe('district_id=0&status=NEEDS_REVIEW');});
  it('crosses month and year boundaries consistently',()=>{expect(shiftDate('2026-01-01',-1)).toBe('2025-12-31');expect(shiftDate('2024-03-01',-1)).toBe('2024-02-29');});
});

describe('opening the photos counted in a report', () => {
  it('includes archived statuses in the unassigned district with the same sender and date range', () => {
    const filters = {date_from:'2026-10-18', date_to:'2026-10-18', sender_id:'455424204', date_basis:'received', sort_order:'desc'};
    const link = new URL(reportPhotoLink(filters, {district_id:'0'}), 'http://test');
    expect(link.pathname).toBe('/photos');
    expect(Object.fromEntries(link.searchParams)).toEqual({...filters, district_id:'0', work_only:'false'});
  });

  it('keeps all dates rather than reverting to the list default of yesterday', () => {
    const link = new URL(reportPhotoLink({sender_id:'9007199254740993'}, {chat_id:'9007199254740995', work_type:'NONE'}), 'http://test');
    expect(Object.fromEntries(link.searchParams)).toEqual({
      sender_id:'9007199254740993', chat_id:'9007199254740995', work_type:'NONE', work_only:'false', all_dates:'1',
    });
  });

  it('preserves a report restricted to the operator queue and its existing status filters', () => {
    const link = new URL(reportPhotoLink({work_only:'true', status:'NEEDS_REVIEW', accepted_only:'true', operator_id:'0'}, {district_id:'0'}), 'http://test');
    expect(Object.fromEntries(link.searchParams)).toEqual({
      work_only:'true', status:'NEEDS_REVIEW', accepted_only:'true', operator_id:'0', district_id:'0', all_dates:'1',
    });
  });

  it('starts the chosen report group at its first page without stale photo navigation', () => {
    const filters = {status:'NEEDS_REVIEW', page:'4', anchor_id:'999', review:'1', spam:'0', from_map:'1', operator_chat:'2'};
    const link = new URL(reportPhotoLink(filters, {accepted_only:'true'}), 'http://test');
    expect(Object.fromEntries(link.searchParams)).toEqual({status:'NEEDS_REVIEW', accepted_only:'true', work_only:'false', all_dates:'1'});
    expect(filters.page).toBe('4');
  });
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
