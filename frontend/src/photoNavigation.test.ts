import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextPhotoId, photoListBackLink, photoListPage } from './photoNavigation';

const fetchMock = vi.fn();
beforeEach(() => {
  vi.stubGlobal('document', {cookie: ''});
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

function respond(value: unknown) {
  fetchMock.mockResolvedValue({ok: true, json: async () => value});
}

describe('next photo in the current list', () => {
  it('advances accepted photos with the same filters across table pages', async () => {
    respond({id: 38});
    const params = new URLSearchParams('review=0&spam=0&work_only=true&status=ACCEPTED&district_id=0&chat_id=123&work_type=SWEEPING&operator_id=2&date_from=2026-10-16&date_to=2026-10-17&date_basis=received&sort_order=asc&page=3&page_size=30&anchor_id=42');
    expect(await nextPhotoId(42, params)).toBe(38);
    const url = new URL(fetchMock.mock.calls[0][0], 'http://test');
    expect(url.pathname).toBe('/api/photos/42/next');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      work_only: 'true', status: 'ACCEPTED', district_id: '0', chat_id: '123', work_type: 'SWEEPING',
      operator_id: '2', date_from: '2026-10-16', date_to: '2026-10-17', date_basis: 'received', sort_order: 'asc',
    });
    expect(params.get('page')).toBe('3');
  });

  it('returns null at the end and keeps all-dates map navigation in the original URL', async () => {
    respond({id: null});
    const params = new URLSearchParams('from_map=1&all_dates=1&district_id=0');
    expect(await nextPhotoId(42, params)).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe('/api/photos/42/next?district_id=0');
    expect(params.toString()).toBe('from_map=1&all_dates=1&district_id=0');
  });

  it('advances the review queue from the current photo rather than its first page', async () => {
    respond({id: 38});
    expect(await nextPhotoId(42, new URLSearchParams('review=1&status=ACCEPTED&page=3'))).toBe(38);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/photos/42/next?status=NEEDS_REVIEW');
    respond({id: null});
    expect(await nextPhotoId(42, new URLSearchParams('review=1'))).toBeNull();
  });

  it('preserves every filter when the server returns an unresolved photo at the end', async () => {
    respond({id: 99});
    expect(await nextPhotoId(12, new URLSearchParams('review=1&chat_id=123&district_id=4&work_type=SWEEPING&date_from=2026-10-16&all_dates=1&anchor_id=12&page=3'))).toBe(99);
    const url = new URL(fetchMock.mock.calls[0][0], 'http://test');
    expect(url.pathname).toBe('/api/photos/12/next');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      chat_id:'123',district_id:'4',work_type:'SWEEPING',date_from:'2026-10-16',status:'NEEDS_REVIEW',
    });
  });

  it('preserves the separate spam list', async () => {
    respond({id: 38});
    expect(await nextPhotoId(42, new URLSearchParams('spam=1'))).toBe(38);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/photos/42/next?status=SPAM');
  });

  it('surfaces navigation failures before saving can begin', async () => {
    fetchMock.mockResolvedValue({ok: false, status: 403, json: async () => ({detail: 'Нет доступа'})});
    await expect(nextPhotoId(42, new URLSearchParams())).rejects.toThrow('Нет доступа');
  });
});

describe('return to the photo list', () => {
  it('preserves the page, all-dates choice and filters and focuses the current photo', () => {
    const params = new URLSearchParams('page=3&all_dates=1&district_id=0&status=ACCEPTED&operator_id=2&review=0&spam=0&anchor_id=99&sort_order=desc');
    const link = new URL(photoListBackLink(42, params), 'http://test');
    expect(link.pathname).toBe('/photos');
    expect(Object.fromEntries(link.searchParams)).toEqual({page:'3',all_dates:'1',district_id:'0',status:'ACCEPTED',operator_id:'2',anchor_id:'42',sort_order:'desc'});
    expect(params.get('anchor_id')).toBe('99');
  });

  it.each([['review', '/review'], ['spam', '/spam']])('returns to the same %s list', (flag, path) => {
    const link = new URL(photoListBackLink(42, new URLSearchParams(`${flag}=1&page=2`)), 'http://test');
    expect(link.pathname).toBe(path);
    expect(link.searchParams.get('page')).toBe('2');
    expect(link.searchParams.get('anchor_id')).toBe('42');
  });

  it('keeps returning to the map independent of table pagination', () => {
    const link = new URL(photoListBackLink(42, new URLSearchParams('from_map=1&page=2&anchor_id=99&all_dates=1&chat_id=123')), 'http://test');
    expect(link.pathname).toBe('/photo-map');
    expect(Object.fromEntries(link.searchParams)).toEqual({all_dates:'1',chat_id:'123'});
  });

  it.each([null, '', '0', '-2', '2.5', 'invalid', 'Infinity', '9007199254740992'])('normalizes invalid page %s', value => {
    expect(photoListPage(value)).toBe(1);
  });

  it('restores a valid page', () => expect(photoListPage('3')).toBe(3));
});
